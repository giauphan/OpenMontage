#!/usr/bin/env python3
"""Publish FB (scheduled) + IG (immediate) for given projects.

Usage:
  python3 scripts/publish_meta.py <project_id> [<project_id> ...]
  python3 scripts/publish_meta.py --date 2026-08-17 <project_id> [...]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.publish_config import fb_slot_times, load_config
except ImportError:
    from publish_config import fb_slot_times, load_config
from tools.publish_store import PublishStore, publish_key
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.social_metadata import meta_caption

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


def _publish_fb(
    store: PublishStore,
    publisher: MetaPublisher,
    target_date: Any,
    pid: str,
    meta: dict[str, Any],
    title: str,
    caption: str,
    slot: datetime,
    now: datetime,
    fb_page_id: str,
) -> None:
    fb_path = ROOT / meta["fb_video"]
    if not fb_path.is_file():
        print(f"MISSING FB asset: {fb_path}")
        return

    fb_key = claim_or_skip(
        store, target_date.isoformat(), pid, meta, "facebook", fb_page_id, "page_video",
        title, fb_path, scheduled_for=slot.isoformat(),
    )
    if not fb_key:
        return

    from tools.publishers.facebook_publisher import FacebookPublisher
    fb_pub = FacebookPublisher()
    now_sec = int(now.timestamp())
    sched_sec = int(slot.timestamp())
    fb_inputs: dict[str, Any] = {
        "video_path": str(fb_path),
        "caption": caption[:2000],
        "title": title,
        "target_id": fb_page_id,
        "enable_auto_translate": True,
        "publish_type": "REEL",
    }
    if sched_sec >= now_sec + 600:
        fb_inputs["scheduled_publish_time"] = sched_sec

    result = fb_pub.execute(fb_inputs)
    err_str = str(result.error or "")
    is_pre_upload_failure = (
        "connection refused" in err_str.lower()
        or "no route to host" in err_str.lower()
        or "connection failed" in err_str.lower()
        or "gateway_url" in err_str.lower()
        or "missing required" in err_str.lower()
    ) and "timeout" not in err_str.lower()

    if not result.success and is_pre_upload_failure and os.environ.get("TOKEN_FACEBOOK"):
        result = publisher.execute({
            "video_path": str(fb_path),
            "caption": caption[:2000],
            "page_id": fb_page_id,
            "post_to_facebook": True,
            "post_to_instagram": False,
            "scheduled_publish_time": int(slot.timestamp()),
        })
    data = (result.data or {}) if result.success else {}
    fb_post_id = data.get("facebook_post_id") or data.get("video_id")
    fb_ok = bool(result.success and fb_post_id)
    fb_error = result.error if not result.success else f"Facebook returned no video/post ID: {data!r}"
    if fb_ok:
        video_url = data.get("video_url") or f"https://facebook.com/{fb_page_id}/videos/{fb_post_id}"
        store.mark_scheduled(
            fb_key,
            video_id=fb_post_id,
            video_url=video_url,
            scheduled_for=slot.isoformat(),
        )
        print(f"FB scheduled {pid}: {fb_post_id} -> {slot.isoformat()}")
    else:
        store.mark_failed(fb_key, str(fb_error))
        print(f"FB FAILED {pid}: {fb_error}")


def _publish_ig(
    store: PublishStore,
    publisher: MetaPublisher,
    target_date: Any,
    pid: str,
    meta: dict[str, Any],
    title: str,
    caption: str,
    fb_page_id: str,
    ig_account_id: str,
) -> None:
    ig_path = ROOT / meta["ig_reels"]
    if not ig_path.is_file():
        print(f"MISSING IG asset: {ig_path}")
        return

    ig_key = claim_or_skip(
        store, target_date.isoformat(), pid, meta, "instagram", ig_account_id, "reels", title, ig_path,
    )
    if not ig_key:
        return

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


def _process_single_project(
    proj: str,
    idx: int,
    target_date: Any,
    slot_times: list[Any],
    now: datetime,
    tz: Any,
    cfg: dict[str, Any],
    store: PublishStore,
    publisher: MetaPublisher,
) -> None:
    meta_path = ROOT / "projects" / proj / "publish_metadata.json"
    if not meta_path.is_file():
        print(f"ERROR: missing {meta_path}")
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pid = meta["id"]
    title = meta["title"]
    caption = meta_caption(title, meta.get("description", title))

    slot_time = slot_times[idx % len(slot_times)]
    slot = datetime.combine(target_date, slot_time, tz)
    if slot <= now + timedelta(minutes=15):
        slot += timedelta(days=1)

    fb_page_id = cfg["meta"]["page_id"]
    ig_account_id = cfg["meta"]["ig_account_id"]

    _publish_fb(store, publisher, target_date, pid, meta, title, caption, slot, now, fb_page_id)
    _publish_ig(store, publisher, target_date, pid, meta, title, caption, fb_page_id, ig_account_id)


def main():
    parser = argparse.ArgumentParser(description="Publish scheduled FB and immediate IG for projects")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (defaults to today/tomorrow)")
    parser.add_argument("projects", nargs="+", help="Project folder names under projects/")
    args = parser.parse_args()

    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    slot_times = fb_slot_times(cfg)

    now = datetime.now(tz)
    target_date = datetime.fromisoformat(args.date).date() if args.date else now.date()

    store = PublishStore()
    publisher = MetaPublisher()

    for idx, proj in enumerate(args.projects):
        _process_single_project(proj, idx, target_date, slot_times, now, tz, cfg, store, publisher)


if __name__ == "__main__":
    main()
