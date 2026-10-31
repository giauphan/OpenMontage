"""Facebook scheduled publishing step for the native, approval-validated scheduling path.

Uses Toolcase Gateway Meta Business Suite adapter with native scheduled_publish_time
and automated 14-language AI dubbing per SCHEDULING_AND_AUTO_TRANSLATE_GUIDE.md.
The caller must already have passed the validation, news-evidence,
provenance and cryptographic approval gates for the exact asset passed in.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.publish_store import publish_key

FACEBOOK_KIND = "reels"


def publish_facebook_native(
    store: Any,
    *,
    date: str,
    topic_id: str,
    asset_path: Path,
    title: str,
    description: str,
    scheduled_for: str,
    content_hash: str | None,
    template_id: str | None,
    dry_run: bool,
    publisher_factory: Callable[[], Any] | None = None,
    target_id: str | None = None,
) -> bool:
    """Publish or schedule one approved asset to Facebook Reels. Returns True when it FAILED."""
    key = publish_key(date, topic_id, "facebook", FACEBOOK_KIND)
    if not asset_path.is_file():
        print(f"failed {topic_id}: missing Facebook asset file {asset_path}")
        return True

    schedule_epoch: int | None = None
    if scheduled_for:
        try:
            schedule_epoch = int(datetime.fromisoformat(scheduled_for).timestamp())
        except Exception:
            pass

    if dry_run:
        sched_info = f" scheduled for {scheduled_for} (epoch={schedule_epoch}, auto_translate=14_langs)" if schedule_epoch else ""
        print(f"SHADOW/DRY-RUN: Simulated Facebook Reels publish{sched_info} for {topic_id} ({asset_path.name}); no store mutations, no upload")
        return False

    existing = store.get(key) if hasattr(store, "get") else None
    if existing and existing.get("status") in ("scheduled", "published"):
        print(f"ALREADY PUBLISHED {topic_id} on facebook ({existing.get('video_url', '')})")
        return False

    claimed = False
    if existing and existing.get("status") == "failed":
        claimed = True
        if hasattr(store, "update"):
            store.update(key, {"status": "scheduling", "error": None})
    else:
        key, claimed, _ = store.claim(
            date=date,
            topic=topic_id,
            platform="facebook",
            account=target_id or "facebook_page",
            kind=FACEBOOK_KIND,
            status="scheduling",
            title=title,
            asset_path=asset_path,
            scheduled_for=scheduled_for,
            content_hash=content_hash,
            template_id=template_id,
        )
    if not claimed:
        print(f"SKIP: Facebook {date} {topic_id} (already claimed)")
        return False

    if publisher_factory is None:
        from tools.publishers.facebook_publisher import FacebookPublisher as publisher_factory
    caption = f"{title}\n\n{description}".strip() if description else title

    inputs: dict[str, Any] = {
        "video_path": str(asset_path),
        "caption": caption,
        "title": title,
        "enable_auto_translate": True,
    }
    if target_id:
        inputs["target_id"] = target_id
    if schedule_epoch:
        inputs["scheduled_publish_time"] = schedule_epoch

    try:
        result = publisher_factory().execute(inputs)
    except Exception as exc:
        store.mark_failed(key, str(exc))
        print(f"Facebook error {topic_id}: {exc}")
        return True

    data = result.data or {}
    remote_id = data.get("facebook_post_id") or data.get("video_id")
    if not result.success or not remote_id:
        err = result.error or "Facebook returned no post or video id"
        store.mark_failed(key, err)
        print(f"Facebook failed {topic_id}: {err}")
        return True

    is_scheduled = data.get("status") == "scheduled" or bool(schedule_epoch)
    video_url = data.get("video_url") or (f"https://facebook.com/{remote_id}" if remote_id else None)
    if is_scheduled:
        store.mark_scheduled(
            key,
            video_id=remote_id,
            video_url=video_url,
            scheduled_for=scheduled_for,
        )
        print(f"Facebook scheduled {topic_id} ({remote_id}) for {scheduled_for} (auto-translate enabled)")
    else:
        store.mark_published(
            key,
            video_id=remote_id,
            video_url=video_url,
            platform_id=remote_id,
        )
        print(f"Facebook published {topic_id} ({remote_id})")
    return False
