"""Firebase-guarded manual publisher for generated video topics.

Publishes one generated topic to YouTube Long + YouTube Short + Instagram Reels + Facebook Page video.
Enforces Firebase duplicate protection and a two-hour gap between batches.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from publish_config import load_config
from tools.publish_store import PublishStore, publish_key
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher

_CFG = load_config()
FB_PAGE_ID = _CFG["meta"]["page_id"]
IG_ACCOUNT_ID = _CFG["meta"]["ig_account_id"]
YT_ACCOUNT = _CFG["youtube"]["account"]


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


def publish_batch(
    metadata: dict,
    project_dir: Path,
    store: PublishStore | None,
    dry_run: bool = False,
    retry_failed: bool = False,
    only_platform: str | None = None,
) -> dict:
    """Publish one topic to configured platforms with Firebase guards."""
    results = {"platforms": {}, "errors": [], "batch_started_at": datetime.now(timezone.utc).isoformat()}
    root = Path(__file__).resolve().parents[1]

    # Metadata contract: each platform maps to one explicit video field and kind.
    platform_contract = [
        ("youtube", YT_ACCOUNT, "short", "yt_shorts"),
        ("instagram", IG_ACCOUNT_ID, "reels", "ig_reels"),
        ("facebook", FB_PAGE_ID, "page_video", "fb_video"),
    ]
    if "fb_video" not in metadata and "fb_reels" in metadata:
        metadata = {**metadata, "fb_video": metadata["fb_reels"]}
    missing = [field for _, _, _, field in platform_contract if field not in metadata]
    if missing:
        raise KeyError(f"publish_metadata.json missing platform video fields: {', '.join(missing)}")
    platforms = [
        {
            "platform": platform,
            "account": account,
            "kind": kind,
            "title": metadata["title"],
            "description": metadata["description"],
            "video_path": metadata[field],
            "publish_at": None,
        }
        for platform, account, kind, field in platform_contract
    ]
    if only_platform:
        platforms = [cfg for cfg in platforms if cfg["platform"] == only_platform]
    if not platforms:
        raise ValueError(f"No platform configured for {only_platform}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for cfg in platforms:
        platform = cfg["platform"]
        account = cfg["account"]
        kind = cfg["kind"]
        title = cfg["title"]
        description = cfg["description"]
        video_path = resolve_video_path(cfg["video_path"], project_dir, root)
        publish_at = cfg["publish_at"]

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
            source_topic=metadata["topic"],
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
                "tags": ["AI", "Công nghệ", "Vietnamese", "OpenMontage"],
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
            publisher = MetaPublisher()
            # Instagram uses R2 upload + Graph API media container; Facebook uses direct page video upload
            inputs = {
                "video_path": video_path,
                "title": title,
                "caption": description,
                "page_id": FB_PAGE_ID,
                "post_to_facebook": platform == "facebook",
                "post_to_instagram": platform == "instagram",
            }
            if dry_run:
                print(f"[DRY RUN] Would upload {platform} {kind}: {video_path}")
                result = {
                    "success": True,
                    "platform_id": f"DRY_RUN_{platform.upper()}_ID",
                    "video_url": f"https://facebook.com/{account}/videos/dry-run",
                }
            else:
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
            store.mark_published(
                key,
                video_id=result.get("video_id") or result.get("platform_id"),
                video_url=result.get("video_url"),
                published_at=datetime.now(timezone.utc).isoformat(),
            )
            results["platforms"][f"{platform}/{kind}"] = {
                "status": "published",
                "video_id": result.get("video_id") or result.get("platform_id"),
                "video_url": result.get("video_url"),
            }
        else:
            error_msg = result.get("error", "Unknown upload error") if result else "No result returned"
            store.mark_failed(key, error_msg)
            results["platforms"][f"{platform}/{kind}"] = {
                "status": "failed",
                "error": error_msg,
            }
            results["errors"].append(f"{platform}/{kind} upload failed: {error_msg}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Firebase-guarded manual publisher for generated videos")
    parser.add_argument("project_dir", help="Path to generated project directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only records marked failed")
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

    # Return success if at least one platform published.
    published_count = sum(1 for s in results["platforms"].values() if s.get("status") == "published")
    if published_count > 0:
        print(f"\n✅ Batch completed with {published_count} successful uploads")
        return 0
    print("\n❌ Batch failed: no platforms published")
    return 1


if __name__ == "__main__":
    sys.exit(main())
