"""Firebase-guarded manual publisher for generated video topics.

DEFAULT: Publishes to YouTube only (single-platform to prevent duplicates).
Multi-platform mode (YouTube + Instagram + Facebook) can be enabled via MULTI_PLATFORM=1.
Enforces Firebase duplicate protection and a two-hour gap between batches.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

# Re-exports from publish_manual_quality
from scripts.publish_manual_quality import (
    safe_resolve_publish_path,
    load_metadata,
    resolve_video_path,
    validate_publish_asset,
    validate_project_quality,
    enforce_release_preflight,
)

# Re-exports from publish_manual_dispatch
from scripts.publish_manual_dispatch import (
    build_youtube_payload,
    _clear_uniqueness_for_topic,
    _facebook_preflight_error,
    _resolve_instagram_account_id,
    _instagram_preflight_error,
    _meta_preflight_error_for_platform,
    _normalize_facebook_format,
    _normalize_youtube_format,
    _resolve_vertical_tiktok_candidate,
    _normalize_tiktok_format,
    _normalize_metadata_formats,
    _upload_youtube,
    _extract_meta_platform_id,
    _extract_meta_video_url,
    _upload_meta,
    _execute_facebook_upload,
    _build_tiktok_result,
    _upload_tiktok,
    _check_youtube_remote_status,
    _check_meta_remote_status,
    _check_tiktok_remote_status,
    _check_remote_published_status,
    _dispatch_platform_upload,
    _resolve_single_platform_contract,
    _resolve_cfg_enabled_candidates,
    _resolve_multi_platform_candidates,
    _filter_active_platforms,
    _resolve_platform_contract,
    _build_platform_configs,
    _collect_blocked_meta_reasons,
)

_CFG = load_config()
FB_PAGE_ID = _CFG["meta"]["page_id"]
IG_ACCOUNT_ID = _CFG["meta"]["ig_account_id"]
YT_ACCOUNT = _CFG["youtube"]["account"]
PUBLISH_TZ = _CFG.get("timezone", "Asia/Ho_Chi_Minh")
UTC_OFFSET = "+00:00"


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
        raise ValueError("publish_time missing from metadata; cannot derive scheduled publish time")

    hh, mm = publish_time.split(":", 1)
    tz = publish_timezone(cfg)
    local_dt = datetime.fromisoformat(f"{publish_date}T{int(hh):02d}:{int(mm):02d}:00").replace(tzinfo=tz)
    scheduled_epoch = int(local_dt.astimezone(timezone.utc).timestamp())
    publish_at_iso = local_dt.astimezone(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
    return datetime.fromisoformat(publish_at_iso.replace("Z", UTC_OFFSET)).replace(tzinfo=timezone.utc), scheduled_epoch


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
