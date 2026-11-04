"""Detailed tests for validate_newsnow_director_artifacts boundary helper."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.validate_newsnow_director_artifacts as helper


def test_validator_rejects_missing_directory(tmp_path):
    assert helper.validate_and_promote_director_artifacts(tmp_path / "missing") is False


def test_validator_accepts_valid_flat_artifact(tmp_path):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    script = arts / "script_vi.json"

    # Director output with theme and sections (no version) is normalized by validator
    script.write_text(json.dumps({"theme": "Tin tức công nghệ", "total_duration_seconds": 10, "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}]}), encoding="utf-8")
    assert helper.validate_and_promote_director_artifacts(tmp_path) is True

    # Valid: Vietnamese text_vi preferred over English text
    script.write_text(json.dumps({"version": "1.0", "title": "Tin tức công nghệ", "total_duration_seconds": 10, "sections": [{"id": "1", "text_vi": "Nội dung mới đây", "text": "Hello world", "start_seconds": 0, "end_seconds": 10}]}), encoding="utf-8")
    assert helper.validate_and_promote_director_artifacts(tmp_path) is True


def test_en_us_validator_rejects_narration_that_cannot_fit_short_contract(tmp_path):
    """Overlong English text must trigger the director repair turn before TTS."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "script_en_US.json").write_text(json.dumps({
        "version": "1.0",
        "title": "Agent reliability",
        "total_duration_seconds": 70,
        "sections": [{
            "id": "s1",
            "text": "word " * 190,
            "start_seconds": 0,
            "end_seconds": 70,
        }],
    }), encoding="utf-8")
    (artifacts / "project_locale.json").write_text(json.dumps({"locale": "en-US"}), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert any("spoken words" in error for error in helper.LAST_VALIDATION_ERRORS)


def test_validator_requires_both_compositions_when_requested(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "script_vi.json").write_text(json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path, require_compositions=True) is False

    (tmp_path / "hyperframes").mkdir()
    (tmp_path / "hyperframes_reels").mkdir()
    (tmp_path / "hyperframes" / "index.html").write_text("full")
    (tmp_path / "hyperframes_reels" / "index.html").write_text("reels")

    assert helper.validate_and_promote_director_artifacts(tmp_path, require_compositions=True) is True


def test_validator_promotes_fresh_artifacts_script(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script.json"
    script.write_text(json.dumps({
        "version": "1.0",
        "title": "Tiêu đề",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text_vi": "Nội dung", "start_seconds": 0, "end_seconds": 10}],
    }), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path, min_mtime_ns=script.stat().st_mtime_ns - 1)
    assert json.loads((artifacts / "script_vi.json").read_text(encoding="utf-8"))["sections"][0]["text"] == "Nội dung"


def test_validator_rejects_stale_artifacts_script(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script.json"
    script.write_text(json.dumps({
        "version": "1.0",
        "title": "Tiêu đề",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung", "start_seconds": 0, "end_seconds": 10}],
    }), encoding="utf-8")

    assert not helper.validate_and_promote_director_artifacts(tmp_path, min_mtime_ns=script.stat().st_mtime_ns + 1)


def test_validator_accepts_comparison_enhancement_cue(tmp_path):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    script = arts / "script_vi.json"
    script.write_text(json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{
            "id": "1",
            "text": "Nội dung mới đây",
            "start_seconds": 0,
            "end_seconds": 10,
            "enhancement_cues": [{"type": "comparison", "description": "Before and after"}],
        }],
    }), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is True


def test_validator_promotes_nested_checkpoint(tmp_path):
    project_id = tmp_path.name
    nested_dir = tmp_path / project_id
    nested_dir.mkdir()
    checkpoint = nested_dir / "checkpoint_script.json"

    payload = {
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text_vi": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}]
    }

    # Stale/old checkpoint check
    import os
    checkpoint.write_text(json.dumps({"artifacts": {"script": payload}}), encoding="utf-8")
    st = checkpoint.stat()
    assert helper.validate_and_promote_director_artifacts(tmp_path, min_mtime_ns=st.st_mtime_ns + 1000000000) is False

    # Fresh checkpoint
    assert helper.validate_and_promote_director_artifacts(tmp_path, min_mtime_ns=st.st_mtime_ns - 1000000000) is True

    # Promoted successfully
    promoted = tmp_path / "artifacts" / "script_vi.json"
    assert promoted.is_file()

    expected_payload = {
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10.0,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0.0, "end_seconds": 10.0}]
    }
    assert json.loads(promoted.read_text(encoding="utf-8")) == expected_payload


