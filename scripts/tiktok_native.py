"""TikTok scheduled publishing step for the native, approval-validated scheduling path.

Uses Toolcase Gateway TikTok Creator Studio adapter with native schedule_time
per SCHEDULING_AND_AUTO_TRANSLATE_GUIDE.md.
The caller must already have passed the validation, news-evidence,
provenance and cryptographic approval gates for the exact asset passed in.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.publish_store import publish_key

TIKTOK_KIND = "video"
_VISIBILITIES = {"only-me", "public", "friends"}


def tiktok_visibility() -> str:
    """Resolve visibility from env; fail closed to private on unknown values."""
    value = os.environ.get("TIKTOK_DEFAULT_VISIBILITY", "only-me").strip().lower()
    return value if value in _VISIBILITIES else "only-me"


def publish_tiktok_native(
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
    locale: str = "en-US",
) -> bool:
    """Publish or schedule one approved asset to TikTok. Returns True when it FAILED."""
    key = publish_key(date, topic_id, "tiktok", TIKTOK_KIND)
    if not asset_path.is_file():
        print(f"failed {topic_id}: missing TikTok asset file {asset_path}")
        return True

    schedule_epoch: int | None = None
    if scheduled_for:
        try:
            schedule_epoch = int(datetime.fromisoformat(scheduled_for).timestamp())
        except Exception:
            pass

    if dry_run:
        sched_info = f" scheduled for {scheduled_for} (epoch={schedule_epoch})" if schedule_epoch else ""
        print(f"SHADOW/DRY-RUN: Simulated TikTok publish{sched_info} for {topic_id} ({asset_path.name}); no store mutations, no upload")
        return False

    existing = store.get(key) if hasattr(store, "get") else None
    if existing and existing.get("status") in ("scheduled", "published"):
        print(f"ALREADY PUBLISHED {topic_id} on tiktok ({existing.get('video_url', '')})")
        return False

    if existing and existing.get("status") == "failed" and (existing.get("video_id") or existing.get("platform_id")):
        print(f"FAILED CLAIM {topic_id} on tiktok has a remote ID; reconciliation required")
        return True

    key, claimed, _ = store.claim(
            date=date,
            topic=topic_id,
            platform="tiktok",
            account="tiktok",
            kind=TIKTOK_KIND,
            status="scheduling",
            title=title,
            asset_path=asset_path,
            scheduled_for=scheduled_for,
            content_hash=content_hash,
            template_id=template_id,
    )
    if not claimed:
        print(f"SKIP: TikTok {date} {topic_id} (already claimed)")
        return bool(existing and existing.get("status") == "failed")

    if publisher_factory is None:
        from tools.publishers.tiktok_publisher import TiktokPublisher as publisher_factory
    caption = f"{title}\n\n{description}".strip() if description else title

    inputs: dict[str, Any] = {
        "video_path": str(asset_path),
        "caption": caption,
        "title": title,
        "visibility": "public" if schedule_epoch else tiktok_visibility(),
        "locale": locale,
    }
    if schedule_epoch:
        inputs["schedule_time"] = schedule_epoch

    try:
        result = publisher_factory().execute(inputs)
    except Exception as exc:
        store.mark_failed(key, str(exc))
        print(f"TikTok error {topic_id}: {exc}")
        return True

    data = result.data or {}
    remote_id = data.get("item_id") or data.get("project_id")
    if not result.success or not remote_id:
        err = result.error or "TikTok returned no item id"
        store.mark_failed(key, err)
        print(f"TikTok failed {topic_id}: {err}")
        return True

    is_scheduled = data.get("status") == "scheduled" or bool(schedule_epoch)
    if is_scheduled:
        store.mark_scheduled(
            key,
            video_id=remote_id,
            video_url=data.get("video_url"),
            scheduled_for=scheduled_for,
        )
        print(f"TikTok scheduled {topic_id} ({remote_id}) for {scheduled_for}")
    else:
        store.mark_published(
            key,
            video_id=remote_id,
            video_url=data.get("video_url"),
            platform_id=data.get("project_id") or remote_id,
        )
        print(f"TikTok published {topic_id} ({remote_id}) visibility={data.get('visibility')}")
    return False
