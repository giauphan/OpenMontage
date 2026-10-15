import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from tools.narration_text import (
    check_vietnamese_prose,
    prepare_narration,
    validate_vietnamese_narration,
    validate_display_text,
)
from scripts.validate_publish_metadata import validate_metadata
from scripts.validate_newsnow_director_artifacts import (
    _normalize_script_payload,
    validate_and_promote_director_artifacts,
)
from tools.publishers.meta_publisher import MetaPublisher
from tools.publishers.tiktok_publisher import TiktokPublisher
from tools.publishers.youtube_publisher import YoutubePublisher

def test_language_heuristics():
    # Good Vietnamese prose + tech words
    assert not check_vietnamese_prose("Dùng API cho phần mềm mới.")
    assert not check_vietnamese_prose("Công nghệ 2026")
    assert not check_vietnamese_prose("Phần mềm mới tăng 60 phần trăm, một phần nhờ AI.")
    assert not check_vietnamese_prose("CHOMPI là một bộ lấy mẫu độc đáo được thiết kế để tạo âm nhạc thú vị.")
    assert not check_vietnamese_prose("Dùng API, Docker và GPU để tăng tốc AI.")

    # Acceptance Criteria 1 & 2: Observed English headlines and mixed sentences
    chompi_err = check_vietnamese_prose("Tin tức công nghệ AI: CHOMPI is a magical sampler designed to make music fun.")
    assert chompi_err, "Should reject English prose"
    assert "Vietnamese prose" in chompi_err[0] or "English" in chompi_err[0]

    family_err = check_vietnamese_prose("Xin chào bạn, The last time my family was replaced by technology it was because of automation.")
    assert family_err, "Should reject English prose"

    # Only a hashtag doesn't make it Vietnamese prose
    tag_err = check_vietnamese_prose("CHOMPI is a magical sampler #tintuc #congnghe #ai")
    assert tag_err, "Should reject English prose even with valid hashtags"

    # Term-only identifier without sentence context
    term_err = check_vietnamese_prose("API")
    assert term_err, "Should reject single English term without Vietnamese context"

def test_ssml_narration_rejects_english_prose():
    with pytest.raises(ValueError, match="narration must be Vietnamese"):
        prepare_narration(
            "Xin chào bạn, The last time my family was replaced by technology.",
            use_ssml=True,
        )


def test_conflicting_script_fields_prefer_vietnamese_or_fail_closed():
    payload = {
        "title": "Tin tức công nghệ AI mới nhất",
        "sections": [{
            "id": "intro",
            "text": "The last time my family was replaced by technology.",
            "text_vi": "Công nghệ mới đang thay đổi cuộc sống.",
            "duration_seconds": 5,
        }],
    }
    normalized = _normalize_script_payload(payload)
    assert normalized is not None
    assert normalized["sections"][0]["text"] == payload["sections"][0]["text_vi"]


def test_invalid_fallback_claims_do_not_create_stale_script(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "research_brief.json").write_text(json.dumps({
        "title": "CHOMPI is a magical sampler",
        "data_points": [{"claim": "It makes music fun."}],
    }), encoding="utf-8")
    stale = artifacts / "script_vi.json"
    stale.write_text(json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ cũ",
        "sections": [{"text": "Nội dung cũ đã được phê duyệt.", "duration_seconds": 5}],
    }), encoding="utf-8")
    assert not validate_and_promote_director_artifacts(tmp_path, require_compositions=False)
    assert not stale.exists(), "invalid current source must not leave stale canonical artifact publishable"


def test_metadata_validation_blocks_conflicting_source_copy(tmp_path: Path):
    metadata = tmp_path / "publish_metadata.json"
    metadata.write_text(json.dumps({
        "id": "conflicting",
        "title": "Tin tức công nghệ AI mới nhất #tintuc #congnghe #ai",
        "description": "The last time my family was replaced by technology #tintuc #congnghe #ai",
    }), encoding="utf-8")
    success, errors = validate_metadata(metadata)
    assert not success
    assert any("description language error" in error for error in errors)


