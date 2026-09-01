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
from publish_manual_video import validate_project_quality, validate_publish_asset
from tools.publish_store import PublishStore, existing_record_summary
from tools.publishers.platform_routes import youtube_shorts_title
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher

ROOT = Path(__file__).resolve().parents[1]
MIN_GAP = timedelta(hours=2)


def ytv_publish_at(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def upload(project_dir, topic_meta, kind, publish_at):
    path = project_dir / topic_meta[kind]
    if not path.is_file():
        raise FileNotFoundError(path)
    result = YoutubePublisher().execute({
        "video_path": str(path),
        "title": youtube_shorts_title(topic_meta["title"]),
        "description": topic_meta.get("description", ""),
        "privacy_status": "private",
        "publish_at": ytv_publish_at(publish_at),
        "category_id": "28",
    })
    if not result.success:
        raise RuntimeError(result.error or "YouTube schedule failed")
    return result


def schedule_facebook(project_dir, topic_meta, publish_at, page_id):
    """Schedule Facebook video via Meta Graph API native scheduling."""
    video_path = project_dir / topic_meta["yt_shorts"]
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    scheduled_epoch = int(publish_at.astimezone(timezone.utc).timestamp())
    result = MetaPublisher().execute({
        "video_path": str(video_path),
        "caption": topic_meta.get("title", ""),
        "page_id": page_id,
        "post_to_facebook": True,
        "post_to_instagram": False,
        "scheduled_publish_time": scheduled_epoch,
    })
    if not result.success:
        raise RuntimeError(result.error or "Facebook schedule failed")
    return result


def schedule_day(day):
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    yt_account = cfg["youtube"]["account"]
    slot_times = yt_slot_times(cfg)

    now = datetime.now(tz)
    date = day.isoformat()

    planned = []
    for idx, project in enumerate(cfg.get("active_projects", [])):
        proj = project.get("project_id") if isinstance(project, dict) else project
        if not isinstance(proj, str) or not proj:
            print(f"skip malformed active project: {project!r}")
            continue
        project_dir = ROOT / "projects" / proj
        meta_path = project_dir / "publish_metadata.json"
        if not meta_path.is_file():
            print(f"skip {proj}: missing publish_metadata.json")
            continue
        topic_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        validate_project_quality(project_dir)
        asset_path = project_dir / topic_meta["yt_shorts"]
        validate_publish_asset(asset_path, project_dir, "youtube", strict=True)
        if cfg.get("meta", {}).get("page_id"):
            fb_asset_path = project_dir / topic_meta["fb_video"]
            validate_publish_asset(fb_asset_path, project_dir, "facebook", strict=True)
        slot_time = slot_times[idx % len(slot_times)]
        dt = datetime.combine(day, slot_time, tz)
        planned.append((proj, project_dir, topic_meta, "yt_shorts", dt))

    store = PublishStore()
    previous = None
    for proj, project_dir, topic_meta, kind, publish_at in sorted(planned, key=lambda item: item[4]):
        if previous and publish_at - previous < MIN_GAP:
            raise RuntimeError(f"slot gap under 2h: {previous.isoformat()} -> {publish_at.isoformat()}")
        previous = publish_at

        if publish_at <= now + timedelta(minutes=20):
            print(f"skip {date} {proj} {kind}: slot already passed ({publish_at.isoformat()})")
            continue

        scheduled_for = publish_at.isoformat()
        asset_path = project_dir / topic_meta[kind]
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
            result = upload(project_dir, topic_meta, kind, publish_at)
            data = result.data or {}
            store.mark_scheduled(
                key,
                video_id=data.get("video_id"),
                video_url=data.get("video_url"),
                scheduled_for=scheduled_for,
            )
            print(f"scheduled {date} {proj} {kind} {scheduled_for} {data.get('video_url')}")

            # Schedule Facebook upload via native Graph API scheduling
            fb_page_id = cfg.get("meta", {}).get("page_id")
            if fb_page_id:
                fb_key, fb_claimed, fb_existing = store.claim(
                    date=date,
                    topic=topic_meta["id"],
                    platform="facebook",
                    account="primary",
                    kind="video",
                    status="scheduling",
                    title=topic_meta["title"],
                    asset_path=asset_path,
                    scheduled_for=scheduled_for,
                )
                if fb_claimed:
                    try:
                        fb_result = schedule_facebook(project_dir, topic_meta, publish_at, fb_page_id)
                        fb_data = fb_result.data or {}
                        fb_entries = fb_data.get("publish_log", {}).get("entries", [])
                        fb_url = fb_entries[0].get("url") if fb_entries else None
                        store.mark_scheduled(
                            fb_key,
                            video_id=fb_entries[0].get("video_id") if fb_entries else None,
                            video_url=fb_url,
                            scheduled_for=scheduled_for,
                        )
                        print(f"scheduled {date} {proj} fb_video {scheduled_for} {fb_url}")
                    except Exception as fb_exc:
                        store.mark_failed(fb_key, str(fb_exc))
                        print(f"facebook schedule failed {date} {proj}: {fb_exc}")
                else:
                    print(f"skip fb {date} {proj}: {existing_record_summary(fb_existing)}")
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
