import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.fixtures.news_evidence import write_reviewed_news_evidence

ROOT = Path(__file__).resolve().parents[1]

def test_publish_manual_video_skips_duplicates_and_avoids_facebook(tmp_path: Path, monkeypatch):
    from scripts.publish_manual_video import publish_batch
    
    project_dir = tmp_path / "projects" / "cand_A"
    project_dir.mkdir(parents=True)
    
    (project_dir / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_A",
        "title": "T",
        "description": "D",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
        "topic": "topic_abc"
    }))
    
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_full_vi_9x16.mp4").touch()
    (renders_dir / "final_reels_vi_9x16.mp4").touch()

    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "narration_vi_text.txt").write_text("Chào mọi người hôm nay chúng ta có tin tức mới.", encoding="utf-8")
    write_reviewed_news_evidence(project_dir)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    
    # Store that claims to have already scheduled / published everything
    class DummyStore:
        def __init__(self):
            self.claims = []
        def claim(self, *, platform, **kwargs):
            self.claims.append(platform)
            return "key123", False, {"status": "published"}
        def unclaim(self, *args, **kwargs):
            pass
            
    store = DummyStore()

    with patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt_pub_class, \
         patch("scripts.publish_manual_video.MetaPublisher") as mock_meta_pub_class, \
         patch("scripts.publish_manual_video.validate_video", return_value=[]), \
         patch("scripts.publish_manual_video.validate_vietnamese_narration", return_value=[]), \
         patch("scripts.publish_manual_video.FB_PAGE_ID", "dummy_fb"), \
         patch("scripts.publish_manual_video.IG_ACCOUNT_ID", "dummy_ig"), \
         patch("scripts.publish_manual_video.YT_ACCOUNT", "dummy_yt"), \
         patch("builtins.open", MagicMock(return_value=MagicMock())):
        
        # Test 1: By default, without MULTI_PLATFORM=1, only youtube is used
        metadata = json.loads((project_dir / "publish_metadata.json").read_text())
        results = publish_batch(metadata, project_dir, store)
        
        assert "youtube" in store.claims
        assert "instagram" not in store.claims
        assert "facebook" not in store.claims
        assert mock_yt_pub_class.return_value.execute.call_count == 0
        assert mock_meta_pub_class.return_value.execute.call_count == 0
        
        # Reset and mock MULTI_PLATFORM
        store.claims.clear()
        
        with patch.dict("os.environ", {"MULTI_PLATFORM": "1", "FACEBOOK_PUBLISH_ENABLED": "0"}):
            results = publish_batch(metadata, project_dir, store)
            
            # Since FB is disabled via env var, only YouTube and Instagram are claimed
            assert "youtube" in store.claims
            assert "instagram" in store.claims
            assert "facebook" not in store.claims
            
            # Execution is bounded by the claimed=False above
            assert mock_yt_pub_class.return_value.execute.call_count == 0
            assert mock_meta_pub_class.return_value.execute.call_count == 0


