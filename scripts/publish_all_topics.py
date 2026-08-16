#!/usr/bin/env python3
raise SystemExit("publish_all_topics.py is disabled; use scripts/schedule_youtube_today.py and Firebase-guarded slot publishers.")

TOPICS = [
    {
        'id': 'topic1',
        'title': 'Cuộc Chiến Chống AI Slop 2026',
        'description': 'YouTube vừa xóa 35 triệu tài khoản bot trong một đợt quét tự động lớn. Các nền tảng mạng xã hội đang siết chặt nội dung AI slop để bảo vệ người dùng và hệ sinh thái sáng tạo.',
        'yt_long': 'projects/newsnow-2026-08-09/renders/final_full_vi_16x9.mp4',
        'yt_shorts': 'projects/newsnow-2026-08-09/renders/final_reels_vi_9x16.mp4',
        'ig_reels': 'projects/newsnow-2026-08-09/renders/final_reels_vi_9x16.mp4',
        'fb_reels': 'projects/newsnow-2026-08-09/renders/final_full_vi_9x16.mp4',
        'tiktok': 'projects/newsnow-2026-08-09/renders/final_full_vi_9x16.mp4',
        'schedule': '07:00 AM',
    },
    {
        'id': 'topic2',
        'title': 'Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026',
        'description': 'Agentic AI đang thay đổi cách doanh nghiệp vận hành. Khám phá cách các hệ thống tự động hóa toàn bộ quy trình từ phát triển đến vận hành.',
        'yt_long': 'projects/topic2-agentic-ai/renders/final_full_vi_16x9.mp4',
        'yt_shorts': 'projects/topic2-agentic-ai/renders/final_reels_vi_9x16.mp4',
        'ig_reels': 'projects/topic2-agentic-ai/renders/final_reels_vi_9x16.mp4',
        'fb_reels': 'projects/topic2-agentic-ai/renders/final_full_vi_9x16.mp4',
        'tiktok': 'projects/topic2-agentic-ai/renders/final_full_vi_9x16.mp4',
        'schedule': '12:00 PM',
    },
    {
        'id': 'topic3',
        'title': 'Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất',
        'description': 'Các phương pháp mới nhất để bảo vệ dữ liệu cá nhân và phòng chống tấn công mạng trong kỷ nguyên số. Hướng dẫn chi tiết cho người dùng và doanh nghiệp.',
        'yt_long': 'projects/topic3-cyber-defense/renders/final_full_vi_16x9.mp4',
        'yt_shorts': 'projects/topic3-cyber-defense/renders/final_reels_vi_9x16.mp4',
        'ig_reels': 'projects/topic3-cyber-defense/renders/final_reels_vi_9x16.mp4',
        'fb_reels': 'projects/topic3-cyber-defense/renders/final_full_vi_9x16.mp4',
        'tiktok': 'projects/topic3-cyber-defense/renders/final_full_vi_9x16.mp4',
        'schedule': '20:00 PM',
    },
]

def publish_topic(topic):
    title = topic['title']
    print(f"\n{'='*60}")
    print(f"PUBLISHING: {title}")
    print(f"Schedule: {topic['schedule']}")
    print('='*60)

    results = {}

    # YouTube Long-form 16:9
    print("\n[1/5] YouTube Long-form (16:9)...")
    res = YoutubePublisher().execute({
        'video_path': topic['yt_long'],
        'title': title[:100],
        'description': topic['description'],
        'privacy_status': 'public',
        'category_id': '28',
    })
    results['youtube_long'] = res.success
    if res.error:
        print(f"  ERROR: {res.error}")

    # YouTube Shorts 9:16
    print("\n[2/5] YouTube Shorts (9:16)...")
    res = YoutubePublisher().execute({
        'video_path': topic['yt_shorts'],
        'title': f"{title} #Shorts"[:100],
        'description': topic['description'],
        'privacy_status': 'public',
        'category_id': '28',
    })
    results['youtube_shorts'] = res.success
    if res.error:
        print(f"  ERROR: {res.error}")

    # Instagram Reels 9:16
    print("\n[3/5] Instagram Reels (9:16)...")
    try:
        # Use TOKEN_INSTAGRAM or fall back to TOKEN_FACEBOOK
        res = MetaPublisher().execute({
            'video_path': topic['ig_reels'],
            'page_id': '17841434265610775',  # Using Direct IG Account ID
            'caption': f"{title} #TechNews #Vietnam #OpenMontage",
            'post_to_facebook': False,
            'post_to_instagram': True,
        })
        results['instagram'] = res.success
        if res.error:
            print(f"  ERROR: {res.error}")
    except Exception as e:
        print(f"  CRITICAL ERROR: {e}")
        results['instagram'] = False

    # Facebook and TikTok held by current publishing policy.
    results['facebook'] = 'held'
    results['tiktok'] = 'held'

    print(f"\n{'='*60}")
    print(f"COMPLETED: {title}")
    for platform, success in results.items():
        status = "OK" if success else "FAIL"
        print(f"  {platform}: {status}")
    print('='*60)

    return results

if __name__ == '__main__':
    print("Batch publisher is disabled; use scripts/publish_today.py for scheduled uploads.")
    raise SystemExit(1)
    all_results = {}
    for topic in TOPICS:
        all_results[topic['id']] = publish_topic(topic)

    print("\n\nFINAL SUMMARY:")
    print("="*60)
    for topic_id, results in all_results.items():
        print(f"\n{topic_id}:")
        for platform, success in results.items():
            status = "OK" if success else "FAIL"
            print(f"  {platform}: {status}")