def test_social_publishers_reject_english_caption_before_network(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.touch()
    (tmp_path / "cookies.json").write_text(json.dumps({"cookies": []}), encoding="utf-8")
    with patch("tools.publishers.platform_routes.ensure_vertical"):
        meta_result = MetaPublisher().execute({
            "video_path": str(video),
            "caption": "The last time my family was replaced by technology",
            "page_id": "synthetic-page",
        })
        tiktok_result = TiktokPublisher().execute({
            "video_path": str(video),
            "caption": "The last time my family was replaced by technology",
            "cookie_path": str(tmp_path / "cookies.json"),
        })
    assert not meta_result.success
    assert "Vietnamese" in meta_result.error or "English" in meta_result.error
    assert not tiktok_result.success
    assert "Vietnamese" in tiktok_result.error or "English" in tiktok_result.error


def test_metadata_validation_enforces_vietnamese(tmp_path: Path):
    meta_path = tmp_path / "publish_metadata.json"

    # Case 1: Untranslated English title
    meta_path.write_text(json.dumps({
        "id": "cand_eng",
        "title": "CHOMPI is a magical sampler #tintuc #congnghe #ai",
        "description": "Tin tức hôm nay #tintuc #congnghe #ai"
    }), encoding="utf-8")

    success, errors = validate_metadata(meta_path)
    assert not success
    assert any("title language error" in err for err in errors)

    # Case 2: Untranslated English description
    meta_path.write_text(json.dumps({
        "id": "cand_eng",
        "title": "Tin tức AI mới nhất #tintuc #congnghe #ai",
        "description": "The last time my family was replaced by technology #tintuc #congnghe #ai"
    }), encoding="utf-8")

    success, errors = validate_metadata(meta_path)
    assert not success
    assert any("description language error" in err for err in errors)

    # Case 3: Valid Vietnamese prose
    meta_path.write_text(json.dumps({
        "id": "cand_vn",
        "title": "Công nghệ AI mới 2026 #tintuc #congnghe #ai",
        "description": "Tin tức hôm nay cung cấp thông tin mới #tintuc #congnghe #ai"
    }), encoding="utf-8")

    success, errors = validate_metadata(meta_path)
    assert success, f"Should pass valid Vietnamese prose: {errors}"

def test_director_artifacts_enforces_vietnamese(tmp_path: Path):
    # Test strict language gate for director artifacts
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # Nested script with untranslated english prose
    nested_dir = tmp_path / "cand_tmp"
    nested_dir.mkdir()

    nested_script = {
        "artifacts": {
            "script": {
                "version": "1.0",
                "title": "CHOMPI is a magical sampler",
                "sections": [{"text": "Xin chào, CHOMPI is a magical sampler designed to make music fun."}]
            }
        }
    }
    (nested_dir / "checkpoint_script.json").write_text(json.dumps(nested_script), encoding="utf-8")

    # Validation should reject promotion
    assert not validate_and_promote_director_artifacts(tmp_path, require_compositions=False)
    assert not (artifacts_dir / "script_vi.json").is_file(), "Should not promote invalid script"

    # Test fallback generation respects language gate
    (nested_dir / "checkpoint_script.json").unlink()

    brief = {
        "title": "CHOMPI is a magical sampler",
        "data_points": [{"claim": "It is designed to make music fun."}]
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief), encoding="utf-8")

    # Validation synthesis should fail closed
    assert not validate_and_promote_director_artifacts(tmp_path, require_compositions=False)
    assert not (artifacts_dir / "script_vi.json").is_file(), "Should not synthesize English title"

def test_youtube_publisher_rejects_english_prose(tmp_path: Path):
    dummy_video = tmp_path / "video.mp4"
    dummy_video.touch()

    publisher = YoutubePublisher()
    with patch("tools.publishers.platform_routes.ensure_vertical"), \
         patch("tools.publishers.platform_routes.ensure_youtube_short"):

        # Reject English title
        res = publisher.execute({
            "video_path": str(dummy_video),
            "title": "CHOMPI is a magical sampler #Shorts",
            "description": "Tin tức AI mới",
        })
        assert not res.success
        assert "Invalid YouTube title" in res.error

        # Reject English description
        res = publisher.execute({
            "video_path": str(dummy_video),
            "title": "Bộ lấy mẫu CHOMPI độc đáo #Shorts",
            "description": "The last time my family was replaced by technology",
        })
        assert not res.success
        assert "Invalid YouTube description" in res.error

        # Valid Vietnamese title+description proceed to credential gate (not prose gate)
        res = publisher.execute({
            "video_path": str(dummy_video),
            "title": "Bộ lấy mẫu CHOMPI độc đáo #Shorts",
            "description": "Tin tức công nghệ AI mới nhất hôm nay",
        })
        assert not res.success
        assert "Invalid YouTube" not in res.error

def test_schedule_today_native_blocks_invalid_metadata(tmp_path: Path):
    from scripts.schedule_today_native import main as schedule_main
    project_dir = tmp_path / "projects" / "cand_bad_lang"
    project_dir.mkdir(parents=True)

    meta_path = project_dir / "publish_metadata.json"
    meta_path.write_text(json.dumps({
        "id": "cand_bad_lang",
        "title": "CHOMPI is a magical sampler #tintuc #congnghe #ai",
        "description": "Tin tức hôm nay #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "publish_date": "2026-10-01",
        "publish_time": "14:00",
    }), encoding="utf-8")

    (project_dir / "validation_status.json").write_text(json.dumps([{
        "status": "PASS",
        "strict_quality_pass": True
    }]), encoding="utf-8")

    cfg = {
        "timezone": "Asia/Ho_Chi_Minh",
        "youtube": {"account": "main_account"},
        "active_projects": [{
            "project_id": "cand_bad_lang",
            "publish_date": "2026-10-01",
            "publish_time": "14:00"
        }]
    }

    mock_store = MagicMock()

    from datetime import datetime as dt_cls
    class FakeDateTime(dt_cls):
        @classmethod
        def now(cls, tz=None):
            return dt_cls(2026, 10, 1, 10, 0, tzinfo=tz)

    with patch("scripts.schedule_today_native.load_config", return_value=cfg), \
         patch("sys.argv", ["schedule_today_native.py", "--date", "2026-10-01"]), \
         patch("scripts.schedule_today_native.ROOT", tmp_path), \
         patch("scripts.schedule_today_native.PublishStore", return_value=mock_store), \
         patch("scripts.schedule_today_native.YoutubePublisher") as mock_yt_cls, \
         patch("scripts.schedule_today_native.datetime", FakeDateTime):
        # Running scheduler must fail/skip and NOT claim the invalid project
        with pytest.raises(SystemExit) as exc:
            schedule_main()
        assert exc.value.code != 0
        assert mock_store.claim.call_count == 0, "Should not make any Firebase claim for non-Vietnamese metadata"
        assert mock_yt_cls.return_value.execute.call_count == 0, "Should not upload to YouTube for non-Vietnamese metadata"