def _setup_valid_pipeline_project(tmp_path: Path):
    import hashlib
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir = tmp_path / "projects" / "cand_test"
    project_dir.mkdir(parents=True)

    # project.json
    (project_dir / "project.json").write_text(json.dumps({
        "version": "1.0",
        "project_id": "cand_test",
        "title": "Tòa án phán quyết rủi ro chuỗi cung ứng #tintuc #congnghe #ai",
        "pipeline_type": "animated-explainer",
    }))

    # Renders
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    video_bytes = b"real-video-bytes-for-sha256-calculation"
    video_sha = hashlib.sha256(video_bytes).hexdigest()
    video_file = renders_dir / "final_reels_vi_9x16.mp4"
    video_file.write_bytes(video_bytes)
    full_video = renders_dir / "final_full_vi_9x16.mp4"
    full_video.write_bytes(video_bytes)

    # Metadata
    metadata = {
        "id": "cand_test",
        "title": "Tòa án phán quyết rủi ro chuỗi cung ứng #tintuc #congnghe #ai",
        "description": "Chi tiết phán quyết chuỗi cung ứng #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
        "topic": "topic_test",
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    # Checkpoints and Artifacts
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "narration_vi_text.txt").write_text("Chào mọi người hôm nay có tin tức mới.", encoding="utf-8")
    write_reviewed_news_evidence(project_dir)

    from tests.contracts.test_phase0_contracts import sample_artifact
    stages_info = [
        ("research", "research_brief", False),
        ("proposal", "proposal_packet", True),
        ("script", "script", True),
        ("scene_plan", "scene_plan", True),
        ("assets", "asset_manifest", True),
        ("edit", "edit_decisions", False),
        ("compose", "render_report", False),
    ]
    for st, art_name, gated in stages_info:
        art_payload = sample_artifact(art_name)
        if art_name == "edit_decisions":
            art_payload["render_runtime"] = "remotion"
        cp_data = {
            "version": "1.0",
            "project_id": "cand_test",
            "pipeline_type": "animated-explainer",
            "stage": st,
            "status": "completed",
            "timestamp": "2026-09-27T06:00:00Z",
            "checkpoint_policy": "guided",
            "human_approval_required": gated,
            "human_approved": True if gated else False,
            "artifacts": {art_name: art_payload},
        }
        (project_dir / f"checkpoint_{st}.json").write_text(json.dumps(cp_data), encoding="utf-8")
        (artifacts_dir / f"{art_name}.json").write_text(json.dumps(art_payload), encoding="utf-8")

    (project_dir / "decision_log.json").write_text(json.dumps({"version": "1.0", "decisions": []}), encoding="utf-8")
    (artifacts_dir / "final_review.json").write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")

    # Approval
    approval_data = {
        "approved": True,
        "approved_media_sha256": video_sha,
        "approved_title": metadata["title"],
        "approved_description": metadata["description"],
        "target_accounts": {
            "youtube": "dummy_yt",
            "instagram": "dummy_ig",
            "facebook": "dummy_fb",
        },
    }
    (project_dir / "approval.json").write_text(json.dumps(approval_data), encoding="utf-8")

    # Validation status
    (project_dir / "validation_status.json").write_text(json.dumps({
        "strict_quality_pass": True,
        "inspected_artifact_hash": video_sha,
    }), encoding="utf-8")

    return project_dir, metadata, video_sha


