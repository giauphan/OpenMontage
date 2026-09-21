#!/usr/bin/env python3
import fcntl
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publish_config import load_config
from publish_manual_video import validate_project_quality
from tools.publishers.platform_routes import CUT_RENDER, FULL_RENDER, youtube_shorts_title
from tools.publish_store import PublishStore, existing_record_summary
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.youtube_publisher import YoutubePublisher

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "publish_state.lock"
_CFG = load_config()
LOCAL_TZ = ZoneInfo(_CFG["timezone"])
IG_ACCOUNT_ID = _CFG["meta"]["ig_account_id"]
PLATFORM_ACCOUNTS = {
    "youtube": _CFG["youtube"]["account"],
    "instagram": IG_ACCOUNT_ID,
}

JOBS = {
    "topic1-short": {
        "topic": "topic1",
        "kind": "short",
        "platform": "youtube",
        "title": "Cuộc Chiến Chống AI Slop 2026 #Shorts",
        "description": "YouTube vừa xóa 35 triệu tài khoản bot trong một đợt quét tự động lớn.",
                "path": f"projects/newsnow-2026-08-09/{CUT_RENDER}",
    },
    "topic1-instagram": {
        "topic": "topic1",
        "kind": "reels",
        "platform": "instagram",
        "title": "Cuộc Chiến Chống AI Slop 2026",
        "description": "Cuộc chiến chống AI slop 2026.",
                "path": f"projects/newsnow-2026-08-09/{FULL_RENDER}",
    },
    "topic2-short": {
        "topic": "topic2",
        "kind": "short",
        "platform": "youtube",
        "title": "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026 #Shorts",
        "description": "Agentic AI đang thay đổi cách doanh nghiệp vận hành.",
                "path": f"projects/topic2-agentic-ai/{CUT_RENDER}",
    },
    "topic2-instagram": {
        "topic": "topic2",
        "kind": "reels",
        "platform": "instagram",
        "title": "Kỷ Nguyên Agentic AI: Khi AI Tự Động Hóa Toàn Bộ Workflow 2026",
        "description": "Kỷ nguyên Agentic AI 2026.",
                "path": f"projects/topic2-agentic-ai/{FULL_RENDER}",
    },
    "topic3-short": {
        "topic": "topic3",
        "kind": "short",
        "platform": "youtube",
        "title": "Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất #Shorts",
        "description": "Các phương pháp mới nhất để bảo vệ dữ liệu cá nhân trong kỷ nguyên số.",
                "path": f"projects/topic3-cyber-defense/{CUT_RENDER}",
    },
    "topic3-instagram": {
        "topic": "topic3",
        "kind": "reels",
        "platform": "instagram",
        "title": "Bảo Vệ Dữ Liệu Cá Nhân 2026: Giải Pháp An Ninh Mạng Mới Nhất",
        "description": "Bảo vệ dữ liệu cá nhân 2026.",
                "path": f"projects/topic3-cyber-defense/{FULL_RENDER}",
    },
}


def publish(job):
    path = ROOT / job["path"]
    if not path.is_file():
        raise FileNotFoundError(path)
    if job["platform"] == "youtube":
        return YoutubePublisher().execute({
            "video_path": str(path),
            "title": youtube_shorts_title(job["title"]),
            "description": job["description"],
            "privacy_status": "unlisted",
            "category_id": "28",
        })
    return MetaPublisher().execute({
        "video_path": str(path),
        "page_id": IG_ACCOUNT_ID,
        "caption": f'{job["title"]} #TechNews #Vietnam #OpenMontage',
        "post_to_facebook": False,
        "post_to_instagram": True,
    })


def run(job_name):
    if job_name not in JOBS:
        raise SystemExit(f"Unknown job: {job_name}")
    job = JOBS[job_name]
    asset_path = (ROOT / job["path"]).resolve()
    projects_root = (ROOT / "projects").resolve()
    try:
        project_dir = projects_root / asset_path.relative_to(projects_root).parts[0]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{job_name}: asset is not mapped to a canonical project") from exc
    if not (project_dir / "publish_metadata.json").is_file():
        raise ValueError(f"{job_name}: canonical project has no publish_metadata.json")
    validate_project_quality(project_dir)
    now = datetime.now(LOCAL_TZ)
    date = now.date().isoformat()
    lock_file = LOCK_PATH.open("a+")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    try:
        store = PublishStore()
        if not asset_path.is_file():
            raise FileNotFoundError(asset_path)
        key, claimed, existing = store.claim(
            date=date,
            topic=job["topic"],
            platform=job["platform"],
            account=PLATFORM_ACCOUNTS[job["platform"]],
            kind=job["kind"],
            status="uploading",
            job=job_name,
            title=job["title"],
            asset_path=asset_path,
        )
        if not claimed:
            print(f"SKIP {date} {job_name}: {existing_record_summary(existing)}")
            return
        try:
            result = publish(job)
            if not result.success:
                raise RuntimeError(result.error or f"{job_name} failed")
            data = result.data or {}
            store.mark_published(
                key,
                video_id=data.get("video_id"),
                video_url=data.get("video_url"),
                platform_id=data.get("instagram_media_id"),
                published_at=now.isoformat(),
            )
            print(f"OK {date} {job_name} {data.get('video_url') or data.get('instagram_media_id') or ''}")
        except Exception as exc:
            store.mark_failed(key, str(exc))
            raise
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {Path(sys.argv[0]).name} JOB; jobs: {', '.join(JOBS)}")
    run(sys.argv[1])
