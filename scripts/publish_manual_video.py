"""Firebase-guarded manual publisher for generated video topics.

DEFAULT: Publishes to YouTube only (single-platform to prevent duplicates).
Multi-platform mode (YouTube + Instagram + Facebook) can be enabled via MULTI_PLATFORM=1.
Enforces Firebase duplicate protection and a two-hour gap between batches.
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from scripts.publish_config import (
    load_config,
    publish_timezone,
    canonical_platform_name,
    get_held_platforms,
    is_platform_held,
    get_enabled_platforms,
    is_platform_enabled,
)
from tools.narration_text import validate_vietnamese_narration
from tools.publish_store import PublishStore, file_sha256, publish_key
from scripts.validate_render_quality import PORTRAIT_DIMENSIONS, resolve_narration, validate_video
from tools.publishers.platform_routes import (
    PLATFORM_ROUTES,
    ensure_youtube_short,
    youtube_shorts_title,
    probe_dimensions,
    VERTICAL_WIDTH,
    VERTICAL_HEIGHT,
    compose_release_metadata,
)
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.tiktok_publisher import TiktokPublisher
from tools.publishers.social_metadata import meta_caption


def build_youtube_payload(
    topic_meta: dict,
    video_path: str,
    publish_at: str | None = None,
    thumbnail_path: str | None = None,
) -> dict:
    """Build unified YouTube Shorts upload payload using compose_release_metadata."""
    payload_meta = dict(topic_meta)
    if "id" not in payload_meta:
        payload_meta["id"] = payload_meta.get("project_id", "news_video")
    rel = compose_release_metadata(payload_meta)
    yt = rel.youtube_payload
    fmt = payload_meta.get("format", "short")
    is_long = fmt in ("longform", "long", "16:9", "16x9", "full")
    title = payload_meta.get("title", yt["title"]) if is_long else yt["title"]
    payload = {
        "video_path": str(video_path),
        "title": title,
        "description": yt["description"],
        "tags": yt["tags"],
        "privacy_status": "private" if publish_at else "unlisted",
        "publish_at": publish_at,
        "category_id": "28",
        "format": fmt,
        "locale": payload_meta.get("locale") or os.environ.get("OPENMONTAGE_LOCALE") or "en-US",
    }
    expected_channel = (
        payload_meta.get("expected_channel_id")
        or os.environ.get("EXPECTED_CHANNEL_ID")
        or os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID")
    )
    if expected_channel:
        payload["expected_channel_id"] = expected_channel
    if "contains_synthetic_media" in payload_meta:
        payload["contains_synthetic_media"] = payload_meta["contains_synthetic_media"]

    # Thumbnail resolution (explicit arg -> topic_meta -> project discovery -> JIT generation)
    thumb = thumbnail_path or payload_meta.get("thumbnail_path") or payload_meta.get("thumbnail")
    if not thumb or not Path(thumb).is_file():
        v_p = Path(video_path)
        candidates = [
            v_p.parent.parent / "artifacts" / "thumbnail.png",
            v_p.parent.parent / "artifacts" / "thumbnail.jpg",
            v_p.parent / "artifacts" / "thumbnail.png",
            v_p.parent / "artifacts" / "thumbnail.jpg",
            v_p.parent.parent / "thumbnails" / "thumbnail.png",
            v_p.parent.parent / "thumbnails" / "thumbnail.jpg",
            v_p.parent / "thumbnail.png",
            v_p.parent / "thumbnail.jpg",
            v_p.parent / "thumbnails" / "thumbnail.png",
            v_p.parent / "thumbnails" / "thumbnail.jpg",
        ]
        for c in candidates:
            if c.is_file():
                thumb = str(c)
                break

    # If still missing, empty, or placeholder (< 50KB), attempt just-in-time generation
    if not thumb or not Path(thumb).is_file() or Path(thumb).stat().st_size < 50_000:
        try:
            from lib.news_visual.thumbnail_orchestrator import ThumbnailOrchestrator
            v_p = Path(video_path)
            pdir = v_p.parent.parent if v_p.parent.name == "renders" else v_p.parent
            if pdir.is_dir() and pdir.name.startswith("cand_"):
                title = payload_meta.get("title") or pdir.name
                res = ThumbnailOrchestrator.generate_thumbnail(
                    project_dir=pdir,
                    title=title,
                    topic=payload_meta.get("topic", "") or payload_meta.get("summary", ""),
                    format_type=payload_meta.get("format", "short"),
                    allow_fallback=True,
                )
                if res.success and res.thumbnail_path and Path(res.thumbnail_path).is_file():
                    thumb = res.thumbnail_path
        except Exception:
            pass

    if thumb and Path(thumb).is_file():
        payload["thumbnail_path"] = str(thumb)

    return payload


_CFG = load_config()
FB_PAGE_ID = _CFG["meta"]["page_id"]
IG_ACCOUNT_ID = _CFG["meta"]["ig_account_id"]
YT_ACCOUNT = _CFG["youtube"]["account"]
PUBLISH_TZ = _CFG.get("timezone", "Asia/Ho_Chi_Minh")
UTC_OFFSET = "+00:00"


def _clear_uniqueness_for_topic(store: PublishStore, topic: str) -> int:
    """Delete all uniqueness documents for a topic so claim() can succeed on re-publish.

    Queries by publish_key prefix (embedded in each uniqueness doc) and deletes each.
    Safe: only clears docs for the specific topic being re-published.
    """
    base_url = store.base_url
    topic_prefix = topic[:20].lower().replace("-", "_")
    deleted = 0
    page_token = None
    while True:
        params = {"pageSize": 300}
        if page_token:
            params["pageToken"] = page_token
        try:
            r = store.session.get(base_url, params=params, timeout=30)
        except Exception as e:
            print(f"[WARN] Could not list uniqueness docs: {e}")
            break
        if r.status_code != 200:
            break
        docs = r.json().get("documents", [])
        if not docs:
            break
        for doc in docs:
            fields = doc.get("fields", {})
            rec_type = fields.get("record_type", {}).get("stringValue", "")
            pub_key = fields.get("publish_key", {}).get("stringValue", "")
            if rec_type == "uniqueness" and topic in pub_key:
                doc_name = doc["name"]
                doc_url = f"{store.documents_url.split('/projects/', 1)[0]}/{doc_name}"
                dr = store.session.delete(doc_url, timeout=30)
                if dr.status_code == 200:
                    deleted += 1
        page_token = r.json().get("nextPageToken")
        if not page_token:
            break
    return deleted


def safe_resolve_publish_path(raw: str | Path, base_dir: Path | None = None) -> Path:
    """Resolve and sanitize path against traversal attacks (CWE-22 / CWE-73)."""
    import tempfile
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = ((base_dir or ROOT) / p)
    resolved = p.resolve()
    allowed_roots = (ROOT.resolve(), Path.cwd().resolve(), Path.home().resolve(), Path(tempfile.gettempdir()).resolve())
    if not any(resolved.is_relative_to(r) for r in allowed_roots if r != Path(r.anchor)):
        raise ValueError(f"Path traversal detected or path outside allowed root: {raw}")
    return resolved


def load_metadata(project_dir: Path) -> dict:
    project_dir = safe_resolve_publish_path(project_dir, ROOT)
    meta_path = project_dir / "publish_metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"publish_metadata.json not found in {project_dir}")
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_video_path(raw: str, project_dir: Path, root: Path) -> Path:
    """Resolve a metadata video path safely.

    - Absolute paths are validated against allowed root directories.
    - Repo-prefixed paths (``projects/...``) resolve against the repo root.
    - Anything else resolves against the project directory.
    """
    p = Path(raw)
    base = root if (p.parts and p.parts[0] == "projects") else project_dir
    return safe_resolve_publish_path(p, base)


def enforce_batch_gap(last_publish_time: str | None) -> None:
    """Enforce at least 2 hours between publishing batches."""
    if not last_publish_time:
        return
    last = datetime.fromisoformat(last_publish_time.replace("Z", UTC_OFFSET))
    now = datetime.now(timezone.utc)
    gap = now - last
    if gap < timedelta(hours=2):
        wait_seconds = (timedelta(hours=2) - gap).total_seconds()
        print(f"Waiting {wait_seconds:.0f} seconds to enforce 2-hour gap...")
        time.sleep(wait_seconds)


def validate_publish_asset(video_path: Path, project_dir: Path, platform: str, strict: bool = False) -> None:
    project_dir = safe_resolve_publish_path(project_dir, ROOT)
    video_path = safe_resolve_publish_path(video_path, project_dir)
    rehearsal_marker = project_dir / "OFFLINE_REHEARSAL_TEST_ONLY.json"
    if rehearsal_marker.exists() or rehearsal_marker.is_symlink():
        raise ValueError(
            f"Release blocked: offline rehearsal test-only marker present in {project_dir.name}"
        )
    ffprobe = shutil.which("ffprobe") or ""
    ffmpeg = shutil.which("ffmpeg") or ""
    if not ffprobe:
        candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
        ffprobe = str(candidates[0]) if candidates else ""
    if not ffmpeg:
        candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
        ffmpeg = str(candidates[0]) if candidates else ""
    if not ffprobe or not ffmpeg:
        raise ValueError("ffprobe and ffmpeg are required for strict publish asset validation")

    meta = {}
    meta_path = project_dir / "publish_metadata.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    fmt = meta.get("format", "short")
    is_longform = fmt in ("longform", "long", "16:9", "16x9", "full")

    narration = resolve_narration(
        project_dir,
        "narration.mp3" if is_longform else ("narration_reels.mp3" if platform in ("youtube", "instagram") else "narration.mp3"),
        "narration.mp3",
    )
    from lib.artifact_paths import resolve_project_locale, is_english_locale, resolve_narration_text_path
    from lib.language_validation import get_language_validator
    locale = resolve_project_locale(project_dir)
    narration_text = resolve_narration_text_path(project_dir, locale=locale)
    if not narration_text.is_file():
        raise ValueError(f"missing narration text: {narration_text}")
    if is_english_locale(locale):
        validator = get_language_validator(locale)
        language_errors = validator.validate_prose(narration_text.read_text(encoding="utf-8"))
    else:
        language_errors = validate_vietnamese_narration(narration_text.read_text(encoding="utf-8"))
    if language_errors:
        raise ValueError("; ".join(language_errors))
    expected_dims = (1920, 1080) if (is_longform and is_english_locale(locale)) else PORTRAIT_DIMENSIONS
    min_dur = 60.0 if is_longform else 14.0
    max_dur = None if is_longform else (180.0 if platform == "youtube" else (60.0 if platform == "instagram" else None))
    errors = validate_video(
        video_path,
        narration,
        ffprobe,
        ffmpeg,
        min_dur,
        3.0,
        expected_dims,
        max_dur,
        narration_text if narration_text.is_file() else None,
        strict=strict,
        locale=locale,
    )
    if errors:
        raise ValueError("\n".join(errors))


def get_required_routes_for_project(
    topic: str,
    project_dir: Path | None = None,
    metadata: dict | None = None,
    ignore_held: bool = False,
    held_platforms: set[str] | list[str] | str | None = None,
    enabled_platforms: set[str] | list[str] | str | None = None,
    ignore_disabled: bool = False,
) -> list[tuple[str, str]]:
    """Determine all required platform routes (platform, kind) for a project."""
    root = ROOT
    pdir = project_dir
    if pdir is None:
        for cand in [root / "projects" / topic, root / "projects_news" / topic, root / "projects" / "instagram" / topic]:
            if cand.is_dir():
                pdir = cand
                break
    meta = metadata
    if meta is None and pdir and (pdir / "publish_metadata.json").is_file():
        try:
            meta = json.loads((pdir / "publish_metadata.json").read_text(encoding="utf-8"))
        except Exception:
            pass

    facebook_enabled = os.environ.get("FACEBOOK_PUBLISH_ENABLED", "1") == "1"

    routes: list[tuple[str, str]] = [("youtube", "short")]

    has_ig = bool(meta and meta.get("ig_reels"))
    if not has_ig and pdir:
        has_ig = (pdir / "renders" / "final_short_en_US_9x16.mp4").is_file() or (pdir / "renders" / "final_reels_vi_9x16.mp4").is_file()
    if has_ig or not meta:
        routes.append(("instagram", "reels"))

    if facebook_enabled:
        has_fb = bool(meta and (meta.get("fb_video") or meta.get("fb_reels")))
        if not has_fb and pdir:
            has_fb = (pdir / "renders" / "final_long_en_US_16x9.mp4").is_file() or (pdir / "renders" / "final_full_vi_9x16.mp4").is_file()
        if has_fb or not meta:
            routes.append(("facebook", "reels"))

    if meta and meta.get("tiktok"):
        routes.append(("tiktok", "video"))

    if not ignore_disabled:
        enabled = get_enabled_platforms(extra_enabled=enabled_platforms)
        if enabled is not None:
            routes = [(platform, kind) for platform, kind in routes if platform in enabled]

    if not ignore_held:
        held = get_held_platforms(extra_held=held_platforms)
        if held:
            routes = [(platform, kind) for platform, kind in routes if platform not in held]

    return routes


def canonical_platform_records_published(
    store: PublishStore,
    *,
    date: str,
    topic: str,
    project_dir: Path | None = None,
    routes: list[tuple[str, str]] | None = None,
    held_platforms: set[str] | list[str] | str | None = None,
    enabled_platforms: set[str] | list[str] | str | None = None,
) -> bool:
    try:
        if routes:
            return all(
                (record := store.get(publish_key(date, topic, platform, kind)))
                and record.get("status") == "published"
                for platform, kind in routes
            )
        if store is not None and date:
            from scripts.check_cleanup_eligibility import reconcile_project_publications
            req_routes = get_required_routes_for_project(
                topic,
                project_dir=project_dir,
                held_platforms=held_platforms,
                enabled_platforms=enabled_platforms,
            )
            if req_routes:
                reconcile_project_publications(store, topic, date, req_routes)

        from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
        eligible, reason, _ = is_project_eligible_for_cleanup(
            topic,
            project_dir=project_dir,
            store=store,
            date=date,
            held_platforms=held_platforms,
            enabled_platforms=enabled_platforms,
        )
        if not eligible:
            print(f"Publication not complete for {topic}: {reason}", file=sys.stderr)
        return eligible
    except Exception as exc:
        print(f"Failed to verify Firebase publish completion: {exc}", file=sys.stderr)
        return False


def _resolve_scheduled_publish(
    metadata: dict,
    publish_date: str,
    cfg: dict,
) -> tuple[datetime, int]:
    """Derive publish datetime + epoch from queue metadata (next-day schedule)."""
    publish_time = metadata.get("publish_time")
    if not publish_time:
        # Remaining live paths: not a queued publish — require explicit routing.
        # Keep this non-silent: callers with publish_time=None and date=None should
        # run in immediate-unlisted mode only by explicit opt-in (see publish_batch).
        raise ValueError("publish_time missing from metadata; cannot derive scheduled publish time")

    hh, mm = publish_time.split(":", 1)
    tz = publish_timezone(cfg)
    local_dt = datetime.fromisoformat(f"{publish_date}T{int(hh):02d}:{int(mm):02d}:00").replace(tzinfo=tz)
    # If someone passes publish_time in UTC-like form, attach tz properly; no wall-clock drift.
    # publish_date+publish_time ARE the source of truth.
    scheduled_epoch = int(local_dt.astimezone(timezone.utc).timestamp())
    publish_at_iso = local_dt.astimezone(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
    return datetime.fromisoformat(publish_at_iso.replace("Z", UTC_OFFSET)).replace(tzinfo=timezone.utc), scheduled_epoch


def _facebook_preflight_error() -> str | None:
    try:
        from tools.publishers.facebook_publisher import FacebookPublisher
        fb_pub = FacebookPublisher()
        readiness = fb_pub.check_readiness()
        if readiness.get("status") in ("enabled", "ok") or readiness.get("configured") is True:
            return None
    except Exception:
        pass
    mp = MetaPublisher()
    fb_token = os.environ.get("TOKEN_FACEBOOK", "")
    if fb_token:
        try:
            _ = mp._get_page_info(fb_token, FB_PAGE_ID)
            return None
        except Exception as e:
            return f"Meta Facebook Page access unavailable for {FB_PAGE_ID}: {e}"
    gw_url = os.environ.get("FACEBOOK_GATEWAY_BASE_URL", "http://127.0.0.1:20129/custom/facebook")
    return (
        f"Facebook publishing unavailable: Toolcase Gateway not reachable at {gw_url} "
        "(port 20129) and TOKEN_FACEBOOK is not configured."
    )


def _resolve_instagram_account_id(mp: MetaPublisher, fb_token: str) -> str | None:
    if IG_ACCOUNT_ID:
        return IG_ACCOUNT_ID
    try:
        info = mp._get_page_info(fb_token, FB_PAGE_ID)
        return (info.get("instagram_business_account") or {}).get("id")
    except Exception:
        return None


def _instagram_preflight_error() -> str | None:
    mp = MetaPublisher()
    fb_token = os.environ.get("TOKEN_FACEBOOK", "")
    ig_acct = _resolve_instagram_account_id(mp, fb_token)
    if not ig_acct:
        return "Instagram Business Account unavailable: IG_ACCOUNT_ID not configured and Page lookup failed."
    try:
        _ = mp._get_instagram_info(fb_token, ig_acct)
        return None
    except Exception as e:
        return f"Meta Instagram access unavailable for ig_account_id {ig_acct}: {e}"


def _meta_preflight_error_for_platform(platform: str) -> str | None:
    if platform == "facebook":
        return _facebook_preflight_error()
    if platform == "instagram":
        return _instagram_preflight_error()
    return None


def _resolve_single_platform_contract(
    only_platform: str,
    enabled_platforms: Any,
    held_platforms: Any,
    yt_kind: str,
    yt_field: str,
    results: dict,
) -> list[tuple[str, str, str, str]] | None:
    canon = canonical_platform_name(only_platform)
    effective = set(enabled_platforms) if enabled_platforms else set()
    effective.add(canon)
    if not is_platform_enabled(canon, extra_enabled=effective, extra_held=held_platforms):
        reason = "held" if is_platform_held(canon, extra_held=held_platforms) else "disabled"
        print(f"⏸️ {reason.upper()}: Platform {canon} is {reason} by pipeline flag/env/config. Skipping publish.")
        kind = PLATFORM_ROUTES.get(canon, ("short", ""))[0]
        results["platforms"][f"{canon}/{kind}"] = {"status": "held", "reason": f"{canon} {reason} by pipeline flag/env/config"}
        return None
    accounts = {"instagram": IG_ACCOUNT_ID, "facebook": FB_PAGE_ID, "youtube": YT_ACCOUNT}
    acct = accounts.get(canon, "")
    k = yt_kind if canon == "youtube" else PLATFORM_ROUTES.get(canon, ("", ""))[0]
    f = yt_field if canon == "youtube" else PLATFORM_ROUTES.get(canon, ("", ""))[1]
    if not k:
        raise ValueError(f"No platform configured for {canon}")
    return [(canon, acct, k, f)]


def _resolve_cfg_enabled_candidates(
    cfg_enabled: set[str],
    yt_kind: str,
    yt_field: str,
) -> list[tuple[str, str, str, str]]:
    contract_candidates: list[tuple[str, str, str, str]] = []
    if "youtube" in cfg_enabled:
        contract_candidates.append(("youtube", YT_ACCOUNT, yt_kind, yt_field))
    if "instagram" in cfg_enabled:
        contract_candidates.append(("instagram", IG_ACCOUNT_ID, PLATFORM_ROUTES["instagram"][0], PLATFORM_ROUTES["instagram"][1]))
    if "facebook" in cfg_enabled:
        contract_candidates.append(("facebook", FB_PAGE_ID, PLATFORM_ROUTES["facebook"][0], PLATFORM_ROUTES["facebook"][1]))
    if "tiktok" in cfg_enabled:
        contract_candidates.append(("tiktok", "tiktok", PLATFORM_ROUTES["tiktok"][0], PLATFORM_ROUTES["tiktok"][1]))
    for p in cfg_enabled:
        if p not in ("youtube", "instagram", "facebook", "tiktok") and p in PLATFORM_ROUTES:
            contract_candidates.append((p, "", PLATFORM_ROUTES[p][0], PLATFORM_ROUTES[p][1]))
    print("📋 CONFIG-ENABLED PLATFORMS MODE: " + " + ".join(p for p, _, _, _ in contract_candidates))
    return contract_candidates


def _resolve_multi_platform_candidates() -> list[tuple[str, str, str, str]]:
    fb_on = os.environ.get("FACEBOOK_PUBLISH_ENABLED", "1") == "1"
    tt_on = os.environ.get("TIKTOK_PUBLISH_ENABLED", "0") in ("1", "true", "True")
    platforms = [("youtube", YT_ACCOUNT), ("instagram", IG_ACCOUNT_ID)]
    if fb_on:
        platforms.append(("facebook", FB_PAGE_ID))
    if tt_on:
        platforms.append(("tiktok", "tiktok"))
    print("🌐 MULTI-PLATFORM MODE: " + " + ".join(p for p, _ in platforms))
    return [(p, acct, PLATFORM_ROUTES[p][0], PLATFORM_ROUTES[p][1]) for p, acct in platforms]


def _filter_active_platforms(
    contract: list[tuple[str, str, str, str]],
    enabled_platforms: Any,
    held_platforms: Any,
    results: dict,
) -> list[tuple[str, str, str, str]]:
    active = []
    for platform, account, kind, field in contract:
        if not is_platform_enabled(platform, extra_enabled=enabled_platforms, extra_held=held_platforms):
            reason = "held" if is_platform_held(platform, extra_held=held_platforms) else "disabled"
            print(f"⏸️ {reason.upper()}: Skipping {platform} (platform is {reason} by pipeline flag/env/config)")
            results["platforms"][f"{platform}/{kind}"] = {"status": "held", "reason": f"{platform} {reason} by pipeline flag/env/config"}
        else:
            active.append((platform, account, kind, field))
    return active


def _resolve_platform_contract(
    only_platform: str | None,
    instagram_mode: bool,
    cfg_enabled: set[str] | None,
    multi_platform: bool,
    yt_kind: str,
    yt_field: str,
    enabled_platforms: Any,
    held_platforms: Any,
    results: dict,
) -> list[tuple[str, str, str, str]] | None:
    if only_platform:
        return _resolve_single_platform_contract(
            only_platform, enabled_platforms, held_platforms, yt_kind, yt_field, results
        )

    if instagram_mode:
        print("📸 INSTAGRAM MODE: Instagram only (Instagram cron job)")
        contract = [("instagram", IG_ACCOUNT_ID, PLATFORM_ROUTES["instagram"][0], PLATFORM_ROUTES["instagram"][1])]
    elif cfg_enabled is not None:
        contract = _resolve_cfg_enabled_candidates(cfg_enabled, yt_kind, yt_field)
    elif multi_platform:
        contract = _resolve_multi_platform_candidates()
    else:
        print("🎯 SINGLE-PLATFORM MODE: YouTube only (set MULTI_PLATFORM=1 for multi-platform)")
        contract = [("youtube", YT_ACCOUNT, yt_kind, yt_field)]

    return _filter_active_platforms(contract, enabled_platforms, held_platforms, results)


def _normalize_facebook_format(meta: dict) -> None:
    if "fb_video" not in meta and "fb_reels" in meta:
        meta["fb_video"] = meta["fb_reels"]


def _normalize_youtube_format(meta: dict, is_longform: bool) -> None:
    if is_longform:
        if "yt_longform" not in meta and "yt_shorts" in meta:
            meta["yt_longform"] = meta["yt_shorts"]
    elif "yt_shorts" not in meta and "yt_longform" in meta:
        meta["yt_shorts"] = meta["yt_longform"]


def _resolve_vertical_tiktok_candidate(meta: dict) -> str | None:
    for cand in ("yt_shorts", "ig_reels"):
        cand_val = str(meta.get(cand, ""))
        if cand in meta and any(k in cand_val for k in ("9x16", "short", "reels")):
            return meta[cand]
    return None


def _normalize_tiktok_format(meta: dict) -> None:
    if "tiktok" not in meta:
        for cand in ("yt_shorts", "ig_reels"):
            if cand in meta:
                meta["tiktok"] = meta[cand]
                return
    elif "16x9" in str(meta["tiktok"]) or "long" in str(meta["tiktok"]):
        replacement = _resolve_vertical_tiktok_candidate(meta)
        if replacement:
            meta["tiktok"] = replacement


def _normalize_metadata_formats(metadata: dict, is_longform: bool) -> dict:
    meta = dict(metadata)
    _normalize_facebook_format(meta)
    _normalize_youtube_format(meta, is_longform)
    _normalize_tiktok_format(meta)
    return meta


def _upload_youtube(metadata: dict, video_path: Path, publish_at: str | None, kind: str, dry_run: bool) -> tuple[dict, Any]:
    publisher = YoutubePublisher()
    try:
        inputs = build_youtube_payload(metadata, video_path=str(video_path), publish_at=publish_at)
    except ValueError as exc:
        return {"success": False, "error": f"metadata invalid: {exc}"}, publisher

    if dry_run:
        print(f"[DRY RUN] Would upload YouTube {kind}: {video_path}")
        return {"success": True, "video_id": "DRY_RUN_ID", "video_url": "https://example.com/dry-run"}, publisher

    tool_res = publisher.execute(inputs)
    data = tool_res.data or {}
    if tool_res.success:
        res = {
            "success": True,
            "video_id": data.get("video_id"),
            "video_url": data.get("video_url"),
            "thumbnail_status": data.get("thumbnail_status"),
            "thumbnail_path": data.get("thumbnail_path"),
            "error": None,
        }
    else:
        res = {
            "success": False,
            "video_id": None,
            "video_url": None,
            "thumbnail_status": None,
            "thumbnail_path": None,
            "error": tool_res.error,
        }
    return res, publisher


def _extract_meta_platform_id(platform: str, data: dict) -> str | None:
    if platform == "facebook":
        return data.get("facebook_post_id") or data.get("video_id")
    return data.get("instagram_media_id")


def _extract_meta_video_url(platform: str, account: str, platform_id: str | None, data: dict) -> str | None:
    if platform != "facebook":
        return None
    if data.get("video_url"):
        return data["video_url"]
    if platform_id:
        return f"https://facebook.com/{account}/videos/{platform_id}"
    return None


def _upload_meta(
    platform: str,
    account: str,
    kind: str,
    title: str,
    description: str,
    video_path: Path,
    cfg: dict,
    dry_run: bool,
    blocked_meta_reason: dict[str, str],
) -> tuple[dict, Any]:
    publisher = MetaPublisher()
    if platform in blocked_meta_reason and not dry_run:
        return {"success": False, "error": blocked_meta_reason[platform]}, publisher
    if dry_run:
        print(f"[DRY RUN] Would upload {platform} {kind}: {video_path}")
        return {
            "success": True,
            "platform_id": f"DRY_RUN_{platform.upper()}_ID",
            "video_url": f"https://facebook.com/{account}/videos/dry-run",
        }, publisher

    inputs = {
        "video_path": video_path,
        "title": title,
        "caption": meta_caption(title, description),
        "page_id": FB_PAGE_ID,
        "instagram_account_id": IG_ACCOUNT_ID,
        "post_to_facebook": platform == "facebook",
        "post_to_instagram": platform == "instagram",
    }
    if cfg.get("scheduled_epoch") and platform == "facebook":
        inputs["scheduled_publish_time"] = int(cfg["scheduled_epoch"])

    if platform == "facebook":
        tool_result = _execute_facebook_upload(video_path, title, description, cfg, inputs, publisher)
    else:
        tool_result = publisher.execute(inputs)

    data = tool_result.data or {}
    platform_id = _extract_meta_platform_id(platform, data)
    video_url = _extract_meta_video_url(platform, account, platform_id, data)
    success = bool(tool_result.success and platform_id)
    error_msg = None if success else (tool_result.error or f"Meta returned no {platform} media ID")

    res = {
        "success": success,
        "platform_id": platform_id,
        "video_url": video_url,
        "error": error_msg,
    }
    return res, publisher


def _execute_facebook_upload(video_path: Path, title: str, description: str, cfg: dict, inputs: dict, publisher: MetaPublisher) -> Any:
    try:
        from tools.publishers.facebook_publisher import FacebookPublisher
        fb_pub = FacebookPublisher()
        fb_inputs = {
            "video_path": str(video_path),
            "title": title,
            "caption": meta_caption(title, description),
            "target_id": FB_PAGE_ID,
            "enable_auto_translate": True,
            "publish_type": "REEL",
        }
        if cfg.get("scheduled_epoch"):
            sched_epoch = int(cfg["scheduled_epoch"])
            if sched_epoch >= int(time.time()) + 600:
                fb_inputs["scheduled_publish_time"] = sched_epoch
            else:
                cfg["scheduled_epoch"] = None
        tool_res = fb_pub.execute(fb_inputs)
    except Exception as fb_exc:
        from tools.base_tool import ToolResult
        tool_res = ToolResult(success=False, error=str(fb_exc))

    if not tool_res.success and os.environ.get("TOKEN_FACEBOOK"):
        tool_res = publisher.execute(inputs)
    return tool_res


def _build_tiktok_result(tool_result: Any, project_id: str | None, data: dict) -> dict:
    has_remote = bool(project_id or data.get("status") in ("published", "scheduled"))
    success = bool(tool_result.success and has_remote)

    video_url = data.get("video_url")
    if not video_url and project_id:
        video_url = f"https://www.tiktok.com/video/{project_id}"

    error_msg = None
    if not tool_result.success:
        error_msg = tool_result.error or "TikTok publish failed"

    return {
        "success": success,
        "platform_id": project_id,
        "video_id": data.get("item_id") or project_id,
        "video_url": video_url,
        "error": error_msg,
    }


def _upload_tiktok(platform: str, kind: str, title: str, description: str, video_path: Path, cfg: dict, dry_run: bool) -> tuple[dict, Any]:
    publisher = TiktokPublisher()
    if dry_run:
        print(f"[DRY RUN] Would upload {platform} {kind}: {video_path}")
        return {
            "success": True,
            "platform_id": "DRY_RUN_TIKTOK_PROJECT_ID",
            "video_id": "DRY_RUN_TIKTOK_VIDEO_ID",
            "video_url": "https://www.tiktok.com/@creator/video/dry-run",
        }, publisher

    caption = f"{title}\n\n{description}".strip() if description else title
    inputs = {
        "video_path": str(video_path),
        "caption": caption,
        "title": title,
        "visibility": os.environ.get("TIKTOK_DEFAULT_VISIBILITY", "only-me"),
    }
    if cfg.get("scheduled_epoch"):
        inputs["schedule_time"] = int(cfg["scheduled_epoch"])
    tool_result = publisher.execute(inputs)
    data = tool_result.data or {}
    project_id = data.get("project_id") or data.get("item_id")
    return _build_tiktok_result(tool_result, project_id, data), publisher


def _check_youtube_remote_status(publisher: Any, vid_id: str) -> dict | None:
    if not hasattr(publisher, "check_video_published"):
        return None
    v_info = publisher.check_video_published(vid_id)
    if v_info and v_info.get("privacy_status") and v_info.get("upload_status"):
        return {"privacy_status": v_info["privacy_status"], "upload_status": v_info["upload_status"]}
    return None


def _check_meta_remote_status(publisher: Any, platform: str, vid_id: str) -> dict | None:
    if not hasattr(publisher, "check_media_published"):
        return None
    m_info = publisher.check_media_published(vid_id, platform=platform)
    if m_info and m_info.get("status"):
        return m_info
    return None


def _check_tiktok_remote_status(publisher: Any, vid_id: str) -> dict | None:
    if not hasattr(publisher, "check_video_published"):
        return None
    t_info = publisher.check_video_published(vid_id)
    if t_info and t_info.get("status"):
        return t_info
    return None


def _check_remote_published_status(publisher: Any, platform: str, vid_id: str | None) -> dict | None:
    if not vid_id:
        return None
    try:
        if platform == "youtube":
            return _check_youtube_remote_status(publisher, vid_id)
        if platform in ("instagram", "facebook"):
            return _check_meta_remote_status(publisher, platform, vid_id)
        if platform == "tiktok":
            return _check_tiktok_remote_status(publisher, vid_id)
    except Exception:
        pass
    return None


def _update_store_success(
    store: PublishStore, key: str, platform: str, vid_id: str | None, vid_url: str | None, is_scheduled: bool, publish_at: str | None, cfg: dict, video_path: Path, publisher: Any
) -> None:
    try:
        if is_scheduled:
            sched_target = publish_at or (
                datetime.fromtimestamp(cfg["scheduled_epoch"], tz=timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
                if cfg.get("scheduled_epoch")
                else datetime.now(timezone.utc).isoformat()
            )
            store.mark_scheduled(key, video_id=vid_id, video_url=vid_url, scheduled_for=sched_target)
            print(f"✅ Firebase record updated: {key} -> scheduled")
        else:
            now_iso = datetime.now(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
            remote_st = _check_remote_published_status(publisher, platform, vid_id)
            is_verified = bool(remote_st and (remote_st.get("upload_status") == "processed" or remote_st.get("status") == "published"))
            verified_at = now_iso if is_verified else None
            store.mark_published(
                key, video_id=vid_id, video_url=vid_url, published_at=now_iso, verified_at=verified_at,
                remote_status=remote_st, media_sha256=file_sha256(video_path) if video_path and Path(video_path).is_file() else None,
            )
            print(f"✅ Firebase record updated: {key} -> published")
    except Exception as fb_error:
        print(f"❌ Firebase update failed for {key}: {fb_error}")


def _is_platform_scheduled(platform: str, cfg: dict, publish_at: str | None) -> bool:
    if platform == "instagram":
        return False
    if platform in ("facebook", "tiktok") and cfg.get("scheduled_epoch"):
        return True
    if platform == "youtube" and publish_at:
        return True
    return False


def _record_platform_publish_result(
    store: PublishStore | None,
    key: str,
    platform: str,
    kind: str,
    result: dict,
    cfg: dict,
    publish_at: str | None,
    video_path: Path,
    publisher: Any,
    results: dict,
) -> None:
    if not (result and result.get("success")):
        error_msg = result.get("error", "Unknown upload error") if result else "No result returned"
        if store:
            try:
                store.mark_failed(key, error_msg)
            except Exception as fb_err:
                print(f"❌ Firebase mark_failed failed for {key}: {fb_err}")
        results["platforms"][f"{platform}/{kind}"] = {"status": "failed", "error": error_msg}
        results["errors"].append(f"{platform}/{kind} upload failed: {error_msg}")
        return

    vid_id = result.get("video_id") or result.get("platform_id")
    vid_url = result.get("video_url")
    is_scheduled = _is_platform_scheduled(platform, cfg, publish_at)
    record_status = "scheduled" if is_scheduled else "published"
    if store:
        _update_store_success(store, key, platform, vid_id, vid_url, is_scheduled, publish_at, cfg, video_path, publisher)

    results["platforms"][f"{platform}/{kind}"] = {
        "status": record_status,
        "video_id": vid_id,
        "video_url": vid_url,
    }


def _resolve_batch_schedule(metadata: dict, date: str | None) -> tuple[str | None, int | None]:
    if not metadata.get("publish_time"):
        return None, None
    publish_date_for_schedule = date if date else metadata.get("publish_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        _, scheduled_epoch = _resolve_scheduled_publish(metadata, publish_date_for_schedule, load_config())
        publish_at_iso = datetime.fromtimestamp(scheduled_epoch, tz=timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
        return publish_at_iso, scheduled_epoch
    except Exception:
        return None, None


def _build_platform_configs(
    platform_contract: list[tuple[str, str, str, str]],
    metadata: dict,
    publish_at_iso: str | None,
    scheduled_epoch: int | None,
    only_platform: str | None,
) -> list[dict]:
    platforms = [
        {
            "platform": platform,
            "account": account,
            "kind": kind,
            "title": (
                youtube_shorts_title(metadata["title"])
                if platform == "youtube" and kind == "short"
                else metadata["title"]
            ),
            "description": metadata["description"],
            "video_path": metadata[field],
            "publish_at": publish_at_iso,
            "scheduled_epoch": scheduled_epoch,
        }
        for platform, account, kind, field in platform_contract
    ]
    if only_platform:
        platforms = [c for c in platforms if c["platform"] == only_platform]
    return platforms


def _should_enforce_preflight(enforce_preflight: bool | None, project_dir: Path, metadata: dict) -> bool:
    if enforce_preflight is not None:
        return enforce_preflight
    return bool(
        (project_dir / "project.json").is_file()
        or (project_dir / "approval.json").is_file()
        or (project_dir / "human_approval.json").is_file()
        or "human_approval" in metadata
        or os.environ.get("PRODUCTION_RELEASE") == "1"
        or os.environ.get("STRICT_PRODUCTION") == "1"
    )


def _validate_batch_assets(platforms: list[dict], project_dir: Path, root: Path) -> None:
    for cfg in platforms:
        video_path = resolve_video_path(cfg["video_path"], project_dir, root)
        validate_publish_asset(video_path, project_dir, cfg["platform"], strict=True)


def _collect_blocked_meta_reasons(
    platforms: list[dict],
    dry_run: bool,
    enforce_meta_preflight: bool | None,
    raw_enforce_preflight: bool | None,
) -> dict[str, str]:
    if dry_run:
        return {}
    if enforce_meta_preflight is not None:
        should_enforce = enforce_meta_preflight
    elif raw_enforce_preflight is not None:
        should_enforce = raw_enforce_preflight
    else:
        should_enforce = True
    if not should_enforce:
        return {}
    blocked: dict[str, str] = {}
    for p in platforms:
        plat = p["platform"]
        if plat in ("facebook", "instagram") and plat not in blocked:
            err = _meta_preflight_error_for_platform(plat)
            if err:
                blocked[plat] = err
    return blocked


def _clear_forced_publish(store: PublishStore, today: str, metadata_id: str, platform: str, kind: str) -> None:
    from scripts.clear_uniqueness import clear_uniqueness
    clear_uniqueness(store, metadata_id)
    key = publish_key(today, metadata_id, platform, kind)
    store.session.delete(store._url(key), timeout=30)


def _handle_dry_run_platform(
    platform: str,
    kind: str,
    video_path: Path,
    results: dict,
) -> None:
    exists = video_path.exists()
    status_str = "found" if exists else "MISSING"
    print(f"[DRY RUN] {platform}/{kind}: would upload {video_path} ({status_str})")
    results["platforms"][f"{platform}/{kind}"] = {"status": "dry_run", "video_path": str(video_path), "video_exists": exists}
    if not exists:
        results["errors"].append(f"{platform}/{kind} video not found: {video_path}")


def _handle_unclaimed_reservation(
    store: PublishStore,
    key: str,
    today: str,
    metadata_id: str,
    platform: str,
    kind: str,
    existing: dict | None,
    retry_failed: bool,
    results: dict,
) -> bool:
    """Handle an unclaimed existing record. Returns True if upload should proceed, False if skipped."""
    existing_status = existing.get("status") if existing else "unknown"
    has_remote_id = bool(existing and (existing.get("video_id") or existing.get("platform_id")))

    if retry_failed and existing_status == "failed":
        if has_remote_id:
            print(f"[RETRY CHECK] Existing record {key} already has remote ID; skipping duplicate upload")
            results["platforms"][f"{platform}/{kind}"] = {"status": "skipped", "reason": "existing_remote_id", "existing_record": existing}
            return False
        k = publish_key(today, metadata_id, platform, kind)
        now_iso = datetime.now(timezone.utc).isoformat()
        store.update(k, {"status": "uploading", "error": None, "retry_started_at": now_iso, "updated_at": now_iso})
        return True

    if existing_status == "scheduling" and not has_remote_id:
        print(f"[RESERVATION RESUME] Found queued reservation for {key} without remote ID; resuming upload.")
        k = publish_key(today, metadata_id, platform, kind)
        now_iso = datetime.now(timezone.utc).isoformat()
        store.update(k, {"status": "uploading", "error": None, "worker_started_at": now_iso, "updated_at": now_iso})
        return True

    results["platforms"][f"{platform}/{kind}"] = {"status": "skipped", "reason": "duplicate", "existing_record": existing}
    return False


def _dispatch_platform_upload(
    platform: str,
    account: str,
    kind: str,
    title: str,
    description: str,
    video_path: Path,
    metadata: dict,
    publish_at: str | None,
    cfg: dict,
    dry_run: bool,
    blocked_meta_reason: dict[str, str],
    results: dict,
) -> tuple[dict, Any]:
    if platform == "youtube":
        return _upload_youtube(metadata, video_path, publish_at, kind, dry_run)
    if platform in ("instagram", "facebook"):
        return _upload_meta(platform, account, kind, title, description, video_path, cfg, dry_run, blocked_meta_reason)
    if platform == "tiktok":
        return _upload_tiktok(platform, kind, title, description, video_path, cfg, dry_run)
    err = f"Unsupported platform: {platform}"
    results["errors"].append(err)
    return {"success": False, "error": err}, None


def publish_batch(
    metadata: dict,
    project_dir: Path,
    store: PublishStore | None,
    dry_run: bool = False,
    retry_failed: bool = False,
    only_platform: str | None = None,
    force: bool = False,
    date: str | None = None,
    strict: bool = True,
    enforce_preflight: bool | None = None,
    held_platforms: set[str] | list[str] | str | None = None,
    enabled_platforms: set[str] | list[str] | str | None = None,
    enforce_meta_preflight: bool | None = None,
) -> dict:
    """Publish one topic to configured platforms with Firebase guards."""
    results = {"platforms": {}, "errors": [], "batch_started_at": datetime.now(timezone.utc).isoformat()}
    root = Path(__file__).resolve().parents[1]
    project_dir = safe_resolve_publish_path(project_dir, root)

    from lib.news_release_gate import require_news_evidence
    require_news_evidence(project_dir, metadata=metadata)

    multi_platform = os.environ.get("MULTI_PLATFORM", "0") == "1"
    instagram_mode = os.environ.get("INSTAGRAM_MODE", "0") == "1"

    fmt = metadata.get("format", "short")
    is_longform = fmt in ("longform", "long", "16:9", "16x9", "full")
    yt_kind = "longform" if is_longform else PLATFORM_ROUTES["youtube"][0]
    yt_field = "yt_longform" if is_longform else PLATFORM_ROUTES["youtube"][1]

    cfg_enabled = get_enabled_platforms(extra_enabled=enabled_platforms)

    platform_contract = _resolve_platform_contract(
        only_platform, instagram_mode, cfg_enabled, multi_platform, yt_kind, yt_field, enabled_platforms, held_platforms, results
    )
    if not platform_contract:
        return results

    metadata = _normalize_metadata_formats(metadata, is_longform)
    missing = [field for _, _, _, field in platform_contract if field not in metadata]
    if missing:
        raise KeyError(f"publish_metadata.json missing platform video fields: {', '.join(missing)}")

    publish_at_iso, scheduled_epoch = _resolve_batch_schedule(metadata, date)
    platforms = _build_platform_configs(platform_contract, metadata, publish_at_iso, scheduled_epoch, only_platform)

    raw_enforce_preflight = enforce_preflight
    should_preflight = _should_enforce_preflight(enforce_preflight, project_dir, metadata)
    if should_preflight:
        enforce_release_preflight(project_dir, metadata, platforms=platforms, strict=strict, force=force)

    _validate_batch_assets(platforms, project_dir, root)

    today = date if date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocked_meta_reason = _collect_blocked_meta_reasons(
        platforms, dry_run, enforce_meta_preflight, raw_enforce_preflight
    )

    for cfg in platforms:
        platform = cfg["platform"]
        account = cfg["account"]
        kind = cfg["kind"]
        title = cfg["title"]
        description = cfg["description"]
        video_path = resolve_video_path(cfg["video_path"], project_dir, root)
        publish_at = cfg["publish_at"]

        if force and store and not dry_run:
            _clear_forced_publish(store, today, metadata["id"], platform, kind)

        if dry_run:
            _handle_dry_run_platform(platform, kind, video_path, results)
            continue

        key, claimed, existing = store.claim(
            date=today,
            topic=metadata["id"],
            platform=platform,
            account=account,
            kind=kind,
            status="scheduling",
            title=title,
            asset_path=video_path,
            source_topic=metadata.get("topic", metadata["id"]),
            scheduled_for=publish_at,
        )

        if not claimed and not _handle_unclaimed_reservation(store, key, today, metadata["id"], platform, kind, existing, retry_failed, results):
            continue

        result, publisher = _dispatch_platform_upload(
            platform, account, kind, title, description, video_path, metadata, publish_at, cfg, dry_run, blocked_meta_reason, results
        )
        _record_platform_publish_result(store, key, platform, kind, result, cfg, publish_at, video_path, publisher, results)

    return results


def validate_project_quality(project_path: Path, strict: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]

    # Step 1: Validate metadata text fields (hashtags, shell syntax, placeholders)
    try:
        youtube_shorts_title(load_metadata(project_path)["title"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"YouTube Shorts title validation failed: {exc}") from exc

    metadata_validator = root / "scripts" / "validate_publish_metadata.py"
    if not metadata_validator.is_file():
        raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: metadata validator required")

    result = subprocess.run(
        [sys.executable, str(metadata_validator), str(project_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        diagnostic = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise RuntimeError(diagnostic or f"metadata validator exited {result.returncode}")

    # Step 2: Codex Agent Strict Quality Validation (mandatory when strict=True)
    if strict:
        val_status_file = project_path / "validation_status.json"
        already_valid = False
        if val_status_file.is_file():
            try:
                v_data = json.loads(val_status_file.read_text(encoding="utf-8"))
                records = v_data if isinstance(v_data, list) else [v_data]
                for rec in reversed(records):
                    if rec.get("status") == "PASS" and rec.get("strict_quality_pass") is True:
                        already_valid = True
                        break
            except Exception:
                already_valid = False

        if not already_valid:
            agent_validator = root / "scripts" / "codex_agent_validation.py"
            if not agent_validator.is_file():
                raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: Codex agent validator required")

            env = dict(os.environ)
            ffprobe = shutil.which("ffprobe") or ""
            ffmpeg = shutil.which("ffmpeg") or ""
            if not ffprobe:
                candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
                if candidates:
                    env["PATH"] = str(candidates[0].parent) + ":" + env.get("PATH", "")
                    ffprobe = str(candidates[0])
            if not ffmpeg:
                candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
                if candidates:
                    ffmpeg = str(candidates[0])

            cmd = [sys.executable, str(agent_validator), str(project_path), "--strict", "--retry", "3"]
            if ffprobe:
                cmd.extend(["--ffprobe", ffprobe])
            if ffmpeg:
                cmd.extend(["--ffmpeg", ffmpeg])

            val_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
            )
            if val_result.returncode:
                diagnostic = "\n".join(part.strip() for part in (val_result.stdout, val_result.stderr) if part.strip())
                err_detail = diagnostic or f"validator exited {val_result.returncode}"
                raise RuntimeError(f"Codex Agent strict validation failed: {err_detail}")

    # Step 3: Validate video/audio content (dimensions, codecs, black frames, silent audio)
    ffprobe = shutil.which("ffprobe") or ""
    ffmpeg = shutil.which("ffmpeg") or ""
    if not ffprobe:
        candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
        ffprobe = str(candidates[0]) if candidates else ""
    if not ffmpeg:
        candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
        ffmpeg = str(candidates[0]) if candidates else ""
    validate_script = root / "scripts" / "validate_render_quality.py"
    if not validate_script.is_file() or not ffprobe or not ffmpeg:
        raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: validator, ffprobe, and ffmpeg are required")
    meta = load_metadata(project_path)
    fmt = meta.get("format")
    from lib.artifact_paths import resolve_project_locale, is_english_locale
    locale = resolve_project_locale(project_path)
    is_en = is_english_locale(locale)

    command = [
        sys.executable,
        str(validate_script),
        str(project_path),
        "--ffprobe",
        ffprobe,
        "--ffmpeg",
        ffmpeg,
    ]
    if is_en:
        if fmt in ("short", "shorts", "reels", "9x16"):
            command.extend(["--render", "reels", "--reels-max-duration", "180"])
        elif fmt in ("long", "longform", "16x9", "full"):
            command.extend(["--render", "full"])
        else:
            if (project_path / "renders" / "final_short_en_US_9x16.mp4").is_file():
                command.extend(["--render", "reels", "--reels-max-duration", "180"])
            elif (project_path / "renders" / "final_long_en_US_16x9.mp4").is_file():
                command.extend(["--render", "full"])
    else:
        command.extend(["--reels-max-duration", "60"])

    if strict:
        command.append("--strict")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        diagnostic = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise RuntimeError(diagnostic or f"validator exited {result.returncode}")


def enforce_release_preflight(
    project_dir: Path,
    metadata: dict,
    *,
    platforms: list[dict] | None = None,
    strict: bool = True,
    force: bool = False,
) -> None:
    """Unified release preflight gate.

    Enforces:
    1. Strict video, audio, and metadata quality validation.
    2. Stage checkpoints & prerequisites from selected pipeline manifest.
    3. Required stage artifacts from pipeline manifest.
    4. Explicit human approval bound to exact media SHA-256, target account, copy, and release time.
    5. Block publication on asset or copy changes until re-validated and re-approved.
    6. Force flags cannot bypass quality gates or approvals.
    """
    root = Path(__file__).resolve().parents[1]

    # --- Step 1: Quality Validation ---
    validate_project_quality(project_dir, strict=strict)

    # --- Step 2: Pipeline Checkpoints & Artifacts ---
    project_marker = project_dir / "project.json"
    pipeline_type = metadata.get("pipeline_type")
    if project_marker.is_file():
        try:
            with project_marker.open("r", encoding="utf-8") as f:
                marker_data = json.load(f)
            if not pipeline_type:
                pipeline_type = marker_data.get("pipeline_type")
        except Exception as e:
            raise RuntimeError(f"Release preflight failed: Invalid project.json: {e}") from e

    from lib.news_release_gate import is_news_project
    is_news = is_news_project(project_dir, metadata)

    if pipeline_type:
        from lib.checkpoint import (
            get_pipeline_stages,
            _stage_requires_approval,
            validate_checkpoint,
            CANONICAL_STAGE_ARTIFACTS,
        )
        from lib.pipeline_loader import load_pipeline_readonly

        try:
            stages = get_pipeline_stages(pipeline_type)
        except Exception:
            stages = []

        publish_idx = stages.index("publish") if "publish" in stages else len(stages)
        predecessor_stages = stages[:publish_idx]

        manifest_stages_dict = {}
        try:
            manifest = load_pipeline_readonly(pipeline_type)
            for st in manifest.get("stages", []):
                manifest_stages_dict[st.get("name")] = st
        except Exception:
            pass

        is_interactive_production = bool(
            (project_dir / "checkpoint_proposal.json").is_file()
            or (not is_news and (project_dir / "approval.json").is_file())
            or (project_dir / "human_approval.json").is_file()
            or "human_approval" in metadata
        )

        for st_name in predecessor_stages:
            cp_file = project_dir / f"checkpoint_{st_name}.json"
            if not cp_file.is_file():
                if is_news and not is_interactive_production:
                    # In automated unattended news pipeline, only the research stage creates a checkpoint;
                    # subsequent stages run unattended and are verified by validate_project_quality.
                    continue
                raise RuntimeError(
                    f"Release preflight failed: Missing required stage checkpoint for {st_name!r} "
                    f"(expected {cp_file.name})"
                )
            try:
                with cp_file.open("r", encoding="utf-8") as f:
                    cp_data = json.load(f)
                validate_checkpoint(cp_data)
            except Exception as e:
                raise RuntimeError(
                    f"Release preflight failed: Invalid checkpoint for stage {st_name!r}: {e}"
                ) from e

            if cp_data.get("status") != "completed":
                raise RuntimeError(
                    f"Release preflight failed: Stage {st_name!r} status is {cp_data.get('status')!r}, "
                    f"expected 'completed'"
                )

            # Check human approval on gated stages
            if _stage_requires_approval(pipeline_type, st_name) and not cp_data.get("human_approved"):
                raise RuntimeError(
                    f"Release preflight failed: Stage {st_name!r} requires human approval "
                    f"but human_approved is false"
                )

            # Check produced artifacts
            produced = []
            if st_name in manifest_stages_dict:
                produced = manifest_stages_dict[st_name].get("produces", [])
            elif st_name in CANONICAL_STAGE_ARTIFACTS:
                produced = [CANONICAL_STAGE_ARTIFACTS[st_name]]

            for art in produced:
                art_in_cp = isinstance(cp_data.get("artifacts"), dict) and art in cp_data["artifacts"]
                art_on_disk = (
                    (project_dir / "artifacts" / f"{art}.json").is_file()
                    or (project_dir / "artifacts" / f"{art}_vi.json").is_file()
                    or (project_dir / f"{art}.json").is_file()
                )
                if not (art_in_cp or art_on_disk):
                    raise RuntimeError(
                        f"Release preflight failed: Missing required stage artifact {art!r} "
                        f"for stage {st_name!r}"
                    )

    # --- Step 3: Explicit Human Approval Bound to Media SHA-256 ---
    is_interactive_production = bool(
        (project_dir / "checkpoint_proposal.json").is_file()
        or (project_dir / "approval.json").is_file()
        or (project_dir / "human_approval.json").is_file()
        or "human_approval" in metadata
    )
    if is_news and not is_interactive_production:
        requires_approval = False
    else:
        requires_approval = bool(
            project_marker.is_file()
            or is_interactive_production
            or os.environ.get("PRODUCTION_RELEASE") == "1"
            or os.environ.get("STRICT_PRODUCTION") == "1"
        )

    if requires_approval:
        approval = None
        if "human_approval" in metadata and isinstance(metadata["human_approval"], dict):
            approval = metadata["human_approval"]
        elif (project_dir / "approval.json").is_file():
            try:
                with (project_dir / "approval.json").open("r", encoding="utf-8") as f:
                    approval = json.load(f)
            except Exception as e:
                raise RuntimeError(f"Release preflight failed: Invalid approval.json: {e}") from e
        elif (project_dir / "human_approval.json").is_file():
            try:
                with (project_dir / "human_approval.json").open("r", encoding="utf-8") as f:
                    approval = json.load(f)
            except Exception as e:
                raise RuntimeError(f"Release preflight failed: Invalid human_approval.json: {e}") from e

        if isinstance(approval, list):
            approval = approval[-1] if approval else None

        if not approval or not isinstance(approval, dict):
            raise RuntimeError(
                f"Release preflight failed: Missing explicit human approval record for {project_dir.name}. "
                f"Publication requires human approval bound to media SHA-256."
            )

        if not (approval.get("approved") is True or approval.get("status") == "approved"):
            raise RuntimeError(
                f"Release preflight failed: Human approval status is not approved "
                f"(status={approval.get('status')!r}, approved={approval.get('approved')!r})"
            )

        from lib.artifact_paths import resolve_project_locale, is_english_locale
        locale = resolve_project_locale(project_dir)
        is_us = is_english_locale(locale) or metadata.get("audience") == "us"
        if is_us or "signature" in approval:
            if not approval or not isinstance(approval, dict):
                raise RuntimeError("Release preflight failed: mandatory approval.json missing or invalid for US project")
            from lib.qa_signing import verify_approval_record
            valid_sig, sig_msg = verify_approval_record(
                approval, project_dir.name, project_dir=project_dir, require_manifest=is_us
            )
            if not valid_sig:
                raise RuntimeError(f"Release preflight failed: {sig_msg}")

            # Strict claim ledger verification for US projects
            ledger_file = project_dir / "artifacts" / "claim_ledger.json"
            if is_us:
                if not ledger_file.is_file():
                    raise RuntimeError("Release preflight failed: mandatory claim_ledger.json missing for US project")
                import hashlib
                h_c = hashlib.sha256(ledger_file.read_bytes()).hexdigest()
                approved_claim_sha = approval.get("claim_ledger_sha256")
                if approved_claim_sha and h_c != approved_claim_sha:
                    raise RuntimeError(f"Release preflight failed: claim ledger SHA-256 mismatch ({h_c} != {approved_claim_sha})")

        # Build list of media files to check
        media_to_check: list[tuple[str, Path]] = []
        if platforms:
            for p in platforms:
                vp = resolve_video_path(p["video_path"], project_dir, root)
                media_to_check.append((p["platform"], vp))
        else:
            for k in ("yt_shorts", "yt_longform", "youtube_video", "ig_reels", "fb_video", "fb_reels"):
                if k in metadata:
                    vp = resolve_video_path(metadata[k], project_dir, root)
                    plat = "youtube" if "yt" in k else ("instagram" if "ig" in k else "facebook")
                    media_to_check.append((plat, vp))

        approved_sha = approval.get("approved_media_sha256") or approval.get("media_sha256")
        approved_hashes_list = approval.get("approved_media_hashes", [])
        approved_by_plat = approval.get("media_sha256_by_platform", {})

        for plat, v_path in media_to_check:
            if not v_path.is_file():
                continue
            actual_sha = file_sha256(v_path)
            plat_approved_sha = approved_by_plat.get(plat) or approved_sha

            hash_matched = (
                (plat_approved_sha and actual_sha == plat_approved_sha)
                or (actual_sha in approved_hashes_list)
            )
            if not hash_matched:
                raise RuntimeError(
                    f"Release preflight failed: Media SHA-256 mismatch for {v_path.name} on {plat}. "
                    f"File SHA-256 is {actual_sha}, but approved hash is {plat_approved_sha!r}. "
                    f"Asset has been modified after human approval!"
                )

            # Check Stale Review against validation_status.json
            val_status_file = project_dir / "validation_status.json"
            if val_status_file.is_file():
                inspected_hashes = set()
                try:
                    with val_status_file.open("r", encoding="utf-8") as f:
                        v_stat = json.load(f)
                    entries = v_stat if isinstance(v_stat, list) else [v_stat]
                    # The logger appends history; never merge superseded reviews.
                    for entry in reversed(entries):
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("project_id") not in (None, project_dir.name):
                            continue
                        hashes = [entry.get("inspected_artifact_hash")]
                        details = entry.get("details")
                        results = details.get("results", []) if isinstance(details, dict) else []
                        if isinstance(results, list):
                            for result in results:
                                result_details = result.get("details") if isinstance(result, dict) else None
                                if isinstance(result_details, dict):
                                    hashes.append(result_details.get("inspected_artifact_hash"))
                        inspected_hashes = {h for h in hashes if isinstance(h, str) and h}
                        if inspected_hashes:
                            break
                except (json.JSONDecodeError, OSError):
                    pass
                # A review covers full and reels media with no per-result path labels.
                if inspected_hashes and actual_sha not in inspected_hashes:
                    raise RuntimeError(
                        f"Release preflight failed: Stale validation review! "
                        f"Codex agent inspected hashes {sorted(inspected_hashes)}, but media file hash is {actual_sha}. "
                        f"Re-validation required."
                    )

        # Check Copy: Title & Description
        approved_title = approval.get("approved_title") or approval.get("title")
        if approved_title is not None and metadata.get("title") != approved_title:
            raise RuntimeError(
                f"Release preflight failed: Post title has been altered since approval. "
                f"Approved: {approved_title!r}, Current: {metadata.get('title')!r}"
            )

        approved_desc = approval.get("approved_description") or approval.get("description")
        if approved_desc is not None and metadata.get("description") != approved_desc:
            raise RuntimeError(
                f"Release preflight failed: Post description has been altered since approval. "
                f"Approved: {approved_desc!r}, Current: {metadata.get('description')!r}"
            )

        # Check Target Account
        approved_accounts = approval.get("target_accounts", {})
        if not approved_accounts and approval.get("account"):
            approved_accounts = {"all": approval.get("account")}
        if platforms:
            for p in platforms:
                plat = p["platform"]
                acct = p.get("account", "")
                target_match = approved_accounts.get(plat) or approved_accounts.get("all")
                if target_match and str(target_match) != str(acct):
                    raise RuntimeError(
                        f"Release preflight failed: Target account mismatch for {plat}. "
                        f"Configured account: {acct!r}, Approved account: {target_match!r}"
                    )

        # Check Release Time / Scheduled Time
        approved_time = (
            approval.get("release_time")
            or approval.get("publish_time")
            or approval.get("scheduled_for")
        )
        if approved_time is not None:
            actual_time = metadata.get("publish_time") or metadata.get("publish_date")
            if actual_time and approved_time != actual_time and not approved_time.startswith(str(actual_time)):
                raise RuntimeError(
                    f"Release preflight failed: Release time mismatch. "
                    f"Approved: {approved_time!r}, Scheduled: {actual_time!r}"
                )


def main():
    parser = argparse.ArgumentParser(description="Firebase-guarded manual publisher for generated videos")
    parser.add_argument("project_dir", help="Path to generated project directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only records marked failed")
    parser.add_argument("--date", type=str, default=None, help="Force date for this run")
    parser.add_argument("--force", action="store_true", help="Force re-publish even if already uploaded/published")
    parser.add_argument("--only-platform", type=str, default=None, help="Limit publishing to one platform (e.g. ig, fb, tiktok, ytb)")
    parser.add_argument("--last-publish", type=str, default=None, help="Last publish timestamp (ISO8601) for gap enforcement")
    parser.add_argument(
        "--hold-platform",
        action="append",
        default=[],
        dest="hold_platforms_list",
        help="Hold (pause/skip) publishing to specific platform (e.g. ig, fb, tiktok, ytb). Can be repeated.",
    )
    parser.add_argument(
        "--hold-platforms",
        type=str,
        default="",
        help="Comma-separated platforms to hold (e.g. 'ig,fb,tiktok,ytb')",
    )
    parser.add_argument("--hold-ig", action="store_true", help="Hold Instagram publishing")
    parser.add_argument("--hold-fb", action="store_true", help="Hold Facebook publishing")
    parser.add_argument("--hold-tiktok", action="store_true", help="Hold TikTok publishing")
    parser.add_argument("--hold-ytb", action="store_true", help="Hold YouTube publishing")
    parser.add_argument(
        "--enabled-platforms",
        type=str,
        default="",
        help="Comma or space separated platforms to enable (e.g. 'ytb' or 'youtube,instagram')",
    )
    parser.add_argument(
        "--enable-platform",
        action="append",
        default=[],
        dest="enabled_platforms_list",
        help="Enable a specific platform (e.g. ytb, ig, fb, tiktok). Can be repeated.",
    )
    args = parser.parse_args()

    project_path = safe_resolve_publish_path(args.project_dir, ROOT)
    if not project_path.exists():
        print(f"Error: Project directory not found: {project_path}")
        sys.exit(1)

    cli_held: list[str] = list(args.hold_platforms_list)
    if args.hold_platforms:
        cli_held.append(args.hold_platforms)
    if args.hold_ig:
        cli_held.append("instagram")
    if args.hold_fb:
        cli_held.append("facebook")
    if args.hold_tiktok:
        cli_held.append("tiktok")
    if args.hold_ytb:
        cli_held.append("youtube")

    cli_enabled: list[str] = list(args.enabled_platforms_list)
    if args.enabled_platforms:
        cli_enabled.append(args.enabled_platforms)
    if not cli_enabled:
        cli_enabled = None

    only_platform = canonical_platform_name(args.only_platform) if args.only_platform else None

    # Load metadata
    try:
        metadata = load_metadata(project_path)
    except Exception as e:
        print(f"Error loading metadata: {e}")
        sys.exit(1)

    try:
        from lib.news_release_gate import require_news_evidence
        require_news_evidence(project_path, metadata=metadata)
        # Skip release preflight if only targeted platform is held or disabled
        if not (only_platform and not is_platform_enabled(only_platform, extra_enabled=cli_enabled, extra_held=cli_held)):
            preflight_platforms = None
            if only_platform:
                yt_kind = "short" if metadata.get("format") == "short" else "longform"
                yt_field = "yt_shorts" if yt_kind == "short" else "yt_longform"
                from tools.publishers.platform_routes import PLATFORM_ROUTES
                field = yt_field if only_platform == "youtube" else PLATFORM_ROUTES.get(only_platform, ("", "video"))[1]
                acct = (
                    YT_ACCOUNT
                    if only_platform == "youtube"
                    else (
                        IG_ACCOUNT_ID
                        if only_platform == "instagram"
                        else (
                            FB_PAGE_ID
                            if only_platform == "facebook"
                            else ("tiktok" if only_platform == "tiktok" else "")
                        )
                    )
                )
                if field in metadata:
                    preflight_platforms = [{"platform": only_platform, "account": acct, "video_path": metadata[field]}]
            enforce_release_preflight(project_path, metadata, platforms=preflight_platforms, strict=True, force=args.force)
    except Exception as exc:
        print(f"STRICT QUALITY GATE FAILED for {metadata['id']}:")
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    # Enforce batch gap
    enforce_batch_gap(args.last_publish)

    # Dry runs must not initialize or mutate Firebase.
    if args.dry_run:
        store = None
    else:
        try:
            store = PublishStore()
        except Exception as e:
            print(f"Error initializing Firebase store: {e}")
            sys.exit(1)

    # Publish batch
    results = publish_batch(
        metadata,
        project_path,
        store,
        dry_run=args.dry_run,
        retry_failed=args.retry_failed,
        only_platform=only_platform,
        force=args.force,
        date=args.date,
        strict=True,
        enforce_preflight=False,
        held_platforms=cli_held,
        enabled_platforms=cli_enabled,
        enforce_meta_preflight=not args.force,
    )

    # Print summary
    print("\n=== Publish Summary ===")
    print(f"Project: {metadata['id']}")
    print(f"Batch started: {results['batch_started_at']}")
    print(f"Dry run: {args.dry_run}")
    print()

    for platform_kind, status in results["platforms"].items():
        status_str = status["status"]
        if status_str == "published":
            print(f"✅ {platform_kind}: {status['video_id']}")
            print(f"   URL: {status['video_url']}")
        elif status_str in ("skipped", "held"):
            reason = status.get("reason", "unknown")
            print(f"⏸️  {platform_kind}: HELD/SKIPPED ({reason})")
        elif status_str == "dry_run":
            state = "found" if status.get("video_exists") else "MISSING"
            print(f"✅ {platform_kind}: DRY RUN ({state})")
        else:
            print(f"❌ {platform_kind}: {status_str}")
            if "error" in status:
                print(f"   Error: {status['error']}")

    if results["errors"]:
        print("\n=== Errors ===")
        for err in results["errors"]:
            print(f"- {err}")

    # Dry-run validation succeeds only when every selected asset exists.
    if args.dry_run:
        failed_checks = sum(1 for s in results["platforms"].values() if not s.get("video_exists"))
        if failed_checks:
            print(f"\n❌ Dry run failed: {failed_checks} video asset(s) missing")
            return 1
        print(f"\n✅ Dry run completed for {len(results['platforms'])} platform uploads")
        return 0

    total_platforms = len(results["platforms"])
    today = args.date if args.date else datetime.now(timezone.utc).date().isoformat()

    batch_success_count = sum(
        1 for s in results["platforms"].values()
        if s.get("status") in ("published", "scheduled", "skipped", "held")
    )
    batch_succeeded = (batch_success_count == total_platforms) and len(results["errors"]) == 0

    all_canonical_published = canonical_platform_records_published(
        store, date=today, topic=metadata["id"], project_dir=project_path, held_platforms=cli_held, enabled_platforms=cli_enabled
    )

    if all_canonical_published:
        print(f"\n✅ All canonical platform records verified for {metadata['id']} ({batch_success_count}/{total_platforms} in this batch)")
        if not args.dry_run:
            from scripts.publish_active_projects import deactivate_project
            instagram_mode = os.environ.get("INSTAGRAM_MODE", "0") == "1"
            if not deactivate_project(
                metadata["id"],
                project_dir=project_path,
                store=store,
                date=today,
                instagram_mode=instagram_mode,
                held_platforms=cli_held,
                enabled_platforms=cli_enabled,
            ):
                print("\n❌ Cleanup blocked: canonical Firebase publish records are incomplete; project retained")
                return 1
        return 0
    elif batch_succeeded:
        print(
            f"\n✅ Batch completed for requested platforms ({batch_success_count}/{total_platforms}). "
            f"Project retained for remaining scheduled/pending platforms."
        )
        return 0

    print(f"\n❌ Incomplete batch: {batch_success_count}/{total_platforms} uploads succeeded; errors: {results['errors']}; project retained")
    return 1


if __name__ == "__main__":
    sys.exit(main())
