#!/usr/bin/env python3
"""Schedule active projects to YouTube for a target date based on config/publish_schedule.json.

Usage:
  python3 scripts/schedule_youtube_today.py [YYYY-MM-DD]
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from publish_config import load_config, yt_slot_times
from tools.publish_store import PublishStore, existing_record_summary
from tools.publishers.youtube_publisher import YoutubePublisher

ROOT = Path(__file__).resolve().parents[1]
MIN_GAP = timedelta(hours=2)


def ytv_publish_at(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def upload(topic_meta, kind, publish_at):
    path = ROOT / topic_meta[kind]
    if not path.is_file():
        raise FileNotFoundError(path)
    result = YoutubePublisher().execute({
        "video_path": str(path),
        "title": f'{topic_meta["title"]} #Shorts'[:100],
        "description": topic_meta.get("description", ""),
        "privacy_status": "private",
        "publish_at": ytv_publish_at(publish_at),
        "category_id": "28",
    })
    if not result.success:
        raise RuntimeError(result.error or "YouTube schedule failed")
    return result


def schedule_day(day):
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    yt_account = cfg["youtube"]["account"]
    slot_times = yt_slot_times(cfg)

    now = datetime.now(tz)
    store = PublishStore()
    date = day.isoformat()

    planned = []
    for idx, proj in enumerate(cfg.get("active_projects", [])):
        meta_path = ROOT / "projects" / proj / "publish_metadata.json"
        if not meta_path.is_file():
            print(f"skip {proj}: missing publish_metadata.json")
            continue
        topic_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        slot_time = slot_times[idx % len(slot_times)]
        dt = datetime.combine(day, slot_time, tz)
        planned.append((proj, topic_meta, "yt_shorts", dt))

    previous = None
    for proj, topic_meta, kind, publish_at in sorted(planned, key=lambda item: item[3]):
        if previous and publish_at - previous < MIN_GAP:
            raise RuntimeError(f"slot gap under 2h: {previous.isoformat()} -> {publish_at.isoformat()}")
        previous = publish_at

        if publish_at <= now + timedelta(minutes=20):
            print(f"skip {date} {proj} {kind}: slot already passed ({publish_at.isoformat()})")
            continue

        scheduled_for = publish_at.isoformat()
        asset_path = ROOT / topic_meta[kind]
        if not asset_path.is_file():
            raise FileNotFoundError(asset_path)

        key, claimed, existing = store.claim(
            date=date,
            topic=topic_meta["id"],
            platform="youtube",
            account=yt_account,
            kind="short",
            status="scheduling",
            title=topic_meta["title"],
            asset_path=asset_path,
            scheduled_for=scheduled_for,
        )
        if not claimed:
            print(f"skip {date} {proj} {kind}: {existing_record_summary(existing)}")
            continue

        try:
            result = upload(topic_meta, kind, publish_at)
            data = result.data or {}
            store.mark_scheduled(
                key,
                video_id=data.get("video_id"),
                video_url=data.get("video_url"),
                scheduled_for=scheduled_for,
            )
            print(f"scheduled {date} {proj} {kind} {scheduled_for} {data.get('video_url')}")
        except Exception as exc:
            store.mark_failed(key, str(exc))
            raise


if __name__ == "__main__":
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    target = datetime.now(tz).date()
    if len(sys.argv) == 2:
        target = datetime.fromisoformat(sys.argv[1]).date()
    schedule_day(target)
