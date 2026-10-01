import json
import pytest
from pathlib import Path
from tools.narration_text import check_vietnamese_prose
from scripts.validate_publish_metadata import validate_metadata
from scripts.validate_newsnow_director_artifacts import validate_and_promote_director_artifacts

def test_language_heuristics():
    # Good Vietnamese prose + tech words
    assert not check_vietnamese_prose("Dùng API cho phần mềm mới.")
    assert not check_vietnamese_prose("Công nghệ 2026")
    assert not check_vietnamese_prose("Phần mềm mới tăng 60 phần trăm, một phần nhờ AI.")

    # English sentences
    chompi_err = check_vietnamese_prose("Tin tức công nghệ AI: CHOMPI is a magical sampler designed to make music fun.")
    assert chompi_err, "Should reject English prose"
    assert "Vietnamese prose" in chompi_err[0] or "English" in chompi_err[0]

    family_err = check_vietnamese_prose("Xin chào bạn, The last time my family was replaced by technology it was because of automation.")
    assert family_err, "Should reject English prose"

    # Only a hashtag doesn't make it Vietnamese prose
    tag_err = check_vietnamese_prose("CHOMPI is a magical sampler #tintuc #congnghe #ai")
    assert tag_err, "Should reject English prose even with valid hashtags"

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
        "description": "CHOMPI is a magical sampler #tintuc #congnghe #ai"
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
