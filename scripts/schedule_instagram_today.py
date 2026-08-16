#!/usr/bin/env python3
from datetime import datetime, time
from zoneinfo import ZoneInfo

from tools.publish_store import PublishStore, existing_record_summary, publish_key

LOCAL_TZ = ZoneInfo("Asia/Jakarta")
TOPICS = [
    ("topic1", "Cuộc Chiến Chống AI Slop 2026", "projects/newsnow-2026-08-09/renders/final_reels_vi_9x16.mp4", time(11, 0)),
    ("topic2", "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026", "projects/topic2-agentic-ai/renders/final_reels_vi_9x16.mp4", time(16, 0)),
    ("topic3", "Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất", "projects/topic3-cyber-defense/renders/final_reels_vi_9x16.mp4", time(23, 0)),
]


def main():
    store = PublishStore()
    date = datetime.now(LOCAL_TZ).date().isoformat()
    for topic_id, title, path, slot in TOPICS:
        record = store.get(publish_key(date, topic_id, "instagram", "reels"))
        if record:
            print(f"skip {topic_id}: {existing_record_summary(record)}")
            continue
        print(f"Instagram API scheduling unavailable: use scripts/publish_slot.py {topic_id}-instagram at {slot.isoformat()} for {path}")


if __name__ == "__main__":
    main()
