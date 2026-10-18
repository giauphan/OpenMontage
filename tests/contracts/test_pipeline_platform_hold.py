"""Contract tests for pipeline platform hold flags (ig, fb, tiktok, ytb).

Tests the ability to pause, hold, or skip publishing to specific platforms via:
- Platform aliases: ig, fb, tiktok, ytb, and their canonical equivalents
- Environment variables: HOLD_PLATFORMS, HOLD_PIPELINE, HOLD_IG, HOLD_FB, HOLD_TIKTOK, HOLD_YTB
- CLI arguments: --hold-platform, --hold-platforms, --hold-ig, --hold-fb, --hold-tiktok, --hold-ytb
- Config file: held_platforms list in publish_schedule.json
- Impact on required cleanup routes and batch execution
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
    parse_platform_list,
    get_held_platforms,
    is_platform_held,
)
from scripts.publish_manual_video import (
    get_required_routes_for_project,
    publish_batch,
)
from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup


def test_canonical_platform_name_normalization():
    """Verify alias mapping for all supported platform variations."""
    # Instagram aliases
    assert canonical_platform_name("ig") == "instagram"
    assert canonical_platform_name("IG") == "instagram"
    assert canonical_platform_name("insta") == "instagram"
    assert canonical_platform_name("INSTAGRAM") == "instagram"
    assert canonical_platform_name("  ig  ") == "instagram"

    # Facebook aliases
    assert canonical_platform_name("fb") == "facebook"
    assert canonical_platform_name("FB") == "facebook"
    assert canonical_platform_name("face") == "facebook"
    assert canonical_platform_name("facebook") == "facebook"

    # TikTok aliases
    assert canonical_platform_name("tiktok") == "tiktok"
    assert canonical_platform_name("TikTok") == "tiktok"
    assert canonical_platform_name("TIKTOK") == "tiktok"
    assert canonical_platform_name("tt") == "tiktok"
    assert canonical_platform_name("TT") == "tiktok"

    # YouTube aliases
    assert canonical_platform_name("ytb") == "youtube"
    assert canonical_platform_name("YTB") == "youtube"
    assert canonical_platform_name("yt") == "youtube"
    assert canonical_platform_name("YT") == "youtube"
    assert canonical_platform_name("youtube") == "youtube"
    assert canonical_platform_name("YouTube") == "youtube"


def test_parse_platform_list_formats():
    """Verify parsing of comma, space, list, and mixed separators."""
    assert parse_platform_list("ig,fb,tiktok,ytb") == {"instagram", "facebook", "tiktok", "youtube"}
    assert parse_platform_list("ig; fb tiktok ytb") == {"instagram", "facebook", "tiktok", "youtube"}
    assert parse_platform_list(["ig", "fb,tt", "ytb"]) == {"instagram", "facebook", "tiktok", "youtube"}
    assert parse_platform_list("") == set()
    assert parse_platform_list(None) == set()


def test_get_held_platforms_env_hold_platforms(monkeypatch):
    """Verify HOLD_PLATFORMS environment variable with comma-separated values."""
    monkeypatch.setenv("HOLD_PLATFORMS", "ig,fb")
    held = get_held_platforms()
    assert "instagram" in held
    assert "facebook" in held
    assert "youtube" not in held
    assert "tiktok" not in held

    assert is_platform_held("ig") is True
    assert is_platform_held("instagram") is True
    assert is_platform_held("fb") is True
    assert is_platform_held("facebook") is True
    assert is_platform_held("ytb") is False
    assert is_platform_held("youtube") is False
    assert is_platform_held("tiktok") is False


def test_get_held_platforms_env_hold_pipeline(monkeypatch):
    """Verify HOLD_PIPELINE environment variable (matches user wording)."""
    monkeypatch.setenv("HOLD_PIPELINE", "tiktok,ytb")
    held = get_held_platforms()
    assert "tiktok" in held
    assert "youtube" in held
    assert "instagram" not in held

    assert is_platform_held("tiktok") is True
    assert is_platform_held("tt") is True
    assert is_platform_held("ytb") is True
    assert is_platform_held("yt") is True


def test_get_held_platforms_individual_env_flags(monkeypatch):
    """Verify individual boolean environment variables (HOLD_IG, HOLD_FB, etc.)."""
    monkeypatch.setenv("HOLD_IG", "1")
    monkeypatch.setenv("HOLD_FB", "true")
    monkeypatch.setenv("HOLD_TIKTOK", "yes")
    monkeypatch.setenv("HOLD_YTB", "on")

    held = get_held_platforms()
    assert held == {"instagram", "facebook", "tiktok", "youtube"}
    assert is_platform_held("instagram") is True
    assert is_platform_held("facebook") is True
    assert is_platform_held("tiktok") is True
    assert is_platform_held("youtube") is True


def test_get_held_platforms_config_file():
    """Verify held_platforms key inside schedule config dictionary."""
    cfg = {
        "held_platforms": ["ig", "tiktok"],
        "timezone": "Asia/Ho_Chi_Minh",
    }
    held = get_held_platforms(cfg=cfg)
    assert held == {"instagram", "tiktok"}
    assert is_platform_held("ig", cfg=cfg) is True
    assert is_platform_held("fb", cfg=cfg) is False


def test_get_held_platforms_cli_extra_precedence():
    """Verify extra_held passed from CLI takes effect."""
    held = get_held_platforms(extra_held=["ig", "fb"])
    assert held == {"instagram", "facebook"}
    assert is_platform_held("instagram", extra_held=["ig"]) is True


def test_get_required_routes_filters_held_platforms(tmp_path: Path, monkeypatch):
    """Verify that held platforms are excluded from required project cleanup routes."""
    meta = {
        "id": "cand_test_routes",
        "title": "Test Title",
        "description": "Test Desc",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }
    monkeypatch.setenv("FACEBOOK_PUBLISH_ENABLED", "1")

    # Baseline: no hold -> all routes required
    routes_all = get_required_routes_for_project("cand_test_routes", metadata=meta)
    assert ("youtube", "short") in routes_all
    assert ("instagram", "reels") in routes_all
    assert ("facebook", "reels") in routes_all

    # Hold Instagram: IG excluded, YT and FB remain
    monkeypatch.setenv("HOLD_PLATFORMS", "ig")
    routes_held_ig = get_required_routes_for_project("cand_test_routes", metadata=meta)
    assert ("youtube", "short") in routes_held_ig
    assert ("facebook", "reels") in routes_held_ig
    assert ("instagram", "reels") not in routes_held_ig

    # ignore_held=True overrides hold
    routes_ignored = get_required_routes_for_project("cand_test_routes", metadata=meta, ignore_held=True)
    assert ("instagram", "reels") in routes_ignored

    # Hold all: routes becomes empty
    monkeypatch.setenv("HOLD_PLATFORMS", "ig,fb,ytb")
    routes_held_all = get_required_routes_for_project("cand_test_routes", metadata=meta)
    assert routes_held_all == []


from tests.fixtures.news_evidence import write_reviewed_news_evidence


def test_cleanup_eligibility_when_all_held(tmp_path: Path, monkeypatch):
    """Verify that if all candidate routes are held, cleanup reports all_candidate_routes_currently_held."""
    pdir = tmp_path / "projects" / "cand_all_held"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(
        json.dumps({
            "id": "cand_all_held",
            "title": "Title",
            "description": "Desc",
            "yt_shorts": "renders/final_reels_vi_9x16.mp4",
            "ig_reels": "renders/final_reels_vi_9x16.mp4",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOLD_PLATFORMS", "ig,ytb")
    eligible, reason, _ = is_project_eligible_for_cleanup(
        "cand_all_held",
        project_dir=pdir,
        root=tmp_path,
    )
    assert eligible is False
    assert reason == "all_candidate_routes_currently_held"


def test_publish_batch_skips_held_only_platform(tmp_path: Path, monkeypatch):
    """Verify publish_batch with --only-platform ig exits cleanly when IG is held."""
    pdir = tmp_path / "projects" / "cand_publish_hold"
    pdir.mkdir(parents=True)
    (pdir / "artifacts").mkdir()
    (pdir / "artifacts" / "narration_vi_text.txt").write_text("Chào mọi người hôm nay có tin mới.", encoding="utf-8")
    write_reviewed_news_evidence(pdir)

    meta = {
        "id": "cand_publish_hold",
        "title": "Title",
        "description": "Desc",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
    }
    monkeypatch.setenv("HOLD_PLATFORMS", "ig")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "48")

    results = publish_batch(
        meta,
        project_dir=pdir,
        store=None,
        dry_run=True,
        only_platform="ig",
    )
    assert "instagram/reels" in results["platforms"]
    assert results["platforms"]["instagram/reels"]["status"] == "held"
    assert len(results["errors"]) == 0


def test_publish_batch_multi_platform_skips_held(tmp_path: Path, monkeypatch):
    """Verify in multi-platform mode, held platform is skipped while active platform proceeds."""
    pdir = tmp_path / "projects" / "cand_multi_hold"
    pdir.mkdir(parents=True)
    (pdir / "artifacts").mkdir()
    (pdir / "artifacts" / "narration_vi_text.txt").write_text("Chào mọi người hôm nay có tin mới.", encoding="utf-8")
    write_reviewed_news_evidence(pdir)

    (pdir / "renders").mkdir()
    video_file = pdir / "renders" / "final_reels_vi_9x16.mp4"
    video_file.write_bytes(b"dummy_video_bytes")

    meta = {
        "id": "cand_multi_hold",
        "title": "Title",
        "description": "Desc",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
    }
    monkeypatch.setenv("HOLD_PLATFORMS", "ig")
    monkeypatch.setenv("MULTI_PLATFORM", "1")
    monkeypatch.setenv("FACEBOOK_PUBLISH_ENABLED", "0")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "48")

    with patch("scripts.publish_manual_video.validate_video", return_value=[]), \
         patch("scripts.publish_manual_video.validate_vietnamese_narration", return_value=[]), \
         patch("scripts.publish_manual_video.FB_PAGE_ID", "dummy_fb"), \
         patch("scripts.publish_manual_video.IG_ACCOUNT_ID", "dummy_ig"), \
         patch("scripts.publish_manual_video.YT_ACCOUNT", "dummy_yt"):
        results = publish_batch(
            meta,
            project_dir=pdir,
            store=None,
            dry_run=True,
            enforce_preflight=False,
        )
    # Instagram should be marked held without running validation or upload
    assert results["platforms"]["instagram/reels"]["status"] == "held"
    # YouTube should be processed in dry_run
    assert results["platforms"]["youtube/short"]["status"] == "dry_run"
    assert len(results["errors"]) == 0


def test_publish_active_projects_slot_early_exit_on_hold(monkeypatch):
    """Verify that publish_active_projects exits 0 immediately when slot platform is held."""
    from scripts.publish_active_projects import main as pap_main

    monkeypatch.setenv("HOLD_PLATFORMS", "ig")
    test_args = ["publish_active_projects.py", "--slot", "09:15", "--only-platform", "instagram", "--dry-run"]
    with patch.object(sys, "argv", test_args):
        ret = pap_main()
    assert ret == 0


def test_schedule_today_native_skips_held_platforms(monkeypatch):
    """Verify that schedule_today_native skips YouTube and Instagram when held."""
    from scripts.schedule_today_native import main as stn_main

    monkeypatch.setenv("HOLD_PLATFORMS", "ig,ytb")
    mock_cfg = {
        "timezone": "Asia/Ho_Chi_Minh",
        "youtube": {"account": "primary"},
        "active_projects": [],
    }
    test_args = ["schedule_today_native.py", "--date", "2099-01-01"]
    with patch.object(sys, "argv", test_args), \
         patch("scripts.schedule_today_native.load_config", return_value=mock_cfg):
        ret = stn_main()
    assert ret == 0
