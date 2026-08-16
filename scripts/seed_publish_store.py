#!/usr/bin/env python3
from tools.publish_store import PublishStore, existing_record_summary, publish_key, utc_now

RECORDS = [
    {
        "date": "2026-08-13",
        "topic": "topic2",
        "platform": "youtube",
        "kind": "long",
        "status": "published",
        "video_id": "9ObcXJpnxZ8",
        "video_url": "https://youtu.be/9ObcXJpnxZ8",
        "published_at": "2026-08-13T10:26:00+07:00",
    },
    {
        "date": "2026-08-13",
        "topic": "topic2",
        "platform": "youtube",
        "kind": "short",
        "status": "published",
        "video_id": "rBm1tj5HI-U",
        "video_url": "https://youtu.be/rBm1tj5HI-U",
        "published_at": "2026-08-13T00:00:00+07:00",
    },
    {
        "date": "2026-08-13",
        "topic": "topic1",
        "platform": "instagram",
        "kind": "reels",
        "status": "published",
        "platform_id": "17991745461009026",
        "published_at": "2026-08-13T00:00:00+07:00",
    },
    {
        "date": "2026-08-13",
        "topic": "topic2",
        "platform": "instagram",
        "kind": "reels",
        "status": "published",
        "platform_id": "18021564140698455",
        "published_at": "2026-08-13T00:00:00+07:00",
    },
    {
        "date": "2026-08-14",
        "topic": "topic1",
        "platform": "youtube",
        "kind": "long",
        "status": "scheduled",
        "video_id": "LkyU68RaGWs",
        "video_url": "https://youtu.be/LkyU68RaGWs",
        "scheduled_for": "2026-08-14T07:00:00+07:00",
    },
    {
        "date": "2026-08-14",
        "topic": "topic1",
        "platform": "youtube",
        "kind": "short",
        "status": "scheduled",
        "video_id": "GjUT1jd0XxM",
        "video_url": "https://youtu.be/GjUT1jd0XxM",
        "scheduled_for": "2026-08-14T09:15:00+07:00",
    },
    {
        "date": "2026-08-14",
        "topic": "topic2",
        "platform": "youtube",
        "kind": "long",
        "status": "scheduled",
        "video_id": "p1ekurjNX7M",
        "video_url": "https://youtu.be/p1ekurjNX7M",
        "scheduled_for": "2026-08-14T12:00:00+07:00",
    },
    {
        "date": "2026-08-14",
        "topic": "topic2",
        "platform": "youtube",
        "kind": "short",
        "status": "scheduled",
        "video_id": "Gzt1MqZzBLg",
        "video_url": "https://youtu.be/Gzt1MqZzBLg",
        "scheduled_for": "2026-08-14T14:15:00+07:00",
    },
    {
        "date": "2026-08-14",
        "topic": "topic3",
        "platform": "youtube",
        "kind": "long",
        "status": "scheduled",
        "video_id": "ZRwlKJZiNuo",
        "video_url": "https://youtu.be/ZRwlKJZiNuo",
        "scheduled_for": "2026-08-14T19:00:00+07:00",
    },
    {
        "date": "2026-08-14",
        "topic": "topic3",
        "platform": "youtube",
        "kind": "short",
        "status": "scheduled",
        "video_id": "9sAWgiVDZas",
        "video_url": "https://youtu.be/9sAWgiVDZas",
        "scheduled_for": "2026-08-14T21:15:00+07:00",
    },
]


def main():
    store = PublishStore()
    for record in RECORDS:
        key = publish_key(record["date"], record["topic"], record["platform"], record["kind"])
        data = dict(record)
        data["seeded_at"] = utc_now()
        data["updated_at"] = utc_now()
        created, existing = store.create_once(key, data)
        if created:
            print(f"seed {key}: created")
        else:
            print(f"seed {key}: skip {existing_record_summary(existing)}")


if __name__ == "__main__":
    main()
