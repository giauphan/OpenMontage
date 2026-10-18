"""Contract tests for pipeline platform enable/disable flags and configs (ytb, ig, fb, tiktok).

Tests the ability to restrict publishing and post-publish cleanup to enabled platforms via:
- Config file: config/publish_platforms.json (or OPENMONTAGE_PLATFORMS_CONFIG)
- Environment variable list: ENABLED_PLATFORMS, ACTIVE_PLATFORMS, PUBLISH_PLATFORMS
- Individual env flags: ENABLE_YTB, ENABLE_YT, ENABLE_YOUTUBE, ENABLE_IG, etc.
- CLI arguments: --enabled-platforms, --enable-platform
- Integration: When only YouTube (ytb) is enabled, publishing to YouTube verifies canonical
  status, narrows required routes to YouTube, and deletes project folders via deactivate_project.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_config import (
    canonical_platform_name,
    get_enabled_platforms,
    is_platform_enabled,
    parse_platform_list,
)
from scripts.publish_manual_video import (
    canonical_platform_records_published,
    get_required_routes_for_project,
    publish_batch,
)
from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
from scripts.publish_active_projects import deactivate_project
from tools.publish_store import file_sha256, publish_key


def test_get_enabled_platforms_none_by_default(monkeypatch):
    """When no source is configured, returns None (all platforms permitted)."""
    monkeypatch.delenv("ENABLED_PLATFORMS", raising=False)
    monkeypatch.delenv("ACTIVE_PLATFORMS", raising=False)
    monkeypatch.delenv("PUBLISH_PLATFORMS", raising=False)
    monkeypatch.delenv("ENABLE_YTB", raising=False)
    monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", "/nonexistent/platforms.json")

    assert get_enabled_platforms() is None
    assert is_platform_enabled("youtube") is True
    assert is_platform_enabled("instagram") is True


def test_get_enabled_platforms_env_lists(monkeypatch):
    """Verify ENABLED_PLATFORMS, ACTIVE_PLATFORMS, and PUBLISH_PLATFORMS env lists."""
    monkeypatch.setenv("ENABLED_PLATFORMS", "ytb")
    assert get_enabled_platforms() == {"youtube"}
    assert is_platform_enabled("youtube") is True
    assert is_platform_enabled("ytb") is True
    assert is_platform_enabled("instagram") is False
    assert is_platform_enabled("ig") is False

    monkeypatch.delenv("ENABLED_PLATFORMS")
    monkeypatch.setenv("ACTIVE_PLATFORMS", "ytb,ig")
    assert get_enabled_platforms() == {"youtube", "instagram"}
    assert is_platform_enabled("youtube") is True
    assert is_platform_enabled("instagram") is True
    assert is_platform_enabled("facebook") is False

    monkeypatch.delenv("ACTIVE_PLATFORMS")
    monkeypatch.setenv("PUBLISH_PLATFORMS", "tiktok fb")
    assert get_enabled_platforms() == {"tiktok", "facebook"}


def test_get_enabled_platforms_boolean_flags(monkeypatch):
    """Verify individual boolean flags: ENABLE_YTB, ENABLE_IG, etc."""
    monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", "/nonexistent/platforms.json")
    monkeypatch.delenv("ENABLED_PLATFORMS", raising=False)
    monkeypatch.delenv("ACTIVE_PLATFORMS", raising=False)
    monkeypatch.delenv("PUBLISH_PLATFORMS", raising=False)

    monkeypatch.setenv("ENABLE_YTB", "1")
    assert get_enabled_platforms() == {"youtube"}
    assert is_platform_enabled("youtube") is True
    assert is_platform_enabled("instagram") is False

    monkeypatch.setenv("ENABLE_IG", "true")
    assert get_enabled_platforms() == {"youtube", "instagram"}


def test_get_enabled_platforms_config_file(tmp_path: Path, monkeypatch):
    """Verify loading from dedicated config file (config/publish_platforms.json)."""
    cfg_file = tmp_path / "publish_platforms.json"
    cfg_file.write_text(json.dumps({"enabled_platforms": ["ytb"]}), encoding="utf-8")
    monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", str(cfg_file))
    monkeypatch.delenv("ENABLED_PLATFORMS", raising=False)

    enabled = get_enabled_platforms()
    assert enabled == {"youtube"}
    assert is_platform_enabled("youtube") is True
    assert is_platform_enabled("instagram") is False


def test_publish_platforms_example_file(monkeypatch):
    """Verify that config/publish_platforms.example.json is valid and loadable."""
    example_path = ROOT / "config" / "publish_platforms.example.json"
    assert example_path.is_file()

    # Verify JSON syntax and metadata
    data = json.loads(example_path.read_text(encoding="utf-8"))
    assert "enabled_platforms" in data
    assert "_supported_aliases" in data

    # Test loading via OPENMONTAGE_PLATFORMS_CONFIG
    monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", str(example_path))
    monkeypatch.delenv("ENABLED_PLATFORMS", raising=False)
    monkeypatch.delenv("ACTIVE_PLATFORMS", raising=False)
    monkeypatch.delenv("PUBLISH_PLATFORMS", raising=False)

    enabled = get_enabled_platforms()
    assert enabled == {"youtube"}
    assert is_platform_enabled("youtube") is True
    assert is_platform_enabled("instagram") is False


def test_get_enabled_platforms_schedule_dict():
    """Verify loading from schedule config dictionary."""
    cfg = {"enabled_platforms": ["youtube"]}
    enabled = get_enabled_platforms(cfg=cfg)
    assert enabled == {"youtube"}


def test_is_platform_enabled_respects_hold(monkeypatch):
    """A platform that is enabled but held must report as not enabled (held takes precedence)."""
    monkeypatch.setenv("ENABLED_PLATFORMS", "youtube,instagram")
    monkeypatch.setenv("HOLD_PLATFORMS", "youtube")

    assert is_platform_enabled("youtube") is False
    assert is_platform_enabled("instagram") is True


def test_get_required_routes_filtered_when_only_ytb_enabled(monkeypatch):
    """When only ytb is enabled, get_required_routes_for_project only requires YouTube."""
    metadata = {
        "id": "cand_yt_only_routes",
        "title": "Title",
        "description": "Desc",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }
    monkeypatch.setenv("ENABLED_PLATFORMS", "ytb")
    monkeypatch.setenv("FACEBOOK_PUBLISH_ENABLED", "1")

    routes = get_required_routes_for_project("cand_yt_only_routes", metadata=metadata)
    assert routes == [("youtube", "short")]

    # ignore_disabled=True returns all candidate routes
    all_routes = get_required_routes_for_project("cand_yt_only_routes", metadata=metadata, ignore_disabled=True)
    assert ("youtube", "short") in all_routes
    assert ("instagram", "reels") in all_routes


def test_cleanup_eligibility_when_only_youtube_enabled(tmp_path: Path, monkeypatch):
    """When only YouTube is enabled, successful YouTube publication authorizes cleanup."""
    pdir = tmp_path / "projects" / "cand_yt_cleanup"
    pdir.mkdir(parents=True)
    renders = pdir / "renders"
    renders.mkdir()
    reel_video = renders / "final_reels_vi_9x16.mp4"
    reel_video.write_bytes(b"sample_reel_bytes_12345")
    video_hash = file_sha256(reel_video)

    metadata = {
        "id": "cand_yt_cleanup",
        "publish_date": "2026-10-18",
        "title": "Title",
        "description": "Desc",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
    }
    (pdir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    class StoreWithYouTubeOnly:
        def __init__(self):
            self.records = {
                publish_key("2026-10-18", "cand_yt_cleanup", "youtube", "short"): {
                    "status": "published",
                    "media_sha256": video_hash,
                    "remote_status": {"privacy_status": "public", "upload_status": "processed"},
                }
            }
        def get(self, key):
            return self.records.get(key)

    monkeypatch.setenv("ENABLED_PLATFORMS", "ytb")

    eligible, reason, meta = is_project_eligible_for_cleanup(
        "cand_yt_cleanup",
        project_dir=pdir,
        store=StoreWithYouTubeOnly(),
        date="2026-10-18",
        root=tmp_path,
    )
    assert eligible is True
    assert reason in ("eligible_for_cleanup", "all_required_destinations_verified_published")
    assert meta["id"] == "cand_yt_cleanup"


def test_deactivate_project_deletes_folder_when_only_ytb_enabled(tmp_path: Path, monkeypatch):
    """Verify deactivate_project deletes the project folder when YouTube is published and only ytb is enabled."""
    config_file = tmp_path / "publish_schedule.json"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True)
    project_id = "cand_yt_deactivate"
    target_project_dir = projects_dir / project_id
    target_project_dir.mkdir()

    renders = target_project_dir / "renders"
    renders.mkdir()
    reel_video = renders / "final_reels_vi_9x16.mp4"
    reel_video.write_bytes(b"sample_reel_bytes_deactivate")
    video_hash = file_sha256(reel_video)

    metadata = {
        "id": project_id,
        "publish_date": "2026-10-18",
        "title": "Title",
        "description": "Desc",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
    }
    (target_project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    schedule_data = {
        "active_projects": [
            {"project_id": project_id, "publish_date": "2026-10-18", "publish_time": "14:15"},
            {"project_id": "cand_other", "publish_date": "2026-10-18", "publish_time": "21:15"},
        ]
    }
    config_file.write_text(json.dumps(schedule_data, indent=2), encoding="utf-8")

    import scripts.publish_active_projects as pap
    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setenv("ENABLED_PLATFORMS", "ytb")

    class StoreYT:
        def __init__(self):
            self.records = {
                publish_key("2026-10-18", project_id, "youtube", "short"): {
                    "status": "published",
                    "media_sha256": video_hash,
                    "remote_status": {"privacy_status": "public", "upload_status": "processed"},
                }
            }
        def get(self, key):
            return self.records.get(key)

    assert target_project_dir.exists()
    ok = deactivate_project(project_id, store=StoreYT(), date="2026-10-18", project_dir=target_project_dir)
    assert ok is True
    # Folder must be deleted from disk
    assert not target_project_dir.exists()

    # Must be removed from schedule active_projects
    updated = json.loads(config_file.read_text(encoding="utf-8"))
    active_ids = [p["project_id"] for p in updated.get("active_projects", [])]
    assert project_id not in active_ids
    assert "cand_other" in active_ids


def test_publish_manual_video_e2e_deletes_folder_when_only_ytb_enabled(tmp_path: Path, monkeypatch):
    """E2E test: when only ytb is enabled, publish_manual_video.py publishes to YouTube,
    verifies canonical status, and deletes the project directory upon completion.
    """
    from tests.test_publish_manual_video import _setup_valid_pipeline_project
    import scripts.publish_manual_video as pmv
    import scripts.publish_active_projects as pap

    project_dir, metadata, video_sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    metadata["publish_date"] = "2026-09-30"
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    # Set up schedule config
    config_file = tmp_path / "config" / "publish_schedule.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    schedule_data = {
        "timezone": "UTC",
        "youtube": {"account": "dummy_yt"},
        "active_projects": [
            {"project_id": metadata["id"], "publish_date": "2026-09-30", "publish_time": "09:15"},
        ],
    }
    config_file.write_text(json.dumps(schedule_data, indent=2), encoding="utf-8")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)
    monkeypatch.setenv("ENABLED_PLATFORMS", "ytb")

    # In-memory store that tracks claims, mark_published, etc.
    class InMemoryStore:
        def __init__(self):
            self.records = {}
        def claim(self, *, date, topic, platform, kind, asset_path=None, **kwargs):
            key = publish_key(date, topic, platform, kind)
            rec = {
                "date": date,
                "topic": topic,
                "platform": platform,
                "kind": kind,
                "status": "scheduling",
                "media_sha256": file_sha256(asset_path) if asset_path else None,
            }
            self.records[key] = rec
            return key, True, rec
        def get(self, key):
            return self.records.get(key)
        def mark_published(self, key, **kwargs):
            rec = self.records.get(key, {})
            rec["status"] = "published"
            rec.update(kwargs)
            self.records[key] = rec
            return rec
        def mark_scheduled(self, key, **kwargs):
            rec = self.records.get(key, {})
            rec["status"] = "scheduled"
            rec.update(kwargs)
            self.records[key] = rec
            return rec

    store_instance = InMemoryStore()

    test_args = ["publish_manual_video.py", str(project_dir), "--date", "2026-09-30"]

    with patch("sys.argv", test_args), \
         patch("scripts.publish_manual_video.PublishStore", return_value=store_instance), \
         patch("scripts.publish_manual_video.enforce_release_preflight"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.validate_video", return_value=[]), \
         patch("scripts.publish_manual_video.validate_vietnamese_narration", return_value=[]), \
         patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt_pmv, \
         patch("tools.publishers.youtube_publisher.YoutubePublisher") as mock_yt_cls, \
         patch("scripts.publish_manual_video.YT_ACCOUNT", "dummy_yt"):

        mock_yt = MagicMock()
        mock_yt.execute.return_value = MagicMock(
            success=True,
            data={"video_id": "yt_published_999", "video_url": "https://youtu.be/yt_published_999"},
        )
        mock_yt.check_video_published.return_value = {
            "status": "found",
            "privacy_status": "public",
            "upload_status": "processed",
        }
        mock_yt_pmv.return_value = mock_yt
        mock_yt_cls.return_value = mock_yt

        assert project_dir.exists()
        exit_code = pmv.main()
        assert exit_code == 0

        # Project folder must be deleted after publishing when only ytb is enabled
        assert not project_dir.exists()

        # Project must be removed from active_projects in publish_schedule.json
        updated = json.loads(config_file.read_text(encoding="utf-8"))
        active_ids = [p["project_id"] for p in updated.get("active_projects", [])]
        assert metadata["id"] not in active_ids

