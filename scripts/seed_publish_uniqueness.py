#!/usr/bin/env python3
from pathlib import Path

from tools.publish_store import PublishStore, file_sha256, media_fingerprint, normalize_identity, publish_key, uniqueness_key, utc_now

ROOT = Path(__file__).resolve().parents[1]

RECORDS = [
    {
        "date": "2026-08-13",
        "topic": "topic1",
        "title": "Cuộc Chiến Chống AI Slop 2026",
        "platform": "youtube",
        "account": "primary",
        "kind": "long",
        "asset_path": "projects/newsnow-2026-08-09/renders/final_full_vi_9x16.mp4",
        "status": "scheduled",
        "video_id": "LkyU68RaGWs",
        "video_url": "https://youtu.be/LkyU68RaGWs",
    },
    {
        "date": "2026-08-13",
        "topic": "topic1",
        "title": "Cuộc Chiến Chống AI Slop 2026",
        "platform": "youtube",
        "account": "primary",
        "kind": "short",
        "asset_path": "projects/newsnow-2026-08-09/renders/final_reels_vi_9x16.mp4",
        "status": "scheduled",
        "video_id": "GjUT1jd0XxM",
        "video_url": "https://youtu.be/GjUT1jd0XxM",
    },
    {
        "date": "2026-08-13",
        "topic": "topic2",
        "title": "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026",
        "platform": "youtube",
        "account": "primary",
        "kind": "long",
        "asset_path": "projects/topic2-agentic-ai/renders/final_full_vi_9x16.mp4",
        "status": "published",
        "video_id": "9ObcXJpnxZ8",
        "video_url": "https://youtu.be/9ObcXJpnxZ8",
    },
    {
        "date": "2026-08-13",
        "topic": "topic2",
        "title": "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026",
        "platform": "youtube",
        "account": "primary",
        "kind": "short",
        "asset_path": "projects/topic2-agentic-ai/renders/final_reels_vi_9x16.mp4",
        "status": "published",
        "video_id": "rBm1tj5HI-U",
        "video_url": "https://youtu.be/rBm1tj5HI-U",
    },
    {
        "date": "2026-08-13",
        "topic": "topic3",
        "title": "Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất",
        "platform": "youtube",
        "account": "primary",
        "kind": "long",
        "asset_path": "projects/topic3-cyber-defense/renders/final_full_vi_9x16.mp4",
        "status": "scheduled",
        "video_id": "ZRwlKJZiNuo",
        "video_url": "https://youtu.be/ZRwlKJZiNuo",
    },
    {
        "date": "2026-08-13",
        "topic": "topic3",
        "title": "Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất",
        "platform": "youtube",
        "account": "primary",
        "kind": "short",
        "asset_path": "projects/topic3-cyber-defense/renders/final_reels_vi_9x16.mp4",
        "status": "scheduled",
        "video_id": "9sAWgiVDZas",
        "video_url": "https://youtu.be/9sAWgiVDZas",
    },
    {
        "date": "2026-08-13",
        "topic": "topic1",
        "title": "Cuộc Chiến Chống AI Slop 2026",
        "platform": "instagram",
        "account": "17841434265610775",
        "kind": "reels",
        "asset_path": "projects/newsnow-2026-08-09/renders/final_reels_vi_9x16.mp4",
        "status": "published",
        "platform_id": "17991745461009026",
    },
    {
        "date": "2026-08-13",
        "topic": "topic2",
        "title": "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026",
        "platform": "instagram",
        "account": "17841434265610775",
        "kind": "reels",
        "asset_path": "projects/topic2-agentic-ai/renders/final_reels_vi_9x16.mp4",
        "status": "published",
        "platform_id": "18021564140698455",
    },
]


def main():
    store = PublishStore()
    for record in RECORDS:
        asset_path = ROOT / record["asset_path"]
        if not asset_path.is_file():
            raise FileNotFoundError(asset_path)
        source_sha256 = file_sha256(asset_path)
        visual_sha256 = media_fingerprint(asset_path)
        source_key = publish_key(record["date"], record["topic"], record["platform"], record["kind"])
        data = {
            **record,
            "asset_path": str(asset_path),
            "source_sha256": source_sha256,
            "visual_sha256": visual_sha256,
            "normalized_title": normalize_identity(record["title"]),
            "source_publish_key": source_key,
            "record_type": "uniqueness",
            "seeded_at": utc_now(),
            "updated_at": utc_now(),
        }
        identities = {
            "topic": record["topic"],
            "title": record["title"],
            "source_topic": record["topic"],
            "source_path": str(asset_path.resolve()),
            "source_visual": visual_sha256,
            "source": source_sha256,
        }
        for identity_type, value in identities.items():
            key = uniqueness_key(record["platform"], record["account"], record["kind"], identity_type, value)
            created, _ = store.create_once(key, {**data, "identity_type": identity_type})
            print(f"{'seed' if created else 'skip'} {record['platform']} {record['kind']} {record['topic']} {identity_type}")


if __name__ == "__main__":
    main()