def _write_bound_news_evidence(artifacts: Path, script_bytes: bytes) -> None:
    (artifacts / "news_evidence.json").write_text(json.dumps({
        "version": "2.0",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
    }), encoding="utf-8")


def test_unbound_draft_is_normalized_and_promoted(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    draft = artifacts / "script.json"
    draft.write_text(json.dumps({
        "title_vi": "Tin tức công nghệ",
        "total_duration_secs": 10,
        "sections": [{"id": 1, "narration": "Nội dung mới đây", "duration_seconds": 10}],
    }, ensure_ascii=False), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is True
    promoted = json.loads((artifacts / "script_vi.json").read_text(encoding="utf-8"))
    assert promoted["version"] == "1.0"
    assert promoted["title"] == "Tin tức công nghệ"
    assert promoted["sections"][0]["text"] == "Nội dung mới đây"
    assert not (artifacts / "news_evidence.json").exists()


def test_bound_canonical_script_is_validated_without_rewrite(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script_vi.json"
    raw = (
        '{"version":"1.0","title":"Tin tức công nghệ",'
        '"total_duration_seconds":10,"sections":[{"id":"1",'
        '"text":"Nội dung mới đây","start_seconds":0,"end_seconds":10}]}  \n'
    ).encode("utf-8")
    script.write_bytes(raw)
    _write_bound_news_evidence(artifacts, raw)

    assert helper.validate_and_promote_director_artifacts(tmp_path) is True
    assert script.read_bytes() == raw


@pytest.mark.parametrize("evidence_bytes", [b"{not-json", b'{"version":"1.0","script_sha256":"unused"}'])
def test_malformed_or_wrong_version_evidence_preserves_canonical_and_draft(tmp_path, evidence_bytes):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script_vi.json"
    canonical_bytes = json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }, ensure_ascii=False).encode("utf-8")
    draft = artifacts / "script.json"
    draft_bytes = json.dumps({
        "title_vi": "Bản nháp",
        "total_duration_secs": 12,
        "sections": [{"id": 1, "narration": "Nội dung dự thảo", "duration_seconds": 12}],
    }, ensure_ascii=False).encode("utf-8")
    script.write_bytes(canonical_bytes)
    draft.write_bytes(draft_bytes)
    (artifacts / "news_evidence.json").write_bytes(evidence_bytes)

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert script.read_bytes() == canonical_bytes
    assert draft.read_bytes() == draft_bytes


def test_bound_schema_invalid_canonical_script_fails_without_rewrite(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script_vi.json"
    # Missing the required version/title fields must not be repaired as a draft.
    raw = json.dumps({
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }, ensure_ascii=False).encode("utf-8")
    script.write_bytes(raw)
    _write_bound_news_evidence(artifacts, raw)

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert script.read_bytes() == raw
    assert helper.LAST_VALIDATION_ERRORS


def test_bound_invalid_research_brief_preserves_canonical_script(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script_vi.json"
    raw = json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }, ensure_ascii=False).encode("utf-8")
    script.write_bytes(raw)
    _write_bound_news_evidence(artifacts, raw)
    (artifacts / "research_brief.json").write_text(json.dumps({"title": "invalid"}), encoding="utf-8")
    monkeypatch.setattr(helper, "check_vietnamese_prose", lambda text: text == "invalid")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert script.read_bytes() == raw


def test_bound_canonical_script_hash_mismatch_fails_without_mutation(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script_vi.json"
    raw = json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }, ensure_ascii=False).encode("utf-8")
    script.write_bytes(raw)
    _write_bound_news_evidence(artifacts, raw + b" ")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert script.read_bytes() == raw
    assert any("binding mismatch" in error for error in helper.LAST_VALIDATION_ERRORS)


