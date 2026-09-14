"""Firebase-guarded manual publisher for generated video topics.

Publishes one generated topic to YouTube Long + YouTube Short + Instagram Reels + Facebook Page video.
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

from scripts.publish_config import load_config, publish_timezone
from tools.publish_store import PublishStore, publish_key
from scripts.validate_render_quality import PORTRAIT_DIMENSIONS, resolve_narration, validate_video
from tools.publishers.platform_routes import (
    PLATFORM_ROUTES,
    ensure_youtube_short,
    youtube_shorts_title,
    probe_dimensions,
    VERTICAL_WIDTH,
    VERTICAL_HEIGHT,
)
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.social_metadata import meta_caption

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
    errors = validate_video(
        video_path,
        narration,
        ffprobe,
        ffmpeg,
        30.0,
        3.0,
        PORTRAIT_DIMENSIONS,
        60.0 if platform in ("youtube", "instagram") else None,
        narration_text if narration_text.is_file() else None,
        strict=strict,
    )
    if errors:
        raise ValueError("\n".join(errors))


def canonical_platform_records_published(store: PublishStore, *, date: str, topic: str) -> bool:
    routes = (("youtube", "short"), ("instagram", "reels"))
    try:
        return all(
            (record := store.get(publish_key(date, topic, platform, kind)))
            and record.get("status") == "published"
            for platform, kind in routes
        )
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
) -> dict:
    """Publish one topic to configured platforms with Firebase guards."""
    results = {"platforms": {}, "errors": [], "batch_started_at": datetime.now(timezone.utc).isoformat()}
    root = Path(__file__).resolve().parents[1]

    # Metadata contract: the shared route table owns platform -> field/kind mapping.
    platform_contract = [
        (platform, account, PLATFORM_ROUTES[platform][0], PLATFORM_ROUTES[platform][1])
        for platform, account in (
            ("youtube", YT_ACCOUNT),
            ("instagram", IG_ACCOUNT_ID),
            ("facebook", FB_PAGE_ID),
        )
    ]
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

    # Validate exact selected assets before any Firebase claim or mutation.
    for cfg in platforms:
        video_path = resolve_video_path(cfg["video_path"], project_dir, root)
        validate_publish_asset(video_path, project_dir, cfg["platform"], strict=True)

    today = date if date else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fail-closed Meta preflight: never attempt IG/FB with a transparently-doomed token.
    # IMPORTANT: this must never block YouTube. Gate each platform independently and fail
    # the blocked ones as "failed" (visible failure), while YouTube still runs.
    def _meta_preflight_error_for_platform(platform: str) -> str | None:
        from tools.publishers.meta_publisher import MetaPublisher as _MetaPub

        mp = _MetaPub()
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
            inputs = {
                "video_path": str(video_path),
                "title": title,
                "description": description,
                "tags": ["tintuc", "congnghe", "ai", "tuonglai", "vietnam"],
                "privacy_status": "private" if publish_at else "unlisted",
                "publish_at": publish_at,
            }
            if dry_run:
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
            try:
                store.mark_published(
                    key,
                    video_id=result.get("video_id") or result.get("platform_id"),
                    video_url=result.get("video_url"),
                    published_at=datetime.now(timezone.utc).isoformat(),
                )
                print(f"✅ Firebase record updated: {key} -> published")
            except Exception as fb_error:
                print(f"❌ Firebase update failed for {key}: {fb_error}")
                # Continue anyway since the platform upload succeeded
                
            results["platforms"][f"{platform}/{kind}"] = {
                "status": "published",
                "video_id": result.get("video_id") or result.get("platform_id"),
                "video_url": result.get("video_url"),
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

    # Step 2: CLAUDE Agent Strict Quality Validation (mandatory when strict=True)
    if strict:
        claude_validator = root / "scripts" / "claude_agent_validation.py"
        if not claude_validator.is_file():
            raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: CLAUDE agent validator required")

        env = dict(os.environ)
        ffprobe = shutil.which("ffprobe") or ""
        if not ffprobe:
            candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
            if candidates:
                env["PATH"] = str(candidates[0].parent) + ":" + env.get("PATH", "")

        claude_result = subprocess.run(
            [sys.executable, str(claude_validator), str(project_path), "--strict"],
            capture_output=True,
            text=True,
            env=env,
        )
        if claude_result.returncode:
            diagnostic = "\n".join(part.strip() for part in (claude_result.stdout, claude_result.stderr) if part.strip())
            raise RuntimeError(f"CLAUDE Agent strict validation failed: {diagnostic or f'validator exited {claude_result.returncode}'}")

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


def main():
    parser = argparse.ArgumentParser(description="Firebase-guarded manual publisher for generated videos")
    parser.add_argument("project_dir", help="Path to generated project directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only records marked failed")
    parser.add_argument("--date", type=str, default=None, help="Force date for this run")
    parser.add_argument("--force", action="store_true", help="Force re-publish even if already uploaded/published")
    parser.add_argument("--only-platform", choices=["instagram", "facebook", "youtube"], help="Limit publishing to one platform")
    parser.add_argument("--last-publish", type=str, default=None, help="Last publish timestamp (ISO8601) for gap enforcement")
    args = parser.parse_args()

    project_path = Path(args.project_dir)
    if not project_path.exists():
        print(f"Error: Project directory not found: {project_path}")
        sys.exit(1)

    # Load metadata
    try:
        metadata = load_metadata(project_path)
    except Exception as e:
        print(f"Error loading metadata: {e}")
        sys.exit(1)

    try:
        validate_project_quality(project_path, strict=True)
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
        only_platform=args.only_platform,
        force=args.force,
        date=args.date,
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
        elif status_str == "skipped":
            reason = status.get("reason", "unknown")
            print(f"⏭️  {platform_kind}: SKIPPED ({reason})")
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
    if canonical_platform_records_published(store, date=today, topic=metadata["id"]):
        published_now = sum(1 for s in results["platforms"].values() if s.get("status") in ("published", "skipped"))
        print(f"\n✅ All {total_platforms} canonical Firebase platform records verified ({published_now} uploaded now)")
        if not args.dry_run:
            from scripts.publish_active_projects import deactivate_project
            if not deactivate_project(metadata["id"], store=store, date=today):
                print("\n❌ Cleanup blocked: canonical Firebase publish records are incomplete; project retained")
                return 1
        return 0

    published_count = sum(1 for s in results["platforms"].values() if s.get("status") in ("published", "skipped"))
    print(f"\n❌ Incomplete batch: {published_count}/{total_platforms} uploads and Firebase records not all published; project retained")
    return 1


if __name__ == "__main__":
    sys.exit(main())
