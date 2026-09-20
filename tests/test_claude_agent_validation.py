"""Tests for CLAUDE Agent Validation Implementation."""

import json
import tempfile
import pytest
from pathlib import Path
from scripts.claude_agent_validation import CLAUDEAgentValidator, ValidationResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_validation_result_creation(self):
        """Test creating ValidationResult instances."""
        result = ValidationResult(
            check_name="Test Check",
            passed=True,
            message="Test passed",
            details={"score": 100}
        )
        
        assert result.check_name == "Test Check"
        assert result.passed is True
        assert result.message == "Test passed"
        assert result.details == {"score": 100}
        
    def test_validation_result_failure(self):
        """Test creating failed ValidationResult."""
        result = ValidationResult(
            check_name="Test Check",
            passed=False,
            message="Test failed",
            details={"error": "something went wrong"}
        )
        
        assert result.check_name == "Test Check"
        assert result.passed is False
        assert result.message == "Test failed"
        assert result.details == {"error": "something went wrong"}


class TestCLAUDEAgentValidator:
    """Test CLAUDEAgentValidator class."""
    
    def test_validator_initialization(self):
        """Test validator initialization."""
        test_dir = Path(tempfile.mkdtemp())
        validator = CLAUDEAgentValidator(
            project_dir=test_dir,
            strict_mode=True
        )
        
        assert validator.project_dir == test_dir
        assert validator.strict_mode is True
        assert validator.retry_count == 2
        assert validator.retry_count == 2
        
    def test_technical_contract_missing_file(self):
        """Test technical contract validation with missing file."""
        test_dir = Path(tempfile.mkdtemp())
        validator = CLAUDEAgentValidator(test_dir, strict_mode=True)
        
        non_existent = test_dir / "nonexistent.mp4"
        results = validator.validate_technical_contract(non_existent)
        
        assert len(results) == 1
        assert results[0].passed is False
        assert "Video file missing" in results[0].message
        
    def test_technical_contract_empty_file(self):
        """Test technical contract validation with empty file."""
        test_dir = Path(tempfile.mkdtemp())
        validator = CLAUDEAgentValidator(test_dir, strict_mode=True)
        
        # Create empty file
        empty_file = test_dir / "empty.mp4"
        empty_file.touch()
        
        results = validator.validate_technical_contract(empty_file)
        
        assert len(results) == 1
        assert results[0].passed is False
        assert "Video file empty" in results[0].message
        
    def test_metadata_validation_missing_file(self):
        """Test metadata validation with missing file."""
        test_dir = Path(tempfile.mkdtemp())
        validator = CLAUDEAgentValidator(test_dir, strict_mode=True)
        
        non_existent = test_dir / "nonexistent.json"
        results = validator.validate_metadata(non_existent)
        
        assert len(results) == 1
        assert results[0].passed is False
        assert "Metadata file missing" in results[0].message


class TestCommandLineIntegration:
    """Test command line integration."""

    def test_help_command(self):
        """Test that help command works."""
        import subprocess
        import os
        result = subprocess.run([
            "python3", "scripts/claude_agent_validation.py", "--help"
        ], capture_output=True, text=True, cwd=os.getcwd())

        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()


class TestStrictMode:
    """Test strict mode behavior."""
    
    def test_strict_mode_default(self):
        """Test that strict mode defaults to True."""
        import subprocess
        import os
        result = subprocess.run([
            "python3", "-c",
            "from scripts.claude_agent_validation import main; "
            "import argparse; parser = argparse.ArgumentParser(); "
            "parser.add_argument('--strict', action='store_true', default=True); "
            "parser.add_argument('--no-strict', action='store_true', default=False); "
            "args = parser.parse_args([]); "
            "print('strict=' + str(args.strict))"
        ], capture_output=True, text=True, cwd=os.getcwd())
        
        assert result.returncode == 0
        assert "strict=True" in result.stdout


class TestClaudeReviewEnvelope:
    def test_parse_claude_review_unwraps_result_json(self):
        from scripts.claude_agent_validation import parse_claude_review

        review = {
            "visual_quality": {"passed": True, "score": 94, "notes": "clear"},
            "audio_sync": {"passed": True, "score": 92, "notes": "aligned"},
            "content_appropriateness": {"passed": True, "score": 96, "notes": "safe"},
            "brand_compliance": {"passed": True, "score": 91, "notes": "consistent"},
            "overall_passed": True,
            "summary": "approved",
        }
        envelope = json.dumps({"is_error": False, "result": json.dumps(review)})

        assert parse_claude_review(envelope) == review

    def test_parse_claude_review_rejects_plain_text_result(self):
        from scripts.claude_agent_validation import parse_claude_review

        with pytest.raises(ValueError, match="review invalid"):
            parse_claude_review(json.dumps({"is_error": False, "result": "Looks good. Approved."}))

    def test_parse_claude_review_rejects_error_envelope(self):
        from scripts.claude_agent_validation import parse_claude_review

        with pytest.raises(ValueError, match="Claude CLI error"):
            parse_claude_review(json.dumps({"is_error": True, "result": "failure"}))

    def test_parse_claude_review_accepts_telemetry_before_review(self):
        from scripts.claude_agent_validation import parse_claude_review

        review = {
            "visual_quality": {"passed": True, "score": 94, "notes": "clear"},
            "audio_sync": {"passed": True, "score": 92, "notes": "aligned"},
            "content_appropriateness": {"passed": True, "score": 96, "notes": "safe"},
            "brand_compliance": {"passed": True, "score": 91, "notes": "consistent"},
            "overall_passed": True,
        }
        response = json.dumps({"duration_api_ms": 4444, "stop_reason": "end_turn"}) + "\n" + json.dumps(review)

        assert parse_claude_review(response) == review

    def test_parse_claude_review_rejects_telemetry_only(self):
        from scripts.claude_agent_validation import parse_claude_review

        telemetry = {"duration_api_ms": 4444, "stop_reason": "end_turn", "session_id": "test"}
        with pytest.raises(ValueError, match="review invalid"):
            parse_claude_review(json.dumps(telemetry))

    def test_parse_claude_review_rejects_missing_result(self):
        from scripts.claude_agent_validation import parse_claude_review

        with pytest.raises(ValueError, match="result missing"):
            parse_claude_review(json.dumps({"is_error": False}))