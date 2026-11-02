"""Route, CLI, and platform-specific tests for publish_manual_video."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.test_publish_manual_video import _setup_valid_pipeline_project


@pytest.fixture(autouse=True)
def clean_publish_env(monkeypatch):
    """Ensure tests run isolated from ambient platform hold/enable environment."""
    for var in (
        "HOLD_PLATFORMS",
        "HOLD_PIPELINE",
        "HOLD_IG",
        "HOLD_INSTAGRAM",
        "HOLD_FB",
        "HOLD_FACEBOOK",
        "HOLD_TIKTOK",
        "HOLD_TT",
        "HOLD_YTB",
        "HOLD_YT",
        "HOLD_YOUTUBE",
    ):
        monkeypatch.delenv(var, raising=False)

    from tools.base_tool import ToolResult
    monkeypatch.setattr(
        "tools.publishers.tiktok_publisher.TiktokPublisher.execute",
        lambda self, inputs: ToolResult(
            success=True,
            data={"status": "published", "project_id": "mock_tt", "item_id": "mock_tt"},
        ),
    )
    monkeypatch.setattr(
        "tools.publishers.facebook_publisher.FacebookPublisher.execute",
        lambda self, inputs: ToolResult(
            success=True,
            data={"status": "published", "video_id": "mock_fb", "facebook_post_id": "mock_fb"},
        ),
    )
    monkeypatch.setattr(
        "tools.publishers.meta_publisher.MetaPublisher.execute",
        lambda self, inputs: ToolResult(
            success=True,
            data={"status": "published", "facebook_post_id": "mock_fb", "instagram_media_id": "mock_ig"},
        ),
    )


def test_publish_manual_video_cli_full_success_calls_deactivate_project(tmp_path: Path, monkeypatch):
    """F01: Verify that CLI completion in main() passes project_path to deactivate_project without NameError."""
    import scripts.publish_manual_video as pmv

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    fake_store = MagicMock()
    fake_store.claim.return_value = ("test_key", True, {})
    test_args = ["publish_manual_video.py", str(project_dir), "--date", "2026-09-30"]

    with patch("sys.argv", test_args), \
         patch("scripts.publish_manual_video.PublishStore", return_value=fake_store), \
         patch("scripts.publish_manual_video.enforce_release_preflight"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt, \
         patch("scripts.publish_manual_video.TiktokPublisher"), \
         patch("scripts.publish_manual_video.canonical_platform_records_published", return_value=True) as mock_canon, \
         patch("scripts.publish_active_projects.deactivate_project", return_value=True) as mock_deact:

        mock_yt.return_value.execute.return_value = MagicMock(
            success=True, data={"video_id": "yt_123", "video_url": "https://youtu.be/yt_123"}
        )

        exit_code = pmv.main()
        assert exit_code == 0
        assert mock_canon.call_count == 1
        assert mock_canon.call_args[1]["project_dir"] == project_dir
        assert mock_deact.call_count == 1
        assert mock_deact.call_args[1]["project_dir"] == project_dir


def test_publish_manual_video_cli_partial_success_retains_project(tmp_path: Path, monkeypatch):
    """F01 & F09: Partial platform success returns 0 and retains project without calling deactivate_project."""
    import scripts.publish_manual_video as pmv

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    fake_store = MagicMock()
    fake_store.claim.return_value = ("test_key", True, {})
    test_args = ["publish_manual_video.py", str(project_dir), "--date", "2026-09-30"]

    with patch("sys.argv", test_args), \
         patch("scripts.publish_manual_video.PublishStore", return_value=fake_store), \
         patch("scripts.publish_manual_video.enforce_release_preflight"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt, \
         patch("scripts.publish_manual_video.TiktokPublisher"), \
         patch("scripts.publish_manual_video.canonical_platform_records_published", return_value=False) as mock_canon, \
         patch("scripts.publish_active_projects.deactivate_project") as mock_deact:

        mock_yt.return_value.execute.return_value = MagicMock(
            success=True, data={"video_id": "yt_123", "video_url": "https://youtu.be/yt_123"}
        )

        exit_code = pmv.main()
        assert exit_code == 0
        assert mock_canon.call_count == 1
        assert mock_deact.call_count == 0


def test_get_required_routes_not_narrowed_by_instagram_mode(tmp_path: Path, monkeypatch):
    """F03: INSTAGRAM_MODE=1 must not narrow project's required cleanup routes."""
    from scripts.publish_manual_video import get_required_routes_for_project

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("INSTAGRAM_MODE", "1")
    monkeypatch.setenv("FACEBOOK_PUBLISH_ENABLED", "1")
    monkeypatch.setenv("ENABLED_PLATFORMS", "youtube,instagram,facebook")

    routes = get_required_routes_for_project("cand_test", project_dir=project_dir, metadata=metadata)
    assert ("youtube", "short") in routes
    assert ("instagram", "reels") in routes