def test_bound_invalid_canonical_script_does_not_fall_back_to_draft(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    script = artifacts / "script_vi.json"
    raw = json.dumps({"title": "Tin tức công nghệ", "scenes": []}, ensure_ascii=False).encode("utf-8")
    script.write_bytes(raw)
    _write_bound_news_evidence(artifacts, raw)
    (artifacts / "script.json").write_text(json.dumps({
        "version": "1.0",
        "title": "Bản nháp",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }, ensure_ascii=False), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert script.read_bytes() == raw


def test_bound_evidence_with_missing_canonical_script_blocks_draft_fallback(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    draft = artifacts / "script.json"
    draft.write_text(json.dumps({
        "version": "1.0",
        "title": "Bản nháp",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}],
    }, ensure_ascii=False), encoding="utf-8")
    (artifacts / "news_evidence.json").write_text(json.dumps({"version": "2.0", "script_sha256": "0" * 64}), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is False
    assert not (artifacts / "script_vi.json").exists()
    assert draft.is_file()


def test_cli_integration(tmp_path):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    (arts / "script_vi.json").write_text(json.dumps({
        "version": "1.0",
        "title": "Tin tức công nghệ",
        "total_duration_seconds": 10,
        "sections": [{"id": "1", "text_vi": "Nội dung mới đây", "start_seconds": 0, "end_seconds": 10}]
    }), encoding="utf-8")

    env = {"PYTHONPATH": str(Path(helper.__file__).resolve().parents[1])}
    res = subprocess.run([sys.executable, str(helper.__file__), str(tmp_path)], env=env, capture_output=True, text=True)
    assert res.returncode == 0
    assert "✓ Validated" in res.stdout


def test_scripts_prevent_recursive_invocation():
    """Verify that the director wrapper shell scripts explicitly forbid recursive execution."""
    root = Path(__file__).resolve().parents[2]

    scripts = [
        root / "scripts" / "run_daily_news_pipeline.sh",
        root / "scripts" / "run_directors_for_existing.sh"
    ]

    for script_path in scripts:
        content = script_path.read_text(encoding="utf-8")
        assert "DIRECTOR_SYSTEM_NOTE=" in content

    prompt_path = root / "scripts" / "prompts" / "director_system.prompt.md"
    if prompt_path.exists():
        prompt_content = prompt_path.read_text(encoding="utf-8")
        assert "infinite loop" in prompt_content or "recursion" in prompt_content or "wrappers" in prompt_content


def test_scripts_resolve_hyperframes_from_node_modules():
    """Verify that both scripts check node_modules/.bin/hyperframes as a fallback path."""
    root = Path(__file__).resolve().parents[2]

    scripts = [
        root / "scripts" / "run_daily_news_pipeline.sh",
        root / "scripts" / "run_directors_for_existing.sh"
    ]

    for script_path in scripts:
        content = script_path.read_text(encoding="utf-8")
        assert "node_modules/.bin/hyperframes" in content


def test_validator_normalizes_director_schema_variants(tmp_path):
    project_id = tmp_path.name
    nested_dir = tmp_path / project_id
    nested_dir.mkdir()
    checkpoint = nested_dir / "checkpoint_script.json"

    # Variant payload with none of the strict schema names
    variant_payload = {
        "project_id": "cand_3eb816",
        "version": "2.0",
        "title_vi": "Tin tức công nghệ",
        "total_duration_secs": 90,
        "sections": [
            {
                "id": 1,
                "label": "Hook",
                "narration": "Chào mừng bạn",
                "duration_seconds": 10,
                "audio_file": "s1.wav",
                "scene_type": "hook"
            }
        ]
    }

    checkpoint.write_text(json.dumps({"artifacts": {"script": variant_payload}}), encoding="utf-8")
    assert helper.validate_and_promote_director_artifacts(tmp_path) is True

    promoted = tmp_path / "artifacts" / "script_vi.json"
    assert promoted.is_file()
    data = json.loads(promoted.read_text(encoding="utf-8"))

    # Assert normalized values match schema
    assert data["version"] == "1.0"
    assert data["title"] == "Tin tức công nghệ"
    assert data["total_duration_seconds"] == 90.0
    assert "project_id" not in data # Extraneous root key removed

    sec = data["sections"][0]
    assert sec["text"] == "Chào mừng bạn"
    assert sec["start_seconds"] == 0.0
    assert sec["end_seconds"] == 10.0
    assert "scene_type" not in sec # Extraneous section key removed
    assert "narration" not in sec


def test_validator_normalizes_missing_version_scene_payload(tmp_path):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    script = arts / "script_vi.json"
    script.write_text(json.dumps({
        "title": "Tin tức công nghệ",
        "duration_seconds": 8,
        "scenes": [
            {
                "id": 1,
                "start_time": 0,
                "duration": 8,
                "narration": "Chào mừng bạn",
            }
        ],
    }), encoding="utf-8")

    assert helper.validate_and_promote_director_artifacts(tmp_path) is True

    data = json.loads(script.read_text(encoding="utf-8"))
    assert data["version"] == "1.0"
    assert data["total_duration_seconds"] == 8.0
    assert data["sections"] == [{
        "id": "1",
        "text": "Chào mừng bạn",
        "start_seconds": 0.0,
        "end_seconds": 8.0,
    }]
