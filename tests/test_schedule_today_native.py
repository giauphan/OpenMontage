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


@pytest.fixture(autouse=True)
def clean_publish_env(monkeypatch):
    """Isolate tests from ambient environment variables."""
    for key in (
        "HOLD_PLATFORMS",
        "HOLD_IG",
        "HOLD_FB",
        "HOLD_TIKTOK",
        "HOLD_YTB",
        "ENABLED_PLATFORMS",
        "ENABLE_PLATFORMS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENABLE_PLATFORMS", "youtube,instagram,tiktok,facebook")

def test_schedule_today_native_prevents_duplicate_uploads_and_avoids_facebook(tmp_path: Path, monkeypatch):
    from scripts.schedule_today_native import main

    projects_dir = tmp_path / "projects"
    config_dir = tmp_path / "config"
    projects_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    
    today = "2099-01-01"
    
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
        assert "tiktok" in claimed_platforms
        assert "facebook" in claimed_platforms


def test_passed_slot_cutoff_is_skipped_gracefully_without_exit_failure(tmp_path: Path, monkeypatch, capsys):
    from scripts.schedule_today_native import main

    projects_dir = tmp_path / "projects"
    config_dir = tmp_path / "config"
    projects_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    today = "2000-01-01"

    # Slot set to 00:01 UTC (in the past if running any time after 00:21 UTC, or guaranteed past by mocking publish_time)
    (config_dir / "publish_schedule.json").write_text(json.dumps({
        "timezone": "UTC",
        "youtube": {"account": "yt-account"},
        "instagram": {"account_id": "ig-account"},
        "active_projects": [
            {"project_id": "cand_passed", "publish_date": today, "publish_time": "00:01"}
        ]
    }))

    cand_dir = projects_dir / "cand_passed"
    cand_dir.mkdir()
    write_reviewed_news_evidence(cand_dir)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    (cand_dir / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_passed",
        "title": "Tin tức #tintuc",
        "description": "Bản tin #tintuc",
        "status": "generated",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
    }))
    (cand_dir / "validation_status.json").write_text(json.dumps([
        {"status": "PASS", "strict_quality_pass": True}
    ]))

    class DummyStore:
        def claim(self, **kwargs):
            return "k1", True, {}

    mock_yt_pub = MagicMock()

    with patch("scripts.schedule_today_native.ROOT", tmp_path), \
         patch("scripts.schedule_today_native.PublishStore", DummyStore), \
         patch("scripts.schedule_today_native.load_config", return_value=json.loads((config_dir / "publish_schedule.json").read_text())), \
         patch("scripts.schedule_today_native.YoutubePublisher", return_value=mock_yt_pub), \
         patch("sys.argv", ["schedule_today_native.py", "--date", today]):

        exit_code = main()
        # Must exit 0 instead of aborting the pipeline
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "slot cutoff passed" in captured.out
        assert "SKIPPED" in captured.out
        # YoutubePublisher must not be invoked for a passed slot
        assert mock_yt_pub.execute.call_count == 0


def test_publish_config_respects_openmontage_env_vars(tmp_path: Path, monkeypatch):
    from scripts import publish_config
    custom_cfg = tmp_path / "custom_schedule.json"
    custom_cfg.write_text(json.dumps({
        "timezone": "UTC",
        "slots": {"yt_slots_wib": ["10:00"]},
        "meta": {"page_id": "custom_page"},
        "youtube": {"account": "custom_yt"},
    }), encoding="utf-8")

    monkeypatch.delenv("FB_PAGE_ID", raising=False)
    monkeypatch.delenv("YOUTUBE_ACCOUNT", raising=False)
    monkeypatch.delenv("PUBLISH_TZ", raising=False)
    monkeypatch.setenv("OPENMONTAGE_CONFIG", str(custom_cfg))
    # Re-evaluate CONFIG_PATH with env set
    cfg_path = Path(os.environ.get("OPENMONTAGE_CONFIG") or publish_config.ROOT / "config" / "publish_schedule.json")
    assert cfg_path == custom_cfg

    monkeypatch.setattr(publish_config, "CONFIG_PATH", custom_cfg)
    loaded = publish_config.load_config()
    assert loaded["youtube"]["account"] == "custom_yt"
    assert loaded["meta"]["page_id"] == "custom_page"


def test_already_scheduled_projects_skip_gracefully_without_failing_news_gate(tmp_path: Path, monkeypatch, capsys):
    from scripts.schedule_today_native import main

    projects_dir = tmp_path / "projects"
    config_dir = tmp_path / "config"
    projects_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    today = "2099-01-01"

    # Hermetic: pin enabled platforms to YouTube-only regardless of repo config.
    yt_only_cfg = tmp_path / "platforms_youtube_only.json"
    yt_only_cfg.write_text(json.dumps({"enabled_platforms": ["youtube"]}))
    monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", str(yt_only_cfg))

    (config_dir / "publish_schedule.json").write_text(json.dumps({
        "timezone": "UTC",
        "youtube": {"account": "yt-account"},
        "instagram": {"account_id": "ig-account"},
        "active_projects": [
            {"project_id": "cand_meta_scheduled", "publish_date": today, "publish_time": "14:15"},
            {"project_id": "cand_store_scheduled", "publish_date": today, "publish_time": "21:15"},
        ]
    }))

    # cand_meta_scheduled: metadata status is "scheduled", no news evidence
    cand1 = projects_dir / "cand_meta_scheduled"
    cand1.mkdir()
    (cand1 / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_meta_scheduled",
        "title": "Tin tức #tintuc",
        "description": "Bản tin #tintuc",
        "status": "scheduled",
    }))

    # cand_store_scheduled: metadata status is "generated", store says already scheduled, no news evidence
    cand2 = projects_dir / "cand_store_scheduled"
    cand2.mkdir()
    (cand2 / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_store_scheduled",
        "title": "Tin tức 2 #tintuc",
        "description": "Bản tin 2 #tintuc",
        "status": "generated",
    }))

    class DummyStore:
        def get(self, key):
            if "cand_store_scheduled" in key:
                return {"status": "scheduled", "scheduled_for": today, "video_url": "https://youtu.be/dummy123"}
            return None

    mock_yt_pub = MagicMock()

    with patch("scripts.schedule_today_native.ROOT", tmp_path), \
         patch("scripts.schedule_today_native.PublishStore", DummyStore), \
         patch("scripts.schedule_today_native.load_config", return_value=json.loads((config_dir / "publish_schedule.json").read_text())), \
         patch("scripts.schedule_today_native.YoutubePublisher", return_value=mock_yt_pub), \
         patch("sys.argv", ["schedule_today_native.py", "--date", today]):

        exit_code = main()
        # Must exit 0 and not fail due to news evidence gate
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "SKIPPED cand_meta_scheduled: already scheduled" in captured.out
        assert "ALREADY SCHEDULED cand_store_scheduled on youtube" in captured.out
        assert mock_yt_pub.execute.call_count == 0


