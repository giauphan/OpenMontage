"""Tests for Codex Agent Validation Implementation."""

import json
import tempfile
import pytest
from pathlib import Path
from scripts.codex_agent_validation import (
    CodexAgentValidator,
    CLAUDEAgentValidator,
    ValidationResult,
    parse_codex_review,
    parse_claude_review,
    resolve_codex_cli,
    resolve_claude_cli,
    resolve_agent_cli,
)


class TestCodexValidationResult:
    """Test ValidationResult dataclass."""

    def test_validation_result_creation(self):
        result = ValidationResult(
            check_name="Test Check",
            passed=True,
            message="Test passed",
            details={"score": 100},
        )
        assert result.check_name == "Test Check"
        assert result.passed is True
        assert result.message == "Test passed"
        assert result.details == {"score": 100}


class TestCodexAgentValidator:
    """Test CodexAgentValidator class."""

    def test_validator_initialization(self):
        test_dir = Path(tempfile.mkdtemp())
        validator = CodexAgentValidator(project_dir=test_dir, strict_mode=True)
        assert validator.project_dir == test_dir
        assert validator.strict_mode is True
        assert validator.retry_count == 2

    def test_alias_equivalence(self):
        assert CLAUDEAgentValidator is CodexAgentValidator
        assert parse_claude_review is parse_codex_review

    def test_technical_contract_missing_file(self):
        test_dir = Path(tempfile.mkdtemp())
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        non_existent = test_dir / "nonexistent.mp4"
        results = validator.validate_technical_contract(non_existent)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Video file missing" in results[0].message

    def test_technical_contract_empty_file(self):
        test_dir = Path(tempfile.mkdtemp())
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        empty_file = test_dir / "empty.mp4"
        empty_file.touch()
        results = validator.validate_technical_contract(empty_file)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Video file empty" in results[0].message

    def test_metadata_validation_missing_file(self):
        test_dir = Path(tempfile.mkdtemp())
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        non_existent = test_dir / "nonexistent.json"
        results = validator.validate_metadata(non_existent)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Metadata file missing" in results[0].message

    def test_autonomous_quality_review_success(self):
        test_dir = Path(tempfile.mkdtemp())
        (test_dir / "hyperframes").mkdir(parents=True, exist_ok=True)
        (test_dir / "hyperframes" / "index.html").write_text("<html><body>scene</body></html>")
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        video_path = test_dir / "video.mp4"
        video_path.write_bytes(b"x" * 2000)
        meta_path = test_dir / "publish_metadata.json"
        meta_path.write_text(json.dumps({"title": "AI News #tintuc #congnghe #ai"}), encoding="utf-8")
        results = validator._autonomous_quality_review(video_path, meta_path)
        assert len(results) == 4
        assert all(r.passed for r in results)

    def test_autonomous_quality_review_brand_violation(self):
        test_dir = Path(tempfile.mkdtemp())
        (test_dir / "hyperframes").mkdir(parents=True, exist_ok=True)
        (test_dir / "hyperframes" / "index.html").write_text("<html><body>scene</body></html>")
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        video_path = test_dir / "video.mp4"
        video_path.write_bytes(b"x" * 2000)
        meta_path = test_dir / "publish_metadata.json"
        meta_path.write_text(json.dumps({"title": "Made with OpenMontage #tintuc #congnghe #ai"}), encoding="utf-8")
        results = validator._autonomous_quality_review(video_path, meta_path)
        brand_check = next(r for r in results if r.check_name == "Brand Compliance")
        assert brand_check.passed is False
        assert "Prohibited brand violation" in brand_check.message

    def test_parse_codex_review_json(self):
        review = {
            "visual_quality": {"passed": True, "score": 95, "notes": "clear"},
            "audio_sync": {"passed": True, "score": 95, "notes": "aligned"},
            "content_appropriateness": {"passed": True, "score": 95, "notes": "safe"},
            "brand_compliance": {"passed": True, "score": 95, "notes": "compliant"},
            "overall_passed": True,
            "summary": "all passed",
        }
        parsed = parse_codex_review(json.dumps(review))
        assert parsed["overall_passed"] is True
        assert parsed["visual_quality"]["score"] == 95


class TestCodexCommandLineIntegration:
    def test_help_command(self):
        import subprocess
        result = subprocess.run(
            ["python3", "scripts/codex_agent_validation.py", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
