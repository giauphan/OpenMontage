#!/usr/bin/env python3
"""Schedule-upload specific project/kind pairs to YouTube as private + publishAt.

Usage: schedule_youtube_slots.py <date> <project>:<kind>:<publish_at_utc> ...

Only the 120s 9:16 `short` flow is supported — the long 16:9 flow was removed.
"""
import json
import sys
from pathlib import Path

from tools.publish_store import PublishStore, publish_key
from tools.publishers.platform_routes import youtube_shorts_title
from tools.publishers.youtube_publisher import YoutubePublisher

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "primary"
ASSET_FIELD = {"short": "yt_shorts"}


def main():
    date = sys.argv[1]
    store = PublishStore()
    publisher = YoutubePublisher()

    for spec in sys.argv[2:]:
        proj, kind, publish_at = spec.split(":", 2)
        meta = json.loads((ROOT / "projects" / proj / "publish_metadata.json").read_text())
        asset = ROOT / meta[ASSET_FIELD[kind]]
        title = youtube_shorts_title(meta["title"])

        key, claimed, existing = store.claim(
            date=date,
            topic=meta["id"],
            platform="youtube",
            account=ACCOUNT,
            kind=kind,
            status="scheduling",
            title=title,
            asset_path=asset,
            source_topic=meta["topic"],
            scheduled_for=publish_at,
        )
        if not claimed:
            status = existing.get("status") if existing else "unknown"
            if status != "failed":
                print(f"skip {proj} {kind}: existing status={status}")
                continue
            key = publish_key(date, meta["id"], "youtube", kind)
            store.update(key, {"status": "scheduling", "error": None, "scheduled_for": publish_at})

        result = publisher.execute(
            {
                "video_path": str(asset),
                "title": title,
                "description": meta.get("description", ""),
                "tags": ["AI", "Công nghệ", "Vietnamese", "OpenMontage"],
                "privacy_status": "private",
                "publish_at": publish_at,
                "category_id": "28",
            }
        )
        if not result.success:
            store.mark_failed(key, str(result.error))
            print(f"FAILED {proj} {kind}: {result.error}")
            continue

        data = result.data or {}
        store.mark_scheduled(
            key,
            video_id=data.get("video_id"),
            video_url=data.get("video_url"),
            scheduled_for=publish_at,
        )
        print(f"scheduled {proj} {kind} {publish_at} {data.get('video_url')}")


if __name__ == "__main__":
    main()
