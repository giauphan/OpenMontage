"""Platform-specific video upload dispatchers and remote verification for OpenMontage.

Dispatches uploads to:
- YouTube (Shorts & Longform) via YoutubePublisher
- Meta (Facebook Page / Instagram Reels) via MetaPublisher & FacebookPublisher
- TikTok via TiktokPublisher
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_store import PublishStore
from scripts.publish_config import canonical_platform_name, is_platform_enabled, is_platform_held
from tools.publishers.platform_routes import compose_release_metadata, PLATFORM_ROUTES, youtube_shorts_title
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.tiktok_publisher import TiktokPublisher
from tools.publishers.social_metadata import meta_caption


THUMBNAIL_PNG = "thumbnail.png"
THUMBNAIL_JPG = "thumbnail.jpg"


def _facade_symbol(name: str, fallback: Any) -> Any:
    mod = sys.modules.get("scripts.publish_manual_video")
    return getattr(mod, name, fallback) if mod is not None else fallback


def _find_candidate_thumbnail(video_path: Path) -> Path | None:
    search_dirs = [
        video_path.parent.parent / "artifacts",
        video_path.parent / "artifacts",
        video_path.parent.parent / "thumbnails",
        video_path.parent,
        video_path.parent / "thumbnails",
    ]
    for d in search_dirs:
        for fname in (THUMBNAIL_PNG, THUMBNAIL_JPG):
            candidate = d / fname
            if candidate.is_file():
                return candidate
    return None


def _generate_fallback_thumbnail(video_path: Path, payload_meta: dict) -> str | None:
    try:
        from lib.news_visual.thumbnail_orchestrator import ThumbnailOrchestrator

        pdir = video_path.parent.parent if video_path.parent.name == "renders" else video_path.parent
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
                return res.thumbnail_path
    except Exception:
        pass
    return None


def _resolve_youtube_thumbnail(
    video_path: str,
    thumbnail_path: str | None,
    payload_meta: dict,
) -> str | None:
    thumb = thumbnail_path or payload_meta.get("thumbnail_path") or payload_meta.get("thumbnail")
    v_p = Path(video_path)
    if not thumb or not Path(thumb).is_file():
        candidate = _find_candidate_thumbnail(v_p)
        if candidate is not None:
            thumb = str(candidate)

    if not thumb or not Path(thumb).is_file() or Path(thumb).stat().st_size < 50_000:
        fallback = _generate_fallback_thumbnail(v_p, payload_meta)
        if fallback:
            thumb = fallback

    return str(thumb) if (thumb and Path(thumb).is_file()) else None


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

    thumb = _resolve_youtube_thumbnail(video_path, thumbnail_path, payload_meta)
    if thumb:
        payload["thumbnail_path"] = thumb

    return payload


def _clear_uniqueness_for_topic(store: PublishStore, topic: str) -> int:
    """Delete all uniqueness documents for a topic so claim() can succeed on re-publish."""
    from scripts.clear_uniqueness import clear_uniqueness

    _, cleared = clear_uniqueness(store, topic)
    return cleared


def _facebook_preflight_error() -> str | None:
    try:
        from tools.publishers.facebook_publisher import FacebookPublisher

        fb_pub = FacebookPublisher()
        readiness = fb_pub.check_readiness()
        if readiness.get("status") in ("enabled", "ok") or readiness.get("configured") is True:
            return None
    except Exception:
        pass
    meta_pub_cls = _facade_symbol("MetaPublisher", MetaPublisher)
    mp = meta_pub_cls()
    fb_token = os.environ.get("TOKEN_FACEBOOK", "")
    page_id = _facade_symbol("FB_PAGE_ID", "")
    if fb_token:
        try:
            _ = mp._get_page_info(fb_token, page_id)
            return None
        except Exception as e:
            return f"Meta Facebook Page access unavailable for {page_id}: {e}"
    gw_url = os.environ.get("FACEBOOK_GATEWAY_BASE_URL", "http://127.0.0.1:20129/custom/facebook")
    return (
        f"Facebook publishing unavailable: Toolcase Gateway not reachable at {gw_url} "
        "(port 20129) and TOKEN_FACEBOOK is not configured."
    )


def _resolve_instagram_account_id(mp: Any, fb_token: str) -> str | None:
    ig_acct = _facade_symbol("IG_ACCOUNT_ID", None)
    if ig_acct:
        return ig_acct
    try:
        page_id = _facade_symbol("FB_PAGE_ID", "")
        info = mp._get_page_info(fb_token, page_id)
        return (info.get("instagram_business_account") or {}).get("id")
    except Exception:
        return None


def _instagram_preflight_error() -> str | None:
    meta_pub_cls = _facade_symbol("MetaPublisher", MetaPublisher)
    mp = meta_pub_cls()
    fb_token = os.environ.get("TOKEN_FACEBOOK", "")
    resolve_ig_fn = _facade_symbol("_resolve_instagram_account_id", _resolve_instagram_account_id)
    ig_acct = resolve_ig_fn(mp, fb_token)
    if not ig_acct:
        return "Instagram Business Account unavailable: IG_ACCOUNT_ID not configured and Page lookup failed."
    try:
        _ = mp._get_instagram_info(fb_token, ig_acct)
        return None
    except Exception as e:
        return f"Meta Instagram access unavailable for ig_account_id {ig_acct}: {e}"


def _meta_preflight_error_for_platform(platform: str) -> str | None:
    if platform == "facebook":
        fb_err_fn = _facade_symbol("_facebook_preflight_error", _facebook_preflight_error)
        return fb_err_fn()
    if platform == "instagram":
        ig_err_fn = _facade_symbol("_instagram_preflight_error", _instagram_preflight_error)
        return ig_err_fn()
    return None


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


def _upload_youtube(
    metadata: dict,
    video_path: Path,
    publish_at: str | None,
    kind: str,
    dry_run: bool,
) -> tuple[dict, Any]:
    yt_pub_cls = _facade_symbol("YoutubePublisher", YoutubePublisher)
    publisher = yt_pub_cls()
    payload_fn = _facade_symbol("build_youtube_payload", build_youtube_payload)
    try:
        inputs = payload_fn(metadata, video_path=str(video_path), publish_at=publish_at)
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


def _execute_facebook_upload(
    video_path: Path,
    title: str,
    description: str,
    cfg: dict,
    inputs: dict,
    publisher: Any,
) -> Any:
    page_id = _facade_symbol("FB_PAGE_ID", "")
    try:
        from tools.publishers.facebook_publisher import FacebookPublisher

        fb_pub = FacebookPublisher()
        fb_inputs = {
            "video_path": str(video_path),
            "title": title,
            "caption": meta_caption(title, description),
            "target_id": page_id,
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
    meta_pub_cls = _facade_symbol("MetaPublisher", MetaPublisher)
    publisher = meta_pub_cls()
    if platform in blocked_meta_reason and not dry_run:
        return {"success": False, "error": blocked_meta_reason[platform]}, publisher
    if dry_run:
        print(f"[DRY RUN] Would upload {platform} {kind}: {video_path}")
        return {
            "success": True,
            "platform_id": f"DRY_RUN_{platform.upper()}_ID",
            "video_url": f"https://facebook.com/{account}/videos/dry-run",
        }, publisher

    page_id = _facade_symbol("FB_PAGE_ID", "")
    ig_account_id = _facade_symbol("IG_ACCOUNT_ID", "")
    inputs = {
        "video_path": video_path,
        "title": title,
        "caption": meta_caption(title, description),
        "page_id": page_id,
        "instagram_account_id": ig_account_id,
        "post_to_facebook": platform == "facebook",
        "post_to_instagram": platform == "instagram",
    }
    if cfg.get("scheduled_epoch") and platform == "facebook":
        inputs["scheduled_publish_time"] = int(cfg["scheduled_epoch"])

    if platform == "facebook":
        exec_fb_fn = _facade_symbol("_execute_facebook_upload", _execute_facebook_upload)
        tool_result = exec_fb_fn(video_path, title, description, cfg, inputs, publisher)
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


def _upload_tiktok(
    platform: str,
    kind: str,
    title: str,
    description: str,
    video_path: Path,
    cfg: dict,
    dry_run: bool,
) -> tuple[dict, Any]:
    tiktok_pub_cls = _facade_symbol("TiktokPublisher", TiktokPublisher)
    publisher = tiktok_pub_cls()
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
        upload_yt_fn = _facade_symbol("_upload_youtube", _upload_youtube)
        return upload_yt_fn(metadata, video_path, publish_at, kind, dry_run)
    if platform in ("instagram", "facebook"):
        upload_meta_fn = _facade_symbol("_upload_meta", _upload_meta)
        return upload_meta_fn(platform, account, kind, title, description, video_path, cfg, dry_run, blocked_meta_reason)
    if platform == "tiktok":
        upload_tt_fn = _facade_symbol("_upload_tiktok", _upload_tiktok)
        return upload_tt_fn(platform, kind, title, description, video_path, cfg, dry_run)
    err = f"Unsupported platform: {platform}"
    results["errors"].append(err)
    return {"success": False, "error": err}, None


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
    fb_page_id = _facade_symbol("FB_PAGE_ID", "")
    ig_acct_id = _facade_symbol("IG_ACCOUNT_ID", "")
    yt_account = _facade_symbol("YT_ACCOUNT", "")
    accounts = {"instagram": ig_acct_id, "facebook": fb_page_id, "youtube": yt_account}
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
    fb_page_id = _facade_symbol("FB_PAGE_ID", "")
    ig_acct_id = _facade_symbol("IG_ACCOUNT_ID", "")
    yt_account = _facade_symbol("YT_ACCOUNT", "")
    contract_candidates: list[tuple[str, str, str, str]] = []
    if "youtube" in cfg_enabled:
        contract_candidates.append(("youtube", yt_account, yt_kind, yt_field))
    if "instagram" in cfg_enabled:
        contract_candidates.append(("instagram", ig_acct_id, PLATFORM_ROUTES["instagram"][0], PLATFORM_ROUTES["instagram"][1]))
    if "facebook" in cfg_enabled:
        contract_candidates.append(("facebook", fb_page_id, PLATFORM_ROUTES["facebook"][0], PLATFORM_ROUTES["facebook"][1]))
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
    fb_page_id = _facade_symbol("FB_PAGE_ID", "")
    ig_acct_id = _facade_symbol("IG_ACCOUNT_ID", "")
    yt_account = _facade_symbol("YT_ACCOUNT", "")
    platforms = [("youtube", yt_account), ("instagram", ig_acct_id)]
    if fb_on:
        platforms.append(("facebook", fb_page_id))
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
        resolve_single_fn = _facade_symbol("_resolve_single_platform_contract", _resolve_single_platform_contract)
        return resolve_single_fn(
            only_platform, enabled_platforms, held_platforms, yt_kind, yt_field, results
        )

    ig_acct_id = _facade_symbol("IG_ACCOUNT_ID", "")
    yt_account = _facade_symbol("YT_ACCOUNT", "")
    if instagram_mode:
        print("📸 INSTAGRAM MODE: Instagram only (Instagram cron job)")
        contract = [("instagram", ig_acct_id, PLATFORM_ROUTES["instagram"][0], PLATFORM_ROUTES["instagram"][1])]
    elif cfg_enabled is not None:
        resolve_cfg_fn = _facade_symbol("_resolve_cfg_enabled_candidates", _resolve_cfg_enabled_candidates)
        contract = resolve_cfg_fn(cfg_enabled, yt_kind, yt_field)
    elif multi_platform:
        resolve_multi_fn = _facade_symbol("_resolve_multi_platform_candidates", _resolve_multi_platform_candidates)
        contract = resolve_multi_fn()
    else:
        print("🎯 SINGLE-PLATFORM MODE: YouTube only (set MULTI_PLATFORM=1 for multi-platform)")
        contract = [("youtube", yt_account, yt_kind, yt_field)]

    filter_fn = _facade_symbol("_filter_active_platforms", _filter_active_platforms)
    return filter_fn(contract, enabled_platforms, held_platforms, results)


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
    meta_err_fn = _facade_symbol("_meta_preflight_error_for_platform", _meta_preflight_error_for_platform)
    blocked: dict[str, str] = {}
    for p in platforms:
        plat = p["platform"]
        if plat in ("facebook", "instagram") and plat not in blocked:
            err = meta_err_fn(plat)
            if err:
                blocked[plat] = err
    return blocked


__all__ = [
    "build_youtube_payload",
    "_clear_uniqueness_for_topic",
    "_facebook_preflight_error",
    "_resolve_instagram_account_id",
    "_instagram_preflight_error",
    "_meta_preflight_error_for_platform",
    "_normalize_facebook_format",
    "_normalize_youtube_format",
    "_resolve_vertical_tiktok_candidate",
    "_normalize_tiktok_format",
    "_normalize_metadata_formats",
    "_upload_youtube",
    "_extract_meta_platform_id",
    "_extract_meta_video_url",
    "_upload_meta",
    "_execute_facebook_upload",
    "_build_tiktok_result",
    "_upload_tiktok",
    "_check_youtube_remote_status",
    "_check_meta_remote_status",
    "_check_tiktok_remote_status",
    "_check_remote_published_status",
    "_dispatch_platform_upload",
    "_resolve_single_platform_contract",
    "_resolve_cfg_enabled_candidates",
    "_resolve_multi_platform_candidates",
    "_filter_active_platforms",
    "_resolve_platform_contract",
    "_build_platform_configs",
    "_collect_blocked_meta_reasons",
]
