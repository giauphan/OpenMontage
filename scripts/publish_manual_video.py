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

from scripts.publish_config import (
    load_config,
    publish_timezone,
    canonical_platform_name,
    get_held_platforms,
    is_platform_held,
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
from tools.publishers.social_metadata import meta_caption


def build_youtube_payload(topic_meta: dict, video_path: str, publish_at: str | None = None) -> dict:
    """Build unified YouTube Shorts upload payload using compose_release_metadata."""
    payload_meta = dict(topic_meta)
    if "id" not in payload_meta:
        payload_meta["id"] = payload_meta.get("project_id", "news_video")
    rel = compose_release_metadata(payload_meta)
    yt = rel.youtube_payload
    return {
        "video_path": str(video_path),
        "title": yt["title"],
        "description": yt["description"],
        "tags": yt["tags"],
        "privacy_status": "private" if publish_at else "unlisted",
        "publish_at": publish_at,
        "category_id": "28",
    }


_CFG = load_config()
FB_PAGE_ID = _CFG["meta"]["page_id"]
IG_ACCOUNT_ID = _CFG["meta"]["ig_account_id"]
YT_ACCOUNT = _CFG["youtube"]["account"]
PUBLISH_TZ = _CFG.get("timezone", "Asia/Ho_Chi_Minh")


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


def load_metadata(project_dir: Path) -> dict:
    meta_path = project_dir / "publish_metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"publish_metadata.json not found in {project_dir}")
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_video_path(raw: str, project_dir: Path, root: Path) -> Path:
    """Resolve a metadata video path.

    - Absolute paths are used as-is.
    - Repo-prefixed paths (``projects/...``) resolve against the repo root.
    - Anything else resolves against the project directory.
    """
    p = Path(raw)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "projects":
        return (root / p).resolve()
    return (project_dir / p).resolve()


def enforce_batch_gap(last_publish_time: str | None) -> None:
    """Enforce at least 2 hours between publishing batches."""
    if not last_publish_time:
        return
    last = datetime.fromisoformat(last_publish_time.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    gap = now - last
    if gap < timedelta(hours=2):
        wait_seconds = (timedelta(hours=2) - gap).total_seconds()
        print(f"Waiting {wait_seconds:.0f} seconds to enforce 2-hour gap...")
        time.sleep(wait_seconds)


def validate_publish_asset(video_path: Path, project_dir: Path, platform: str, strict: bool = False) -> None:
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

    narration = resolve_narration(
        project_dir,
        "narration_reels.mp3" if platform in ("youtube", "instagram") else "narration.mp3",
        "narration.mp3",
    )
    narration_text = project_dir / "artifacts" / "narration_vi_text.txt"
    if not narration_text.is_file():
        raise ValueError(f"missing narration text: {narration_text}")
    language_errors = validate_vietnamese_narration(narration_text.read_text(encoding="utf-8"))
    if language_errors:
        raise ValueError("; ".join(language_errors))
    errors = validate_video(
        video_path,
        narration,
        ffprobe,
        ffmpeg,
        14.0,
        3.0,
        PORTRAIT_DIMENSIONS,
        60.0 if platform in ("youtube", "instagram") else None,
        narration_text if narration_text.is_file() else None,
        strict=strict,
    )
    if errors:
        raise ValueError("\n".join(errors))


def get_required_routes_for_project(
    topic: str,
    project_dir: Path | None = None,
    metadata: dict | None = None,
    ignore_held: bool = False,
    held_platforms: set[str] | list[str] | str | None = None,
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
        has_ig = (pdir / "renders" / "final_reels_vi_9x16.mp4").is_file()
    if has_ig or not meta:
        routes.append(("instagram", "reels"))

    if facebook_enabled:
        has_fb = bool(meta and (meta.get("fb_video") or meta.get("fb_reels")))
        if not has_fb and pdir:
            has_fb = (pdir / "renders" / "final_full_vi_9x16.mp4").is_file()
        if has_fb or not meta:
            routes.append(("facebook", "reels"))

    if meta and meta.get("tiktok"):
        routes.append(("tiktok", "video"))

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
) -> bool:
    try:
        if routes:
            return all(
                (record := store.get(publish_key(date, topic, platform, kind)))
                and record.get("status") == "published"
                for platform, kind in routes
            )
        from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
        eligible, reason, _ = is_project_eligible_for_cleanup(
            topic, project_dir=project_dir, store=store, date=date, held_platforms=held_platforms
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
    publish_at_iso = local_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromisoformat(publish_at_iso.replace("Z", "+00:00")).replace(tzinfo=timezone.utc), scheduled_epoch


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
) -> dict:
    """Publish one topic to configured platforms with Firebase guards."""
    results = {"platforms": {}, "errors": [], "batch_started_at": datetime.now(timezone.utc).isoformat()}
    root = Path(__file__).resolve().parents[1]

    # News evidence is an unconditional release gate, independent of quality
    # preflight toggles and force/retry modes. It must precede claims and uploads.
    from lib.news_release_gate import require_news_evidence
    require_news_evidence(project_dir, metadata=metadata)

    # Metadata contract: the shared route table owns platform -> field/kind mapping.
    # DEFAULT BEHAVIOR: Single-platform publishing to prevent duplicates
    # Multi-platform mode can be enabled via MULTI_PLATFORM=1 environment variable
    # Instagram mode (INSTAGRAM_MODE=1): Instagram only (for Instagram cron jobs)
    multi_platform = os.environ.get("MULTI_PLATFORM", "0") == "1"
    instagram_mode = os.environ.get("INSTAGRAM_MODE", "0") == "1"
    
    if only_platform:
        only_platform = canonical_platform_name(only_platform)
        if is_platform_held(only_platform, extra_held=held_platforms):
            print(f"⏸️ HOLD: Platform {only_platform} is held by pipeline flag/env. Skipping publish.")
            kind = PLATFORM_ROUTES.get(only_platform, ("short", ""))[0]
            results["platforms"][f"{only_platform}/{kind}"] = {
                "status": "held",
                "reason": f"{only_platform} held by pipeline flag/env",
            }
            return results

        if only_platform == "instagram":
            platform_contract = [("instagram", IG_ACCOUNT_ID, PLATFORM_ROUTES["instagram"][0], PLATFORM_ROUTES["instagram"][1])]
        elif only_platform == "facebook":
            platform_contract = [("facebook", FB_PAGE_ID, PLATFORM_ROUTES["facebook"][0], PLATFORM_ROUTES["facebook"][1])]
        elif only_platform == "youtube":
            platform_contract = [("youtube", YT_ACCOUNT, PLATFORM_ROUTES["youtube"][0], PLATFORM_ROUTES["youtube"][1])]
        elif only_platform in PLATFORM_ROUTES:
            platform_contract = [(only_platform, "", PLATFORM_ROUTES[only_platform][0], PLATFORM_ROUTES[only_platform][1])]
        else:
            raise ValueError(f"No platform configured for {only_platform}")
    elif instagram_mode:
        print("📸 INSTAGRAM MODE: Instagram only (Instagram cron job)")
        platform_contract = [
            (platform, account, PLATFORM_ROUTES[platform][0], PLATFORM_ROUTES[platform][1])
            for platform, account in (("instagram", IG_ACCOUNT_ID),)
        ]
    elif multi_platform:
        facebook_enabled = os.environ.get("FACEBOOK_PUBLISH_ENABLED", "1") == "1"
        platforms = [("youtube", YT_ACCOUNT), ("instagram", IG_ACCOUNT_ID)]
        if facebook_enabled:
            platforms.append(("facebook", FB_PAGE_ID))
        print("🌐 MULTI-PLATFORM MODE: " + " + ".join(platform for platform, _ in platforms))
        platform_contract = [
            (platform, account, PLATFORM_ROUTES[platform][0], PLATFORM_ROUTES[platform][1])
            for platform, account in platforms
        ]
    else:
        print("🎯 SINGLE-PLATFORM MODE: YouTube only (set MULTI_PLATFORM=1 for multi-platform)")
        platform_contract = [
            (platform, account, PLATFORM_ROUTES[platform][0], PLATFORM_ROUTES[platform][1])
            for platform, account in (("youtube", YT_ACCOUNT),)
        ]

    # Filter out held platforms from platform contract
    active_contract = []
    for platform, account, kind, field in platform_contract:
        if is_platform_held(platform, extra_held=held_platforms):
            print(f"⏸️ HOLD: Skipping {platform} (platform is held by pipeline flag/env)")
            results["platforms"][f"{platform}/{kind}"] = {
                "status": "held",
                "reason": f"{platform} held by pipeline flag/env",
            }
        else:
            active_contract.append((platform, account, kind, field))

    platform_contract = active_contract
    if not platform_contract:
        print("⏸️ All candidate platforms for this batch are currently held. Exiting batch cleanly.")
        return results
    
    if "fb_video" not in metadata and "fb_reels" in metadata:
        metadata = {**metadata, "fb_video": metadata["fb_reels"]}
    missing = [field for _, _, _, field in platform_contract if field not in metadata]
    if missing:
        raise KeyError(f"publish_metadata.json missing platform video fields: {', '.join(missing)}")
    # Publish-time IS the source of truth for queued items: derive from config/publish_schedule.json
    # via publish_date. The metadata file is NOT the schedule — use the explicit `date` arg (which
    # publish_active_projects forwards from the queue entry) and only fall back to metadata for
    # legacy/manual single-project runs.
    publish_date_for_schedule = date if date else metadata.get("publish_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    publish_at_iso: str | None = None
    scheduled_epoch: int | None = None
    # Derive a scheduled time only when the queue actually placed this project (publish_time present).
    # Otherwise this is a manual/immediate run → publish_at stays None → YouTube unlisted, Facebook immediate.
    if metadata.get("publish_time"):
        try:
            _, scheduled_epoch = _resolve_scheduled_publish(metadata, publish_date_for_schedule, load_config())
            publish_at_iso = datetime.fromtimestamp(scheduled_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            publish_at_iso = None
            scheduled_epoch = None

    platforms = [
        {
            "platform": platform,
            "account": account,
            "kind": kind,
            "title": (
                youtube_shorts_title(metadata["title"])
                if platform == "youtube"
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
        platforms = [cfg for cfg in platforms if cfg["platform"] == only_platform]
    if not platforms:
        raise ValueError(f"No platform configured for {only_platform}")

    # Enforce release preflight (quality gates, checkpoints, human approval).
    # Preflight failure halts before making upload API calls or DB writes.
    if enforce_preflight is None:
        enforce_preflight = bool(
            (project_dir / "project.json").is_file()
            or (project_dir / "approval.json").is_file()
            or (project_dir / "human_approval.json").is_file()
            or "human_approval" in metadata
            or os.environ.get("PRODUCTION_RELEASE") == "1"
            or os.environ.get("STRICT_PRODUCTION") == "1"
        )

    if enforce_preflight:
        enforce_release_preflight(
            project_dir,
            metadata,
            platforms=platforms,
            strict=strict,
            force=force,
        )

    # Validate exact selected assets before any Firebase claim or mutation.
    for cfg in platforms:
        video_path = resolve_video_path(cfg["video_path"], project_dir, root)
        validate_publish_asset(video_path, project_dir, cfg["platform"], strict=True)

    today = date if date else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fail-closed Meta preflight: never attempt IG/FB with a transparently-doomed token.
    # IMPORTANT: this must never block YouTube. Gate each platform independently and fail
    # the blocked ones as "failed" (visible failure), while YouTube still runs.
    def _meta_preflight_error_for_platform(platform: str) -> str | None:
        mp = MetaPublisher()
        fb_token = os.environ.get("TOKEN_FACEBOOK", "")
        if platform == "facebook":
            try:
                _ = mp._get_page_info(fb_token, FB_PAGE_ID)
            except Exception as e:
                return f"Meta Facebook Page access unavailable for {FB_PAGE_ID}: {e}"
            return None
        if platform == "instagram":
            ig_acct = IG_ACCOUNT_ID
            if not ig_acct:
                try:
                    info = mp._get_page_info(fb_token, FB_PAGE_ID)
                    ig_acct = (info.get("instagram_business_account") or {}).get("id")
                except Exception:
                    ig_acct = None
            if not ig_acct:
                return "Instagram Business Account unavailable: IG_ACCOUNT_ID not configured and Page lookup failed."
            try:
                _ = mp._get_instagram_info(fb_token, ig_acct)
            except Exception as e:
                return f"Meta Instagram access unavailable for ig_account_id {ig_acct}: {e}"
            return None
        return None

    blocked_meta_reason: dict[str, str] = {}
    if not dry_run:
        for _p in platforms:
            _plat = _p["platform"]
            if _plat in ("facebook", "instagram") and _plat not in blocked_meta_reason:
                _err = _meta_preflight_error_for_platform(_plat)
                if _err:
                    blocked_meta_reason[_plat] = _err

    for cfg in platforms:
        platform = cfg["platform"]
        account = cfg["account"]
        kind = cfg["kind"]
        title = cfg["title"]
        description = cfg["description"]
        video_path = resolve_video_path(cfg["video_path"], project_dir, root)
        publish_at = cfg["publish_at"]

        if force and store and not dry_run:
            from scripts.clear_uniqueness import clear_uniqueness
            clear_uniqueness(store, metadata["id"])
            key = publish_key(today, metadata["id"], platform, kind)
            store.session.delete(store._url(key), timeout=30)

        # Step 1: Claim in Firebase before upload
        if dry_run:
            key = publish_key(today, metadata["id"], platform, kind)
            exists = video_path.exists()
            print(
                f"[DRY RUN] {platform}/{kind}: would upload "
                f"{video_path} ({'found' if exists else 'MISSING'})"
            )
            results["platforms"][f"{platform}/{kind}"] = {
                "status": "dry_run",
                "video_path": str(video_path),
                "video_exists": exists,
            }
            if not exists:
                results["errors"].append(f"{platform}/{kind} video not found: {video_path}")
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

        if not claimed:
            existing_status = existing.get("status") if existing else "unknown"
            if retry_failed and existing_status == "failed":
                if existing.get("video_id") or existing.get("platform_id"):
                    print(
                        f"[RETRY CHECK] Existing record {key} already has remote ID; "
                        f"skipping duplicate upload"
                    )
                    results["platforms"][f"{platform}/{kind}"] = {
                        "status": "skipped",
                        "reason": "existing_remote_id",
                        "existing_record": existing,
                    }
                    continue
                key = publish_key(today, metadata["id"], platform, kind)
                store.update(
                    key,
                    {
                        "status": "uploading",
                        "error": None,
                        "retry_started_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            elif existing_status == "scheduling" and not (existing.get("video_id") or existing.get("platform_id")):
                print(
                    f"[RESERVATION RESUME] Found queued reservation for {key} without remote ID; "
                    f"resuming upload."
                )
                key = publish_key(today, metadata["id"], platform, kind)
                store.update(
                    key,
                    {
                        "status": "uploading",
                        "error": None,
                        "worker_started_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            else:
                results["platforms"][f"{platform}/{kind}"] = {
                    "status": "skipped",
                    "reason": "duplicate",
                    "existing_record": existing,
                }
                continue

        # Step 2: Upload to platform
        result = None
        if platform == "youtube":
            publisher = YoutubePublisher()
            try:
                inputs = build_youtube_payload(metadata, video_path=str(video_path), publish_at=publish_at)
            except ValueError as exc:
                inputs = None
                result = {"success": False, "error": f"metadata invalid: {exc}"}

            if inputs is None:
                pass
            elif dry_run:
                print(f"[DRY RUN] Would upload YouTube {kind}: {video_path}")
                result = {"success": True, "video_id": "DRY_RUN_ID", "video_url": "https://example.com/dry-run"}
            else:
                tool_result = publisher.execute(inputs)
                result = {
                    "success": tool_result.success,
                    "video_id": tool_result.data.get("video_id") if tool_result.success else None,
                    "video_url": tool_result.data.get("video_url") if tool_result.success else None,
                    "error": tool_result.error if not tool_result.success else None,
                }

        elif platform in ("instagram", "facebook"):
            if platform in blocked_meta_reason and not dry_run:
                # Don't burn an API call that we already know will 400; record visible failure.
                result = {"success": False, "error": blocked_meta_reason[platform]}
            elif dry_run:
                print(f"[DRY RUN] Would upload {platform} {kind}: {video_path}")
                result = {
                    "success": True,
                    "platform_id": f"DRY_RUN_{platform.upper()}_ID",
                    "video_url": f"https://facebook.com/{account}/videos/dry-run",
                }
            else:
                publisher = MetaPublisher()
                # Instagram uses R2 upload + Graph API media container; Facebook uses direct page video upload
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
                    # Native Graph scheduling so the post goes live at the queued VN slot.
                    inputs["scheduled_publish_time"] = int(cfg["scheduled_epoch"])
                tool_result = publisher.execute(inputs)
                data = tool_result.data or {}
                platform_id = (
                    data.get("facebook_post_id") if platform == "facebook" else data.get("instagram_media_id")
                )
                result = {
                    "success": tool_result.success and bool(platform_id),
                    "platform_id": platform_id,
                    "video_url": (
                        f"https://facebook.com/{account}/videos/{platform_id}"
                        if platform == "facebook" and platform_id
                        else None
                    ),
                    "error": (
                        None
                        if tool_result.success and platform_id
                        else tool_result.error or f"Meta returned no {platform} media ID"
                    ),
                }

        else:
            results["errors"].append(f"Unsupported platform: {platform}")
            result = {"success": False, "error": f"Unsupported platform: {platform}"}

        # Step 3: Update Firebase based on result
        if result and result.get("success"):
            vid_id = result.get("video_id") or result.get("platform_id")
            vid_url = result.get("video_url")
            # F08: Instagram is uploaded directly and published immediately at its slot.
            # Only YouTube with publish_at or Facebook with scheduled_epoch are remotely scheduled.
            if platform == "instagram":
                is_scheduled = False
            elif platform == "facebook" and cfg.get("scheduled_epoch"):
                is_scheduled = True
            elif platform == "youtube" and publish_at:
                is_scheduled = True
            else:
                is_scheduled = False
            record_status = "scheduled" if is_scheduled else "published"
            if store:
                try:
                    if is_scheduled:
                        sched_target = publish_at or (
                            datetime.fromtimestamp(cfg["scheduled_epoch"], tz=timezone.utc).isoformat().replace("+00:00", "Z")
                            if cfg.get("scheduled_epoch")
                            else datetime.now(timezone.utc).isoformat()
                        )
                        store.mark_scheduled(
                            key,
                            video_id=vid_id,
                            video_url=vid_url,
                            scheduled_for=sched_target,
                        )
                        print(f"✅ Firebase record updated: {key} -> scheduled")
                    else:
                        store.mark_published(
                            key,
                            video_id=vid_id,
                            video_url=vid_url,
                            published_at=datetime.now(timezone.utc).isoformat(),
                        )
                        print(f"✅ Firebase record updated: {key} -> published")
                except Exception as fb_error:
                    print(f"❌ Firebase update failed for {key}: {fb_error}")
                    # Continue anyway since the platform upload succeeded
                
            results["platforms"][f"{platform}/{kind}"] = {
                "status": record_status,
                "video_id": vid_id,
                "video_url": vid_url,
            }
        else:
            error_msg = result.get("error", "Unknown upload error") if result else "No result returned"
            try:
                store.mark_failed(key, error_msg)
            except Exception as fb_error:
                print(f"❌ Firebase mark_failed failed for {key}: {fb_error}")
                
            results["platforms"][f"{platform}/{kind}"] = {
                "status": "failed",
                "error": error_msg,
            }
            results["errors"].append(f"{platform}/{kind} upload failed: {error_msg}")

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
    command = [
        sys.executable,
        str(validate_script),
        str(project_path),
        "--ffprobe",
        ffprobe,
        "--ffmpeg",
        ffmpeg,
        "--reels-max-duration",
        "60",
    ]
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

    if pipeline_type:
        from lib.checkpoint import (
            get_pipeline_stages,
            _stage_requires_approval,
            validate_checkpoint,
            CANONICAL_STAGE_ARTIFACTS,
        )
        from lib.pipeline_loader import load_pipeline_readonly
        from lib.news_release_gate import is_news_project

        is_news = is_news_project(project_dir, metadata)

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
            or (project_dir / "approval.json").is_file()
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

        # Build list of media files to check
        media_to_check: list[tuple[str, Path]] = []
        if platforms:
            for p in platforms:
                vp = resolve_video_path(p["video_path"], project_dir, root)
                media_to_check.append((p["platform"], vp))
        else:
            for k in ("yt_shorts", "ig_reels", "fb_video", "fb_reels"):
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
                acct = p["account"]
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
    args = parser.parse_args()

    project_path = Path(args.project_dir)
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
        # Skip release preflight if only targeted platform is held
        if not (only_platform and is_platform_held(only_platform, extra_held=cli_held)):
            enforce_release_preflight(project_path, metadata, strict=True, force=args.force)
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
        store, date=today, topic=metadata["id"], project_dir=project_path, held_platforms=cli_held
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