def test_preflight_passes_with_valid_approvals_and_checkpoints(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    with patch("scripts.publish_manual_video.validate_project_quality"):
        enforce_release_preflight(project_dir, metadata, strict=False)


def test_preflight_blocks_when_checkpoint_missing(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    (project_dir / "checkpoint_script.json").unlink()

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Missing required stage checkpoint for 'script'"):
            enforce_release_preflight(project_dir, metadata, strict=False)


def test_preflight_blocks_when_gated_checkpoint_not_approved(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    assets_cp = json.loads((project_dir / "checkpoint_assets.json").read_text(encoding="utf-8"))
    assets_cp["human_approved"] = False
    (project_dir / "checkpoint_assets.json").write_text(json.dumps(assets_cp), encoding="utf-8")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Stage 'assets' requires human approval but human_approved is false"):
            enforce_release_preflight(project_dir, metadata, strict=False)


def test_preflight_blocks_when_required_artifact_missing(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    (project_dir / "artifacts" / "final_review.json").unlink()

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Missing required stage artifact 'final_review' for stage 'compose'"):
            enforce_release_preflight(project_dir, metadata, strict=False)


def test_preflight_blocks_when_human_approval_missing(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    (project_dir / "approval.json").unlink()

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Missing explicit human approval record"):
            enforce_release_preflight(project_dir, metadata, strict=False)


def test_preflight_blocks_on_modified_media_file(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    # Tamper with video content after approval
    (project_dir / "renders" / "final_reels_vi_9x16.mp4").write_bytes(b"tampered-modified-video-bytes")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Media SHA-256 mismatch"):
            enforce_release_preflight(project_dir, metadata, strict=False)


def test_preflight_blocks_on_stale_validation_review(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    (project_dir / "validation_status.json").write_text(json.dumps({
        "strict_quality_pass": True,
        "inspected_artifact_hash": "deadbeef" * 8,
    }), encoding="utf-8")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Stale validation review!"):
            enforce_release_preflight(project_dir, metadata, strict=False)


@pytest.mark.parametrize("latest_matches", [True, False], ids=["matching", "stale"])
@pytest.mark.parametrize("status_format", ["history", "legacy"])
def test_preflight_uses_latest_review_hashes(tmp_path: Path, latest_matches, status_format):
    from scripts.publish_manual_video import enforce_release_preflight
    from scripts.validation_status import ValidationStatusLogger

    project_dir, metadata, video_sha = _setup_valid_pipeline_project(tmp_path)
    stale_sha = "deadbeef" * 8
    latest_sha = video_sha if latest_matches else stale_sha
    status_file = project_dir / "validation_status.json"
    if status_format == "legacy":
        status_file.write_text(json.dumps({
            "strict_quality_pass": True,
            "inspected_artifact_hash": latest_sha,
        }), encoding="utf-8")
    else:
        status_file.unlink()
        logger = ValidationStatusLogger(project_dir)

        def log_review(project_id, hashes):
            logger.log_validation_result(
                project_id, "PASS", len(hashes), len(hashes), 0,
                details={"results": [
                    {"check_name": "Visual Quality", "passed": True,
                     "message": "PASS", "details": {"inspected_artifact_hash": sha}}
                    for sha in hashes
                ]},
            )

        # An older matching review must not rescue a stale latest review;
        # an older stale review must not invalidate a fresh one.
        log_review(project_dir.name, [stale_sha if latest_matches else video_sha])
        log_review(project_dir.name, [latest_sha])
        # Neither unrelated projects nor hashless technical checks erase the review.
        log_review("another_project", [video_sha if not latest_matches else stale_sha])
        log_review(project_dir.name, [])

    with patch("scripts.publish_manual_video.validate_project_quality") as quality:
        if latest_matches:
            enforce_release_preflight(project_dir, metadata, strict=True)
        else:
            with pytest.raises(RuntimeError, match="Stale validation review!"):
                enforce_release_preflight(project_dir, metadata, strict=True, force=True)
        quality.assert_called_once_with(project_dir, strict=True)


def test_preflight_history_supports_distinct_reviewed_media(tmp_path: Path):
    import hashlib
    from scripts.publish_manual_video import enforce_release_preflight
    from scripts.validation_status import ValidationStatusLogger

    project_dir, metadata, reels_sha = _setup_valid_pipeline_project(tmp_path)
    full_video = project_dir / metadata["fb_video"]
    full_video.write_bytes(b"distinct-full-video")
    full_sha = hashlib.sha256(full_video.read_bytes()).hexdigest()
    approval_file = project_dir / "approval.json"
    approval = json.loads(approval_file.read_text(encoding="utf-8"))
    approval["approved_media_hashes"] = [reels_sha, full_sha]
    approval_file.write_text(json.dumps(approval), encoding="utf-8")
    (project_dir / "validation_status.json").unlink()
    logger = ValidationStatusLogger(project_dir)
    logger.log_validation_result(project_dir.name, "PASS", 2, 2, 0, details={
        "results": [
            {"check_name": "Visual Quality", "passed": True, "message": "PASS",
             "details": {"inspected_artifact_hash": sha}}
            for sha in (full_sha, reels_sha)
        ],
    })

    with patch("scripts.publish_manual_video.validate_project_quality"):
        enforce_release_preflight(project_dir, metadata, strict=True)

    # Re-approval alone must not authorize media absent from the latest review.
    full_video.write_bytes(b"changed-full-video")
    approval["approved_media_hashes"] = [
        reels_sha, hashlib.sha256(full_video.read_bytes()).hexdigest(),
    ]
    approval_file.write_text(json.dumps(approval), encoding="utf-8")
    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Stale validation review!"):
            enforce_release_preflight(project_dir, metadata, strict=True)


@pytest.mark.parametrize("gate", ["quality", "approval", "approval_hash"])
def test_preflight_matching_history_does_not_bypass_gates(tmp_path: Path, gate):
    from scripts.publish_manual_video import enforce_release_preflight
    from scripts.validation_status import ValidationStatusLogger

    project_dir, metadata, video_sha = _setup_valid_pipeline_project(tmp_path)
    (project_dir / "validation_status.json").unlink()
    ValidationStatusLogger(project_dir).log_validation_result(
        project_dir.name, "PASS", 1, 1, 0, details={"results": [
            {"check_name": "Visual Quality", "passed": True, "message": "PASS",
             "details": {"inspected_artifact_hash": video_sha}},
        ]},
    )
    expected_error = "quality rejected"
    if gate == "approval":
        (project_dir / "approval.json").unlink()
        expected_error = "Missing explicit human approval record"
    elif gate == "approval_hash":
        approval_file = project_dir / "approval.json"
        approval = json.loads(approval_file.read_text(encoding="utf-8"))
        approval["approved_media_sha256"] = "deadbeef" * 8
        approval_file.write_text(json.dumps(approval), encoding="utf-8")
        expected_error = "Media SHA-256 mismatch"

    with patch("scripts.publish_manual_video.validate_project_quality") as quality:
        if gate == "quality":
            quality.side_effect = RuntimeError(expected_error)
        with pytest.raises(RuntimeError, match=expected_error):
            enforce_release_preflight(project_dir, metadata, strict=True, force=True)
        quality.assert_called_once_with(project_dir, strict=True)


def test_preflight_blocks_on_altered_post_title_or_description(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    altered_meta = dict(metadata)
    altered_meta["title"] = "Tiêu đề đã bị sửa đổi trái phép #Shorts"

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Post title has been altered since approval"):
            enforce_release_preflight(project_dir, altered_meta, strict=False)

    altered_meta2 = dict(metadata)
    altered_meta2["description"] = "Mô tả mới chưa được phê duyệt"
    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Post description has been altered since approval"):
            enforce_release_preflight(project_dir, altered_meta2, strict=False)


def test_preflight_blocks_on_target_account_mismatch(tmp_path: Path):
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    platforms = [{
        "platform": "youtube",
        "account": "unauthorized_account",
        "kind": "short",
        "video_path": "renders/final_reels_vi_9x16.mp4",
    }]

    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Target account mismatch for youtube"):
            enforce_release_preflight(project_dir, metadata, platforms=platforms, strict=False)


def test_force_flag_cannot_bypass_preflight_failure(tmp_path: Path, monkeypatch):
    from scripts.publish_manual_video import publish_batch

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    # Break checkpoint
    (project_dir / "checkpoint_script.json").unlink()

    store_mock = MagicMock()
    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Missing required stage checkpoint for 'script'"):
            # Passing force=True must not bypass preflight!
            publish_batch(metadata, project_dir, store_mock, force=True, strict=False)

    # Store claim must NEVER be called
    assert store_mock.claim.call_count == 0


def test_distinguish_scheduled_from_published_state(tmp_path: Path, monkeypatch):
    from scripts.publish_manual_video import publish_batch

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    metadata["publish_date"] = "2026-09-30"

    class ScheduledStore:
        def __init__(self):
            self.scheduled_calls = []
            self.published_calls = []
        def claim(self, **kwargs):
            return "test_key", True, {}
        def mark_scheduled(self, key, **kwargs):
            self.scheduled_calls.append((key, kwargs))
        def mark_published(self, key, **kwargs):
            self.published_calls.append((key, kwargs))

    store = ScheduledStore()

    with patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt, \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.YT_ACCOUNT", "dummy_yt"):
        
        mock_yt.return_value.execute.return_value = MagicMock(
            success=True,
            data={"video_id": "yt_sched_123", "video_url": "https://youtu.be/yt_sched_123"}
        )

        results = publish_batch(metadata, project_dir, store, only_platform="youtube", strict=False)

        assert results["platforms"]["youtube/short"]["status"] == "scheduled"
        assert len(store.scheduled_calls) == 1
        assert len(store.published_calls) == 0
        assert store.scheduled_calls[0][1]["video_id"] == "yt_sched_123"


def test_publish_manual_video_cli_full_success_calls_deactivate_project(tmp_path: Path, monkeypatch):
    """F01: Verify that CLI completion in main() passes project_path to deactivate_project without NameError."""
    import scripts.publish_manual_video as pmv

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    metadata["publish_time"] = "09:15"
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    fake_store = MagicMock()
    # claim succeeds
    fake_store.claim.return_value = ("test_key", True, {})

    test_args = ["publish_manual_video.py", str(project_dir), "--date", "2026-09-30"]

    with patch("sys.argv", test_args), \
         patch("scripts.publish_manual_video.PublishStore", return_value=fake_store), \
         patch("scripts.publish_manual_video.enforce_release_preflight"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.YoutubePublisher") as mock_yt, \
         patch("scripts.publish_manual_video.canonical_platform_records_published", return_value=True) as mock_canon, \
         patch("scripts.publish_active_projects.deactivate_project", return_value=True) as mock_deact:

        mock_yt.return_value.execute.return_value = MagicMock(
            success=True,
            data={"video_id": "yt_123", "video_url": "https://youtu.be/yt_123"}
        )

        exit_code = pmv.main()
        assert exit_code == 0
        # F01 check: verify canonical check and deactivate_project were called with project_dir=project_dir
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
         patch("scripts.publish_manual_video.canonical_platform_records_published", return_value=False) as mock_canon, \
         patch("scripts.publish_active_projects.deactivate_project") as mock_deact:

        mock_yt.return_value.execute.return_value = MagicMock(
            success=True,
            data={"video_id": "yt_123", "video_url": "https://youtu.be/yt_123"}
        )

        exit_code = pmv.main()
        assert exit_code == 0
        assert mock_canon.call_count == 1
        # deactivate_project MUST NOT be called on partial completion
        assert mock_deact.call_count == 0


def test_get_required_routes_not_narrowed_by_instagram_mode(tmp_path: Path, monkeypatch):
    """F03: INSTAGRAM_MODE=1 must not narrow project's required cleanup routes."""
    from scripts.publish_manual_video import get_required_routes_for_project

    project_dir, metadata, _sha = _setup_valid_pipeline_project(tmp_path)
    monkeypatch.setenv("INSTAGRAM_MODE", "1")
    monkeypatch.setenv("FACEBOOK_PUBLISH_ENABLED", "1")
    monkeypatch.setenv("ENABLED_PLATFORMS", "youtube,instagram,facebook")

    routes = get_required_routes_for_project("cand_test", project_dir=project_dir, metadata=metadata)
    # Must still require YouTube and Instagram (and Facebook), not just Instagram!
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
            # Simulate pre-created reservation from schedule_today_native.py
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
            success=True,
            data={"instagram_media_id": "ig_media_999"}
        )

        results = publish_batch(metadata, project_dir, store, only_platform="instagram", strict=False)

        assert results["platforms"]["instagram/reels"]["status"] == "published"
        # Verify status transitioned to uploading
        assert any(f.get("status") == "uploading" for _, f in store.updated)
        # Verify published record was stored
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
            success=True,
            data={"instagram_media_id": "ig_media_fresh"}
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

    # The latest list entry controls approval and remains hash-bound.
    with patch("scripts.publish_manual_video.validate_project_quality"):
        with pytest.raises(RuntimeError, match="Media SHA-256 mismatch"):
            enforce_release_preflight(project_dir, metadata, strict=False)

    # A newer, correctly bound approval succeeds.
    approvals.append({"approved": True, "status": "approved", "media_sha256": _sha})
    (project_dir / "human_approval.json").write_text(json.dumps(approvals), encoding="utf-8")

    with patch("scripts.publish_manual_video.validate_project_quality"):
        enforce_release_preflight(project_dir, metadata, strict=False)


def test_enforce_release_preflight_unattended_news_project(tmp_path: Path):
    """Unattended news pipeline projects (research checkpoint only, no proposal/human approval) pass preflight."""
    from scripts.publish_manual_video import enforce_release_preflight

    project_dir = tmp_path / "projects" / "cand_news_unattended"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(json.dumps({
        "version": "1.0",
        "project_id": "cand_news_unattended",
        "title": "Tin tức AI hôm nay",
        "pipeline_type": "animated-explainer",
    }), encoding="utf-8")

    from tests.contracts.test_phase0_contracts import sample_artifact
    brief = sample_artifact("research_brief")

    # Only checkpoint_research exists (unattended news pipeline contract)
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

    # Media and metadata
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
        # Should not raise missing checkpoint_proposal or missing approval
        enforce_release_preflight(project_dir, metadata, strict=False)


