"""Failing regression tests for PR-06 / PR-07: Centralized Publish Metadata & CI Contracts.

Tests:
1. Centralized typed metadata composer in tools/publishers/platform_routes.py
   (or tools/publishers/social_metadata.py) that produces consistent release payloads
   for YouTube, Instagram, Facebook, and TikTok.
2. Removes hard-coded tags like ['tintuc', 'congnghe', 'ai', 'tuonglai', 'vietnam']
   and enforces valid Vietnamese tags derived from content/topic.
3. Validates platform length limits, hashtag deduplication, #Shorts handling,
   and language constraints.
4. Identical source metadata produces identical YouTube payloads between
   schedule_today_native and publish_manual_video.
5. CI/Makefile contract checks ensuring make test-contracts and Docker cron E2E
   are wired properly and watchdog runs outside scheduler container.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.publishers.platform_routes import (
    PLATFORM_ROUTES,
    compose_release_metadata,
    validate_release_metadata,
    ReleaseMetadata,
)


def test_compose_release_metadata_valid():
    """Verify compose_release_metadata produces a structured ReleaseMetadata."""
    meta_dict = {
        "id": "cand_01",
        "title": "Trí tuệ nhân tạo phát triển vượt bậc tại Việt Nam #tintuc #congnghe #ai",
        "description": "Bản tin tổng hợp về tiến bộ công nghệ và AI mới nhất. #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
        "tiktok": "renders/final_full_vi_9x16.mp4",
        "tags": ["tintuc", "congnghe", "ai", "vietnam"],
    }
    rel_meta = compose_release_metadata(meta_dict)
    assert isinstance(rel_meta, ReleaseMetadata)
    assert rel_meta.youtube_payload["title"].endswith("#Shorts")
    assert rel_meta.youtube_payload["tags"] == ["tintuc", "congnghe", "ai", "vietnam"]
    assert "tintuc" in rel_meta.youtube_payload["tags"]
    # Verify no fixed hardcoded tags like 'tuonglai' injected if not in source
    assert "tuonglai" not in rel_meta.youtube_payload["tags"]


def test_compose_release_metadata_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="missing required field"):
        compose_release_metadata({"id": "cand_missing_title"})


def test_compose_release_metadata_rejects_invalid_language():
    meta_dict = {
        "id": "cand_en",
        "title": "Artificial Intelligence is booming in Silicon Valley #tintuc #congnghe #ai",
        "description": "Daily news update about artificial intelligence #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
    }
    with pytest.raises(ValueError, match="Vietnamese prose"):
        compose_release_metadata(meta_dict)


def test_compose_release_metadata_deduplicates_hashtags():
    meta_dict = {
        "id": "cand_dup",
        "title": "Tin tức công nghệ mới #tintuc #tintuc #congnghe #ai #ai",
        "description": "Chi tiết tin tức công nghệ hôm nay #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
    }
    rel_meta = compose_release_metadata(meta_dict)
    # Check that title doesn't duplicate hashtags
    words = rel_meta.youtube_payload["title"].split()
    assert words.count("#tintuc") == 1
    assert words.count("#ai") == 1


def test_identical_youtube_payload_between_native_and_manual(tmp_path: Path):
    """Ensure both entrypoints generate identical payloads given same metadata."""
    from scripts.schedule_today_native import build_youtube_payload as build_native_yt
    from scripts.publish_manual_video import build_youtube_payload as build_manual_yt

    meta_dict = {
        "id": "cand_test",
        "title": "Đột phá mới trong lĩnh vực bán dẫn #tintuc #congnghe #ai",
        "description": "Chi tiết về bước tiến sản xuất chip tại Việt Nam #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "tags": ["tintuc", "congnghe", "ai", "bandan"],
    }
    video_path = tmp_path / "renders/final_reels_vi_9x16.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.touch()

    native_payload = build_native_yt(meta_dict, video_path=str(video_path), publish_at="2026-10-13T09:15:00Z")
    manual_payload = build_manual_yt(meta_dict, video_path=str(video_path), publish_at="2026-10-13T09:15:00Z")

    assert native_payload == manual_payload
    assert native_payload["tags"] == ["tintuc", "congnghe", "ai", "bandan"]
    assert "tuonglai" not in native_payload["tags"]


def test_ci_workflow_and_makefile_contracts():
    """PR-07: Verify Makefile and CI workflow include test-contracts and Docker cron E2E."""
    ci_yml = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    makefile = Path(__file__).resolve().parents[1] / "Makefile"

    ci_content = ci_yml.read_text(encoding="utf-8")
    makefile_content = makefile.read_text(encoding="utf-8")

    # Makefile must have test-contracts and test-cron targets
    assert "test-contracts:" in makefile_content
    assert "test-cron:" in makefile_content or "docker-cron" in makefile_content

    # CI must invoke make test-contracts or make test with contracts
    assert "test-contracts" in ci_content


def test_docker_compose_and_watchdog_outside_scheduler():
    """PR-07: Verify docker-compose has fixed cron grouping and check_missed_runs watchdog is configured."""
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")

    # Bug in RC-02: (command -v cron || apt-get update && apt-get install) had flawed operator grouping
    # Check that cron installation syntax groups apt-get commands correctly
    assert "(command -v cron >/dev/null 2>&1 || (apt-get update && apt-get install -y cron jq))" in compose_text

    # Watchdog check: ensure check_missed_runs.py script exists and documents running OUTSIDE scheduler
    checker_script = Path(__file__).resolve().parents[1] / "scripts/check_missed_runs.py"
    assert checker_script.is_file()
    doc = checker_script.read_text(encoding="utf-8")
    assert "OUTSIDE the scheduler container" in doc

