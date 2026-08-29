#!/usr/bin/env python3
"""Publish FB (scheduled) + IG (immediate) for given projects.

Usage:
  python3 scripts/publish_meta.py <project_id> [<project_id> ...]
  python3 scripts/publish_meta.py --date 2026-08-17 <project_id> [...]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from publish_config import fb_slot_times, load_config
from publish_manual_video import meta_caption
from tools.publish_store import PublishStore, publish_key
from tools.publishers.meta_publisher import MetaPublisher

ROOT = Path(__file__).resolve().parents[1]


def claim_or_skip(store, date, pid, meta, platform, account, kind, title, asset, scheduled_for=None):
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
    parser = argparse.ArgumentParser(description="Publish scheduled FB and immediate IG for projects")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today/tomorrow)")
    parser.add_argument("projects", nargs="+", help="Project folder names under projects/")
    args = parser.parse_args()

    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    fb_page_id = cfg["meta"]["page_id"]
    ig_account_id = cfg["meta"]["ig_account_id"]
    slot_times = fb_slot_times(cfg)

    now = datetime.now(tz)
    target_date = datetime.fromisoformat(args.date).date() if args.date else now.date()

    store = PublishStore()
    publisher = MetaPublisher()

    for idx, proj in enumerate(args.projects):
        meta_path = ROOT / "projects" / proj / "publish_metadata.json"
        if not meta_path.is_file():
            print(f"ERROR: missing {meta_path}")
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pid = meta["id"]
        title = meta["title"]
        caption = meta_caption(title, meta.get("description", title))

        # Dynamic FB slot; FB requires >=10min in the future, roll to next day if passed
        slot_time = slot_times[idx % len(slot_times)]
        slot = datetime.combine(target_date, slot_time, tz)
        if slot <= now + timedelta(minutes=15):
            slot += timedelta(days=1)

        # FB: 120s vertical — SCHEDULED
        fb_path = ROOT / meta["fb_video"]
        if not fb_path.is_file():
            print(f"MISSING FB asset: {fb_path}")
        else:
            fb_key = claim_or_skip(
                store, target_date.isoformat(), pid, meta, "facebook", fb_page_id, "page_video",
                title, fb_path, scheduled_for=slot.isoformat(),
            )
            if fb_key:
                result = publisher.execute({
                    "video_path": str(fb_path),
                    "caption": caption[:2000],
                    "page_id": fb_page_id,
                    "post_to_facebook": True,
                    "post_to_instagram": False,
                    "scheduled_publish_time": int(slot.timestamp()),
                })
                if result.success:
                    data = result.data or {}
                    store.mark_scheduled(
                        fb_key,
                        video_id=data.get("facebook_post_id"),
                        video_url=f"https://facebook.com/{fb_page_id}/videos/{data.get('facebook_post_id')}",
                        scheduled_for=slot.isoformat(),
                    )
                    print(f"FB scheduled {pid}: {data.get('facebook_post_id')} -> {slot.isoformat()}")
                else:
                    store.mark_failed(fb_key, str(result.error))
                    print(f"FB FAILED {pid}: {result.error}")

        # IG: 60s vertical — IMMEDIATE
        ig_path = ROOT / meta["ig_reels"]
        if not ig_path.is_file():
            print(f"MISSING IG asset: {ig_path}")
            continue

        ig_key = claim_or_skip(
            store, target_date.isoformat(), pid, meta, "instagram", ig_account_id, "reels", title, ig_path,
        )
        if ig_key:
            result = publisher.execute({
                "video_path": str(ig_path),
                "caption": caption[:2000],
                "page_id": fb_page_id,
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