def test_resumable_instagram_reservation(tmp_path: Path, monkeypatch):
    """F08: Resumable ownership transition for pre-created reservation without remote ID."""
    from scripts.publish_manual_video import publish_batch

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    metadata["publish_date"] = "2026-09-30"

    class ResumableStore:
        def __init__(self):
            self.updated = []
            self.published = []
        def claim(self, **kwargs):
            return "ig_key", False, {"status": "scheduling"}
        def update(self, key, fields):
            self.updated.append((key, fields))
            return fields
        def mark_published(self, key, **kwargs):
            self.published.append((key, kwargs))

    store = ResumableStore()

    with patch("scripts.publish_manual_video.MetaPublisher") as mock_meta, \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.IG_ACCOUNT_ID", "dummy_ig"), \
         patch("scripts.publish_manual_video.FB_PAGE_ID", "dummy_fb"):

        mock_meta.return_value.execute.return_value = MagicMock(
            success=True, data={"instagram_media_id": "ig_media_999"}
        )

        results = publish_batch(metadata, project_dir, store, only_platform="instagram", strict=False)
        assert results["platforms"]["instagram/reels"]["status"] == "published"
        assert any(f.get("status") == "uploading" for _, f in store.updated)
        assert len(store.published) == 1
        assert store.published[0][1]["video_id"] == "ig_media_999"


def test_instagram_upload_records_published_immediately(tmp_path: Path, monkeypatch):
    """F08: Instagram uploads record published status immediately, not scheduled."""
    from scripts.publish_manual_video import publish_batch

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    metadata["publish_date"] = "2026-09-30"

    class FreshStore:
        def __init__(self):
            self.published = []
        def claim(self, **kwargs):
            return "ig_key", True, {}
        def mark_published(self, key, **kwargs):
            self.published.append((key, kwargs))

    store = FreshStore()

    with patch("scripts.publish_manual_video.MetaPublisher") as mock_meta, \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.IG_ACCOUNT_ID", "dummy_ig"), \
         patch("scripts.publish_manual_video.FB_PAGE_ID", "dummy_fb"):

        mock_meta.return_value.execute.return_value = MagicMock(
            success=True, data={"instagram_media_id": "ig_media_fresh"}
        )

        results = publish_batch(metadata, project_dir, store, only_platform="instagram", strict=False)
        assert results["platforms"]["instagram/reels"]["status"] == "published"
        assert len(store.published) == 1
        assert store.published[0][1]["video_id"] == "ig_media_fresh"


def test_enforce_release_preflight_approval_list(tmp_path: Path):
    """M19: enforce_release_preflight properly handles a list-formatted human_approval.json (selects last)."""
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    (project_dir / "approval.json").unlink()

    approvals = [
        {"approved": False, "status": "rejected", "media_sha256": "oldhash"},
        {"approved": True, "status": "approved", "media_sha256": "deadbeef" * 8},
    ]
    (project_dir / "human_approval.json").write_text(json.dumps(approvals), encoding="utf-8")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Media SHA-256 mismatch"):
            enforce_release_preflight(project_dir, metadata, strict=False)

    approvals.append({"approved": True, "status": "approved", "media_sha256": _sha})
    (project_dir / "human_approval.json").write_text(json.dumps(approvals), encoding="utf-8")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        enforce_release_preflight(project_dir, metadata, strict=False)


