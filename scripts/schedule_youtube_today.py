#!/usr/bin/env python3
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.publish_store import PublishStore, existing_record_summary
from tools.publishers.youtube_publisher import YoutubePublisher

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = ZoneInfo("Asia/Jakarta")
MIN_GAP = timedelta(hours=2)
YOUTUBE_ACCOUNT = "primary"

# YouTube only receives 120s Shorts flow (Long 16:9 removed per policy)
TOPICS = [
    {
        "id": "topic1",
        "title": "Cuộc Chiến Chống AI Slop 2026",
        "description": "YouTube vừa xóa 35 triệu tài khoản bot trong một đợt quét tự động lớn. Các nền tảng mạng xã hội đang siết chặt nội dung AI slop để bảo vệ người dùng và hệ sinh thái sáng tạo.",
        "short": "projects/newsnow-2026-08-09/renders/final_full_vi_9x16.mp4",
        "short_time": time(9, 15),
    },
    {
        "id": "topic2",
        "title": "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026",
        "description": "Agentic AI đang thay đổi cách doanh nghiệp vận hành. Khám phá cách các hệ thống tự động hóa toàn bộ quy trình từ phát triển đến vận hành.",
        "short": "projects/topic2-agentic-ai/renders/final_full_vi_9x16.mp4",
        "short_time": time(14, 15),
    },
    {
        "id": "topic3",
        "title": "Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất",
        "description": "Các phương pháp mới nhất để bảo vệ dữ liệu cá nhân và phòng chống tấn công mạng trong kỷ nguyên số. Hướng dẫn chi tiết cho người dùng và doanh nghiệp.",
        "short": "projects/topic3-cyber-defense/renders/final_full_vi_9x16.mp4",
        "short_time": time(21, 15),
    },
]


def scheduled_at(day, slot):
    return datetime.combine(day, slot, LOCAL_TZ)


def ytv_publish_at(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def upload(topic, kind, publish_at):
    path = ROOT / topic[kind]
    if not path.is_file():
        raise FileNotFoundError(path)
    result = YoutubePublisher().execute({
        "video_path": str(path),
        "title": f'{topic["title"]} #Shorts'[:100],
        "description": topic["description"],
        "privacy_status": "private",
        "publish_at": ytv_publish_at(publish_at),
        "category_id": "28",
    })
    if not result.success:
        raise RuntimeError(result.error or "YouTube schedule failed")
    return result


def schedule_day(day):
    now = datetime.now(LOCAL_TZ)
    store = PublishStore()
    date = day.isoformat()
    planned = []
    for topic in TOPICS:
        planned.append((topic, "short", scheduled_at(day, topic["short_time"])))

    previous = None
    for topic, kind, publish_at in sorted(planned, key=lambda item: item[2]):
        if previous and publish_at - previous < MIN_GAP:
            raise RuntimeError(f"slot gap under 2h: {previous.isoformat()} -> {publish_at.isoformat()}")
        previous = publish_at
        if publish_at <= now + timedelta(minutes=20):
            print(f"skip {date} {topic['id']} {kind}: slot already passed")
            continue
        scheduled_for = publish_at.isoformat()
        asset_path = ROOT / topic[kind]
        if not asset_path.is_file():
            raise FileNotFoundError(asset_path)
        key, claimed, existing = store.claim(
            date=date,
            topic=topic["id"],
            platform="youtube",
            account=YOUTUBE_ACCOUNT,
            kind=kind,
            status="scheduling",
            title=topic["title"],
            asset_path=asset_path,
            scheduled_for=scheduled_for,
        )
        if not claimed:
            print(f"skip {date} {topic['id']} {kind}: {existing_record_summary(existing)}")
            continue
        try:
            result = upload(topic, kind, publish_at)
            data = result.data or {}
            store.mark_scheduled(
                key,
                video_id=data.get("video_id"),
                video_url=data.get("video_url"),
                scheduled_for=scheduled_for,
            )
            print(f"scheduled {date} {topic['id']} {kind} {scheduled_for} {data.get('video_url')}")
        except Exception as exc:
            store.mark_failed(key, str(exc))
            raise


if __name__ == "__main__":
    target = datetime.now(LOCAL_TZ).date()
    if len(sys.argv) == 2:
        target = datetime.fromisoformat(sys.argv[1]).date()
    schedule_day(target)
