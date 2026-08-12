import json
import sys
from pathlib import Path
from tools.publishers.youtube_publisher import YoutubePublisher
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.tiktok_publisher import TiktokPublisher

def publish_video(metadata_path):
    meta = json.loads(Path(metadata_path).read_text())
    title = meta["title"]
    description = meta["description"]

    print(f"=== PUBLISHING TOPIC: {title} ===")

    # 1. YouTube Long-Form (16:9)
    print("1. Publishing to YouTube Long-Form (16:9)...")
    yt_long_res = YoutubePublisher().execute({
        "video_path": meta["yt_long"],
        "title": title[:100],
        "description": description,
        "privacy_status": "public",
        "category_id": "28",
    })
    print(f"YouTube Long result: {yt_long_res.success}")

    # 2. YouTube Shorts (9:16 Short)
    print("2. Publishing to YouTube Shorts (9:16 Short)...")
    yt_short_res = YoutubePublisher().execute({
        "video_path": meta["yt_shorts"],
        "title": f"{title} #Shorts"[:100],
        "description": description,
        "privacy_status": "public",
        "category_id": "28",
    })
    print(f"YouTube Shorts result: {yt_short_res.success}")

    # 3. Instagram Reels (9:16 Short)
    print("3. Publishing to Instagram Reels (9:16 Short)...")
    ig_res = MetaPublisher().execute({
        "video_path": meta["ig_reels"],
        "page_id": "100083515437898",
        "caption": f"{title} #TechNews #Vietnam #OpenMontage",
        "post_to_facebook": False,
        "post_to_instagram": True,
    })
    print(f"Instagram Reels result: {ig_res.success}")

    # 4. Facebook Reels (9:16 Full)
    print("4. Publishing to Facebook Reels (9:16 Full)...")
    fb_res = MetaPublisher().execute({
        "video_path": meta["fb_reels"],
        "page_id": "100083515437898",
        "caption": f"{title} #TechNews #Vietnam #OpenMontage",
        "post_to_facebook": True,
        "post_to_instagram": False,
    })
    print(f"Facebook Reels result: {fb_res.success}")

    # 5. TikTok (9:16 Full)
    print("5. Publishing to TikTok (9:16 Full)...")
    tt_res = TiktokPublisher().execute({
        "video_path": meta["tiktok"],
        "caption": f"{title} #TechNews #Vietnam #OpenMontage",
    })
    print(f"TikTok result: {tt_res.success}")

    print(f"=== COMPLETED TOPIC: {title} ===\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        publish_video(sys.argv[1])
    else:
        print("Usage: python publish_scheduled.py <metadata_path>")