def test_enforce_release_preflight_unattended_news_project(tmp_path: Path):
    """Unattended news pipeline projects (research checkpoint only, no proposal/human approval) pass preflight."""
    from scripts.publish_manual_video import enforce_release_preflight
    from tests.contracts.conftest import sample_artifact

    project_dir = tmp_path / "projects" / "cand_news_unattended"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(json.dumps({
        "version": "1.0",
        "project_id": "cand_news_unattended",
        "title": "Tin tức AI hôm nay",
        "pipeline_type": "animated-explainer",
    }), encoding="utf-8")

    brief = sample_artifact("research_brief")
    cp_data = {
        "version": "1.0",
        "project_id": "cand_news_unattended",
        "pipeline_type": "animated-explainer",
        "stage": "research",
        "status": "completed",
        "timestamp": "2026-10-17T00:00:00Z",
        "artifacts": {"research_brief": brief},
    }
    (project_dir / "checkpoint_research.json").write_text(json.dumps(cp_data), encoding="utf-8")
    (project_dir / "artifacts").mkdir(parents=True)
    (project_dir / "artifacts" / "research_brief.json").write_text(json.dumps(brief), encoding="utf-8")

    renders = project_dir / "renders"
    renders.mkdir()
    (renders / "final_reels_vi_9x16.mp4").write_bytes(b"dummy-reels")
    (renders / "final_full_vi_9x16.mp4").write_bytes(b"dummy-full")

    metadata = {
        "id": "cand_news_unattended",
        "title": "Tin tức AI hôm nay",
        "description": "Chi tiết tin tức",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        enforce_release_preflight(project_dir, metadata, strict=False)


def _make_route_project(tmp_path: Path, pid: str, route_key: str, topic: str) -> tuple[Path, dict]:
    project_dir = tmp_path / "projects" / pid
    project_dir.mkdir(parents=True)
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_full_vi_9x16.mp4").touch()
    metadata = {
        "id": pid,
        "title": "Bản tin AI công nghệ mới #tintuc #ai",
        "description": "Chi tiết cập nhật mô hình #congnghe",
        route_key: "renders/final_full_vi_9x16.mp4",
        "topic": topic,
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return project_dir, metadata


class _RouteDummyStore:
    def __init__(self, key: str = "claim_key"):
        self.key = key
    def claim(self, *, platform, **kwargs):
        return self.key, True, None
    def mark_published(self, *args, **kwargs):
        return {}
    def mark_scheduled(self, *args, **kwargs):
        return {}
    def mark_failed(self, *args, **kwargs):
        return {}
    def unclaim(self, *args, **kwargs):
        pass


def test_publish_manual_video_tiktok_route_dry_run(tmp_path: Path):
    from scripts.publish_manual_video import publish_batch

    project_dir, metadata = _make_route_project(tmp_path, "cand_tiktok", "tiktok", "topic_tt")
    store = _RouteDummyStore("claim_key")

    with patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("lib.news_release_gate.require_news_evidence"):
        results = publish_batch(
            metadata, project_dir, store=store, dry_run=True, only_platform="tiktok", enforce_preflight=False
        )

    assert "tiktok/video" in results["platforms"]
    assert results["platforms"]["tiktok/video"]["status"] == "dry_run"


def test_publish_manual_video_tiktok_route_live(tmp_path: Path):
    from scripts.publish_manual_video import publish_batch
    from tools.base_tool import ToolResult

    project_dir, metadata = _make_route_project(tmp_path, "cand_tiktok_live", "tiktok", "topic_tt_live")
    metadata["title"] = "Ứng dụng AI mới nhất #tintuc #ai"
    store = _RouteDummyStore("claim_key_live")

    mock_tool_result = ToolResult(
        success=True,
        data={
            "status": "published",
            "project_id": "7702355712046828820",
            "item_id": "7702355712046828820",
            "video_url": "https://www.tiktok.com/video/7702355712046828820",
        },
    )

    with patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("lib.news_release_gate.require_news_evidence"), \
         patch("tools.publishers.tiktok_publisher.TiktokPublisher.execute", return_value=mock_tool_result) as mock_exec:
        results = publish_batch(
            metadata, project_dir, store=store, dry_run=False, only_platform="tiktok", enforce_preflight=False
        )

    assert mock_exec.call_count == 1
    call_args = mock_exec.call_args[0][0]
    assert "video_path" in call_args
    assert "Ứng dụng AI mới nhất" in call_args["caption"]
    assert results["platforms"]["tiktok/video"]["status"] == "published"
    assert results["platforms"]["tiktok/video"]["video_id"] == "7702355712046828820"


def test_publish_manual_video_facebook_route_live(tmp_path: Path):
    """Verify Facebook publishing route via FacebookPublisher / Toolcase Gateway on port 20129."""
    from scripts.publish_manual_video import publish_batch
    from tools.base_tool import ToolResult

    project_dir, metadata = _make_route_project(tmp_path, "cand_fb_live", "fb_video", "topic_fb_live")
    store = _RouteDummyStore("claim_fb_key_live")

    mock_tool_result = ToolResult(
        success=True,
        data={
            "status": "published",
            "video_id": "1089594350750481",
            "facebook_post_id": "1089594350750481",
            "target_id": "1435449429646177",
            "video_url": "https://facebook.com/1435449429646177/videos/1089594350750481",
        },
    )

    with patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("lib.news_release_gate.require_news_evidence"), \
         patch("tools.publishers.facebook_publisher.FacebookPublisher.execute", return_value=mock_tool_result) as mock_fb_exec:
        results = publish_batch(
            metadata, project_dir, store=store, dry_run=False, only_platform="facebook", enforce_preflight=False
        )

    assert mock_fb_exec.call_count == 1
    call_args = mock_fb_exec.call_args[0][0]
    assert "video_path" in call_args
    assert "Bản tin AI" in call_args["title"]
    assert call_args["enable_auto_translate"] is True
    assert call_args["publish_type"] == "REEL"
    assert results["platforms"]["facebook/reels"]["status"] == "published"
    assert results["platforms"]["facebook/reels"]["video_id"] == "1089594350750481"


def test_publish_manual_video_facebook_preflight_gateway_ready(tmp_path: Path):
    """Verify Facebook preflight passes when Toolcase Gateway (port 20129) is ready without TOKEN_FACEBOOK."""
    from scripts.publish_manual_video import publish_batch
    from tools.base_tool import ToolResult

    project_dir, metadata = _make_route_project(tmp_path, "cand_fb_preflight", "fb_video", "topic_fb_preflight")
    store = _RouteDummyStore("claim_fb_key_pf")

    mock_tool_result = ToolResult(
        success=True,
        data={
            "status": "published",
            "video_id": "999888777",
            "facebook_post_id": "999888777",
            "target_id": "1435449429646177",
            "video_url": "https://facebook.com/1435449429646177/videos/999888777",
        },
    )

    with patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("lib.news_release_gate.require_news_evidence"), \
         patch("tools.publishers.facebook_publisher.FacebookPublisher.check_readiness", return_value={"status": "enabled", "configured": True}), \
         patch("tools.publishers.facebook_publisher.FacebookPublisher.execute", return_value=mock_tool_result) as mock_fb_exec:
        results = publish_batch(
            metadata, project_dir, store=store, dry_run=False, only_platform="facebook", enforce_preflight=True
        )

    assert mock_fb_exec.call_count == 1
    assert results["platforms"]["facebook/reels"]["status"] == "published"
    assert results["platforms"]["facebook/reels"]["video_id"] == "999888777"
