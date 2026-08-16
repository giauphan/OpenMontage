#!/usr/bin/env python3
"""Publish FB (scheduled) + IG (immediate) for given projects.

Usage: python3 scripts/publish_meta.py <project_id> [<project_id> ...]
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.publish_store import PublishStore, publish_key
from tools.publishers.meta_publisher import MetaPublisher

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = ZoneInfo("Asia/Jakarta")
FB_PAGE_ID = "1183103681563663"
IG_ACCOUNT_ID = "17841434265610775"

# Schedule slots for tomorrow (WIB) — 2h apart
FB_SLOTS = {
    "quantum-ai-chips-2026": datetime(2026, 8, 16, 12, 0, tzinfo=LOCAL_TZ),  # 12:00 WIB
    "robotics-dark-factories-2026": datetime(2026, 8, 16, 14, 0, tzinfo=LOCAL_TZ),  # 14:00 WIB
}


def claim_or_skip(store, date, pid, meta, platform, account, kind, title, asset, scheduled_for=None):
    """Claim in Firestore. Returns key if we should proceed, else None."""
    key, claimed, existing = store.claim(
        date=date,
        topic=pid,
        platform=platform,
        account=account,
        kind=kind,
        status="uploading",
        title=title,
        asset_path=asset,
        source_topic=meta["topic"],
        scheduled_for=scheduled_for,
    )
    if claimed:
        return key
    status = existing.get("status") if existing else "unknown"
    if status != "failed":
        print(f"SKIP {platform} {pid}: existing status={status}")
        return None
    key = publish_key(date, pid, platform, kind)
    store.update(key, {"status": "uploading", "error": None})
    return key


def main():
    store = PublishStore()
    publisher = MetaPublisher()
    date = datetime.now(LOCAL_TZ).date().isoformat()

    for proj in sys.argv[1:]:
        meta = json.loads((ROOT / "projects" / proj / "publish_metadata.json").read_text())
        pid = meta["id"]
        title = meta["title"]
        caption = meta.get("description", title)

        # FB: 120s vertical (final_full_vi_9x16.mp4) — SCHEDULED
        fb_path = ROOT / meta["fb_video"]
        if not fb_path.is_file():
            print(f"MISSING FB asset: {fb_path}")
        else:
            slot = FB_SLOTS[pid]
            fb_key = claim_or_skip(
                store, date, pid, meta, "facebook", FB_PAGE_ID, "page_video",
                title, fb_path, scheduled_for=slot.isoformat(),
            )
            if fb_key:
                result = publisher.execute({
                    "video_path": str(fb_path),
                    "caption": caption[:2000],
                    "page_id": FB_PAGE_ID,
                    "post_to_facebook": True,
                    "post_to_instagram": False,
                    "scheduled_publish_time": int(slot.timestamp()),
                })
                if result.success:
                    data = result.data or {}
                    store.mark_scheduled(
                        fb_key,
                        video_id=data.get("facebook_post_id"),
                        video_url=f"https://facebook.com/{FB_PAGE_ID}/videos/{data.get('facebook_post_id')}",
                        scheduled_for=slot.isoformat(),
                    )
                    print(f"FB scheduled {pid}: {data.get('facebook_post_id')} -> {slot.isoformat()}")
                else:
                    store.mark_failed(fb_key, str(result.error))
                    print(f"FB FAILED {pid}: {result.error}")

        # IG: 60s vertical (final_reels_vi_9x16.mp4) — IMMEDIATE
        ig_path = ROOT / meta["ig_reels"]
        if not ig_path.is_file():
            print(f"MISSING IG asset: {ig_path}")
            continue

        ig_key = claim_or_skip(
            store, date, pid, meta, "instagram", IG_ACCOUNT_ID, "reels", title, ig_path,
        )
        if ig_key:
            result = publisher.execute({
                "video_path": str(ig_path),
                "caption": caption[:2000],
                "page_id": FB_PAGE_ID,
                "post_to_facebook": False,
                "post_to_instagram": True,
            })
            if result.success:
                data = result.data or {}
                store.mark_published(
                    ig_key,
                    video_id=data.get("instagram_media_id"),
                    platform_id=data.get("instagram_media_id"),
                )
                print(f"IG published {pid}: {data.get('instagram_media_id')}")
            else:
                store.mark_failed(ig_key, str(result.error))
                print(f"IG FAILED {pid}: {result.error}")


if __name__ == "__main__":
    main()
