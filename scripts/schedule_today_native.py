#!/usr/bin/env python3
"""Same-day native scheduler: validates, queues, schedules YT/FB on platform, keeps IG on cron.
Filters queued projects by publish_date == --date. Usage: --date YYYY-MM-DD (default today VN).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.publish_config import load_config, publish_timezone
from tools.publish_store import PublishStore
from scripts.publish_manual_video import validate_project_quality
from tools.publishers.platform_routes import youtube_shorts_title
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher

def ytv_publish_at(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def main():
    parser = argparse.ArgumentParser(description="Same-day native scheduler for queued slots")
    parser.add_argument("--date", help="Override local date YYYY-MM-DD (default today)")
    args = parser.parse_args()
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    yt_account = cfg["youtube"]["account"]
    fb_page_id = cfg.get("meta",{}).get("page_id")
    today = (datetime.strptime(args.date,"%Y-%m-%d").date() if args.date else datetime.now(tz).date())
    date = today.isoformat()
    # Only schedule queued projects whose publish_date matches the requested date
    queue = [p for p in cfg.get("active_projects",[]) if isinstance(p,dict) and p.get("publish_date")==date]
    if not queue:
        print(f"No queued projects for {date}")
        return 0
    queue.sort(key=lambda p: p.get("publish_time",""))
    MIN_GAP = timedelta(hours=2)
    now = datetime.now(tz)
    store = PublishStore()
    previous = None
    failed = False
    for q in queue:
        proj = q["project_id"]
        hh,mm = q["publish_time"].split(":",1)
        publish_at = datetime.combine(today, datetime.strptime(f"{hh}:{mm}","%H:%M").time(), tz)
        if previous and publish_at - previous < MIN_GAP:
            print(f"failed {proj}: slot gap under 2h: {previous.isoformat()} -> {publish_at.isoformat()}")
            failed = True
            continue
        previous = publish_at
        if publish_at <= now + timedelta(minutes=20):
            print(f"failed {proj}: slot passed ({publish_at.isoformat()})")
            failed = True
            continue
        project_dir = ROOT / "projects" / proj
        meta_path = project_dir / "publish_metadata.json"
        if not meta_path.is_file():
            print(f"failed {proj}: missing publish_metadata.json")
            failed = True
            continue
        topic_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta_status = topic_meta.get("status","")
        if meta_status in ("published", "scheduled"):
            print(f"failed {proj}: status '{meta_status}'")
            failed = True
            continue
        yt_rel = topic_meta.get("yt_shorts")
        fb_rel = topic_meta.get("fb_video", topic_meta.get("fb_reels"))
        asset_path = project_dir / yt_rel if yt_rel else None
        if not asset_path or not asset_path.is_file():
            print(f"failed {proj}: missing YouTube asset file {asset_path}")
            failed = True
            continue
        try:
            validate_project_quality(project_dir, strict=True)
        except Exception as e:
            print(f"failed {proj}: quality validation failed: {e}")
            failed = True
            continue
        scheduled_for = publish_at.isoformat()
        yt_key = None; yt_claimed = False
        # YT
        if yt_rel and (project_dir / yt_rel).is_file():
            yt_key, yt_claimed,_ = store.claim(date=date, topic=topic_meta["id"], platform="youtube", account=yt_account, kind="short", status="scheduling", title=topic_meta["title"], asset_path=project_dir/yt_rel, scheduled_for=scheduled_for)
        if yt_claimed:
            try:
                r = YoutubePublisher().execute({"video_path":str(project_dir/yt_rel),"title":youtube_shorts_title(topic_meta["title"]),"description":topic_meta.get("description",""),"privacy_status":"private","publish_at":ytv_publish_at(publish_at),"category_id":"28"})
                if r.success:
                    store.mark_scheduled(yt_key, video_id=r.data.get("video_id"), video_url=r.data.get("video_url"), scheduled_for=scheduled_for)
                    print(f"YT scheduled {proj} {scheduled_for}")
                else:
                    store.mark_failed(yt_key, r.error)
                    print(f"YT failed {proj}: {r.error}")
                    failed = True
            except Exception as e:
                store.mark_failed(yt_key, str(e))
                print(f"YT error {proj}: {e}")
                failed = True
        # FB (independent of YT claim)
        if fb_page_id and fb_rel and (project_dir / fb_rel).is_file():
            fb_key, fb_claimed,_ = store.claim(date=date, topic=topic_meta["id"], platform="facebook", account="primary", kind="video", status="scheduling", title=topic_meta["title"], asset_path=project_dir/fb_rel, scheduled_for=scheduled_for)
            if fb_claimed:
                epoch = int(publish_at.astimezone(timezone.utc).timestamp())
                try:
                    r = MetaPublisher().execute({"video_path":str(project_dir/fb_rel),"caption":topic_meta.get("title",""),"page_id":fb_page_id,"post_to_facebook":True,"post_to_instagram":False,"scheduled_publish_time":epoch})
                    if r.success:
                        store.mark_scheduled(fb_key, video_id=((r.data or {}).get("publish_log",{}).get("entries",[{}])[0].get("video_id")), scheduled_for=scheduled_for)
                        print(f"FB scheduled {proj} {scheduled_for}")
                    else:
                        store.mark_failed(fb_key, r.error)
                        print(f"FB failed {proj}: {r.error}")
                        failed = True
                except Exception as e:
                    store.mark_failed(fb_key, str(e))
                    print(f"FB error {proj}: {e}")
                    failed = True
        time.sleep(1)
    if failed:
        sys.exit(1)
    return 0

if __name__ == "__main__": raise SystemExit(main())
