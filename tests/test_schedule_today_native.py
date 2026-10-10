import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.fixtures.news_evidence import write_reviewed_news_evidence

ROOT = Path(__file__).resolve().parents[1]

def test_schedule_today_native_prevents_duplicate_uploads_and_avoids_facebook(tmp_path: Path, monkeypatch):
    from scripts.schedule_today_native import main

    projects_dir = tmp_path / "projects"
    config_dir = tmp_path / "config"
    projects_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    
    today = datetime.now(timezone.utc).strftime("%F")
    
    (config_dir / "publish_schedule.json").write_text(json.dumps({
        "timezone": "UTC",
        "youtube": {"account": "yt-account"},
        "instagram": {"account_id": "ig-account"},
        "active_projects": [
            {"project_id": "cand_A", "publish_date": today, "publish_time": "23:59"}
        ]
    }))
    
    cand_dir = projects_dir / "cand_A"
    cand_dir.mkdir()
    write_reviewed_news_evidence(cand_dir)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    (cand_dir / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_A",
        "title": "Tin tức công nghệ #tintuc #congnghe #ai",
        "description": "Bản tin công nghệ hàng ngày #tintuc #congnghe #ai",
        "status": "generated",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4"
    }))
    (cand_dir / "validation_status.json").write_text(json.dumps([
        {"status": "PASS", "strict_quality_pass": True}
    ]))
    renders_dir = cand_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_full_vi_9x16.mp4").touch()
    (renders_dir / "final_reels_vi_9x16.mp4").touch()

    # We will inspect claims here
    claimed_platforms = []

    class DummyStore:
        def claim(self, *, platform, **kwargs):
            claimed_platforms.append(platform)
            # Simulate already claimed by returning (key, claimed=False, existing_record)
            return "k1", False, {"status": "scheduled"}

    mock_yt_pub = MagicMock()

    with patch("scripts.schedule_today_native.ROOT", tmp_path), \
         patch("scripts.schedule_today_native.PublishStore", DummyStore), \
         patch("scripts.schedule_today_native.load_config", return_value=json.loads((config_dir / "publish_schedule.json").read_text())), \
         patch("scripts.schedule_today_native.YoutubePublisher", return_value=mock_yt_pub), \
         patch("sys.argv", ["schedule_today_native.py", "--date", today]):
        
        exit_code = main()
        assert exit_code == 0
        
        # Verify YT execution was skipped because yt_claimed was False
        assert mock_yt_pub.execute.call_count == 0
        
        # Verify platforms claimed
        assert "youtube" in claimed_platforms
        assert "instagram" in claimed_platforms
        
        # Verify facebook was never checked
        assert "facebook" not in claimed_platforms

