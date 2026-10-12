"""Tests for Codex Agent Validation Implementation."""

import json
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from scripts.codex_agent_validation import (
    CodexAgentValidator,
    CLAUDEAgentValidator,
    ValidationResult,
    parse_codex_review,
    parse_claude_review,
    resolve_codex_cli,
    resolve_claude_cli,
    resolve_agent_cli,
    resolve_and_validate_codex_home,
    parse_and_validate_config_toml,
)


class TestCodexHomeValidation:
    def test_explicit_valid_home(self, tmp_path, monkeypatch):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": "sk-test"}')
        (codex_home / "config.toml").write_text('model_provider = "test"')

        env = {"CODEX_HOME": str(codex_home)}
        result = resolve_and_validate_codex_home(env)

        assert result == str(codex_home)

    def test_explicit_invalid_dir(self, tmp_path):
        env = {"CODEX_HOME": str(tmp_path / "nonexistent")}
        with pytest.raises(RuntimeError, match="not exist or is not a directory"):
            resolve_and_validate_codex_home(env)

    def test_explicit_missing_auth(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        # Create empty auth
        (codex_home / "auth.json").touch()
        (codex_home / "config.toml").touch()

        env = {"CODEX_HOME": str(codex_home)}
        with pytest.raises(RuntimeError, match="missing or has empty auth.json"):
            resolve_and_validate_codex_home(env)

    def test_explicit_null_api_key_rejected(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": null}')
        (codex_home / "config.toml").write_text('model_provider = "test"')

        env = {"CODEX_HOME": str(codex_home)}
        with pytest.raises(RuntimeError, match="auth.json missing or invalid OPENAI_API_KEY"):
            resolve_and_validate_codex_home(env)

    def test_explicit_empty_string_api_key_rejected(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": ""}')
        (codex_home / "config.toml").write_text('model_provider = "test"')

        env = {"CODEX_HOME": str(codex_home)}
        with pytest.raises(RuntimeError, match="auth.json missing or invalid OPENAI_API_KEY"):
            resolve_and_validate_codex_home(env)

    def test_config_toml_missing_model_provider_rejected(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": "sk-test"}')
        (codex_home / "config.toml").write_text('other = "value"')

        env = {"CODEX_HOME": str(codex_home)}
        with pytest.raises(RuntimeError, match="missing model_provider"):
            resolve_and_validate_codex_home(env)

    def test_unset_fallback_discovery(self, tmp_path, monkeypatch):
        codex_home = tmp_path / ".codex_pipeline"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": "sk-test"}')
        (codex_home / "config.toml").write_text('model_provider = "test"')

        # Mock candidate_homes by prepending our tmp_path
        import scripts.codex_agent_validation
        import os
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(scripts.codex_agent_validation, "os", os) # ensure no weird un-mock

        env = {}
        result = resolve_and_validate_codex_home(env)
        # Should pick up tmp_path / .codex_pipeline
        assert result == str(codex_home)

    def test_auto_discovery_null_api_key_rejected(self, tmp_path, monkeypatch):
        codex_home = tmp_path / ".codex_pipeline"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": null}')
        (codex_home / "config.toml").write_text('model_provider = "test"')

        import scripts.codex_agent_validation
        import os
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(scripts.codex_agent_validation, "os", os)
        # Block all fixed candidate paths so only tmp_path/.codex_pipeline is probed
        monkeypatch.setattr(Path, "is_file", lambda self: (
            self.parent == codex_home and self.name in ("auth.json", "config.toml")
        ))

        with pytest.raises(RuntimeError, match="No valid Codex home"):
            resolve_and_validate_codex_home({})

    def test_unset_no_valid_fallback(self, monkeypatch):
        # Prevent picking up actual root homes
        monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent/tmp"))
        # Also prevent finding /root/.codex or /home/ubuntu/.codex
        monkeypatch.setattr(Path, "is_file", lambda self: False)
        with pytest.raises(RuntimeError, match="Fallback to temporary credentials is disabled"):
            resolve_and_validate_codex_home({})

    def test_resolution_pins_to_realpath_snapshot(self, tmp_path, monkeypatch):
        """Proof that the resolution yields the realpath, ensuring consumers
        see a frozen generation snapshot even if the target pointer refreshes."""
        store = tmp_path / "store"
        store.mkdir()
        gen = store / "gen_123"
        gen.mkdir()
        (gen / "auth.json").write_text('{"OPENAI_API_KEY": "sk-test"}')
        (gen / "config.toml").write_text('model_provider = "test"')

        codex_home = tmp_path / ".codex"
        codex_home.symlink_to(gen)

        env = {"CODEX_HOME": str(codex_home)}
        result = resolve_and_validate_codex_home(env)

        # Must return the fully resolved generation path, not the symlink path
        assert result == str(gen.resolve())


class TestParseAndValidateConfigToml:
    """Test parse_and_validate_config_toml strictly enforces TOML syntax and string model_provider."""

    def test_valid_string_provider_accepted(self):
        content = 'model_provider = "openai"\n'
        result = parse_and_validate_config_toml(content)
        assert result["model_provider"] == "openai"

    def test_single_quoted_string_accepted(self):
        content = "model_provider = 'anthropic'\n"
        result = parse_and_validate_config_toml(content)
        assert result["model_provider"] == "anthropic"

    def test_numeric_provider_rejected(self):
        content = 'model_provider = 123\n'
        with pytest.raises(ValueError, match="must be a non-empty string|syntax"):
            parse_and_validate_config_toml(content)

    def test_boolean_provider_rejected(self):
        content = 'model_provider = true\n'
        with pytest.raises(ValueError, match="must be a non-empty string|syntax"):
            parse_and_validate_config_toml(content)

    def test_empty_string_provider_rejected(self):
        content = 'model_provider = ""\n'
        with pytest.raises(ValueError, match="must be a non-empty string"):
            parse_and_validate_config_toml(content)

    def test_duplicate_key_rejected(self):
        content = 'model_provider = "first"\nmodel_provider = "second"\n'
        with pytest.raises(ValueError, match="Duplicate key|Invalid TOML"):
            parse_and_validate_config_toml(content)

    def test_subtable_provider_rejected(self):
        content = '[other_table]\nmodel_provider = "test"\n'
        with pytest.raises(ValueError, match="Missing required root-level 'model_provider'"):
            parse_and_validate_config_toml(content)

    def test_malformed_syntax_rejected(self):
        content = 'model_provider\n'
        with pytest.raises(ValueError, match="Invalid TOML syntax|expected key = value"):
            parse_and_validate_config_toml(content)

    def test_malformed_array_rejected_in_fallback(self, monkeypatch):
        # Force the strict fallback by making tomllib and tomli unimportable.
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\nbroken = [\n'
        with pytest.raises(ValueError, match="unclosed|fallback validator|missing value|syntax"):
            parse_and_validate_config_toml(content)

    def test_malformed_inline_table_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\nbroken = {\n'
        with pytest.raises(ValueError, match="unclosed|fallback validator|missing value|syntax"):
            parse_and_validate_config_toml(content)

    def test_valid_array_and_inline_table_accepted_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = (
            'model_provider = "openai"\n'
            'tags = ["ai", "video"]\n'
            'settings = { timeout = 30, retries = 3 }\n'
        )
        res = parse_and_validate_config_toml(content)
        assert res["model_provider"] == "openai"

    def test_duplicate_table_header_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\n[section]\nk = 1\n[section]\nk = 2\n'
        with pytest.raises(ValueError, match="duplicate table header"):
            parse_and_validate_config_toml(content)

    def test_uppercase_boolean_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\nflag = TRUE\n'
        with pytest.raises(ValueError, match="invalid TOML value"):
            parse_and_validate_config_toml(content)

    def test_leading_zero_decimal_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\nbad = 007\n'
        with pytest.raises(ValueError, match="invalid TOML value"):
            parse_and_validate_config_toml(content)

    def test_invalid_escape_sequence_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\nbad = "foo\\x"\n'
        with pytest.raises(ValueError, match="invalid escape sequence"):
            parse_and_validate_config_toml(content)

    def test_duplicate_key_in_inline_table_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\nbad = { a = 1, a = 2 }\n'
        with pytest.raises(ValueError, match="duplicate key 'a' in inline table"):
            parse_and_validate_config_toml(content)

    def test_empty_dotted_key_segment_rejected_in_fallback(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _no_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"mock: no {name}")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_toml)

        content = 'model_provider = "test"\na..b = 1\n'
        with pytest.raises(ValueError, match="invalid key"):
            parse_and_validate_config_toml(content)


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

    def test_parse_codex_review_jsonl_stream(self):
        jsonl = (
            '{"type":"thread.started","thread_id":"test-123"}\n'
            '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"'
            'Here is the review result:\\n\\n```json\\n'
            '{\\"visual_quality\\": {\\"passed\\": true, \\"score\\": 95, \\"notes\\": \\"fine\\"}, '
            '\\"audio_sync\\": {\\"passed\\": true, \\"score\\": 95, \\"notes\\": \\"fine\\"}, '
            '\\"content_appropriateness\\": {\\"passed\\": true, \\"score\\": 95, \\"notes\\": \\"fine\\"}, '
            '\\"brand_compliance\\": {\\"passed\\": true, \\"score\\": 95, \\"notes\\": \\"fine\\"}, '
            '\\"overall_passed\\": true, \\"summary\\": \\"looks good\\"}'
            '\\n```"}}\n'
            '{"type":"turn.completed"}\n'
        )
        parsed = parse_codex_review(jsonl)
        assert parsed["overall_passed"] is True
        assert parsed["visual_quality"]["passed"] is True
        assert parsed["visual_quality"]["score"] == 95



class TestCanonicalValidatorImports:
    def test_imports_do_not_form_circular_dependency(self):
        result = subprocess.run(
            [sys.executable, "-c", "import scripts.codex_agent_validation; print('ok')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"


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


class TestCodexFailClosedStrictReview:
    def test_technical_contract_rejects_corrupt_video(self, tmp_path):
        validator = CodexAgentValidator(tmp_path, strict_mode=True)
        vid = tmp_path / "corrupt.mp4"
        vid.write_bytes(b"x" * 2000)
        with patch("scripts.codex_agent_validation.verify_video_integrity", return_value=(False, "decode failed", {})):
            results = validator.validate_technical_contract(vid)
            assert len(results) == 1
            assert results[0].passed is False
            assert "decode failed" in results[0].message

    def test_extract_frames_rejects_corrupt_frame(self, tmp_path):
        validator = CodexAgentValidator(tmp_path, strict_mode=True)
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"x" * 2000)
        out_dir = tmp_path / "frames"

        with patch("scripts.codex_agent_validation.subprocess.run") as mock_subproc,              patch("scripts.codex_agent_validation.verify_image_integrity", return_value=(False, "bad magic")):
            mock_subproc.side_effect = [
                MagicMock(returncode=0, stdout="10.0"), # duration probe
                MagicMock(returncode=0), # ffmpeg frame extract
                MagicMock(returncode=0), # ffmpeg frame extract
                MagicMock(returncode=0), # ffmpeg frame extract
            ]
            frames = validator._extract_frames(vid, out_dir)
            assert frames == []

    """Test strict fail-closed and audit binding rules."""

    def test_strict_review_fails_when_agent_cli_missing(self, monkeypatch):
        test_dir = Path(tempfile.mkdtemp())
        # Pre-checks (missing-HTML / frame extraction) run before the CLI gate
        # in strict mode; supply valid composition + frames so this test
        # isolates the CLI-missing fail-closed path specifically.
        (test_dir / "hyperframes").mkdir(parents=True, exist_ok=True)
        (test_dir / "hyperframes" / "index.html").write_text("<html><body>scene</body></html>", encoding="utf-8")
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        video_path = test_dir / "video.mp4"
        video_path.write_bytes(b"content" * 100)
        meta_path = test_dir / "meta.json"
        meta_path.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(validator, "_extract_frames", lambda *a, **k: [test_dir / "frame.png"])
        monkeypatch.setattr("scripts.codex_agent_validation.resolve_agent_cli", lambda: None)
        results = validator.codex_agent_strict_review(video_path, meta_path)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Agent CLI binary not found" in results[0].message
        assert results[0].details["inspected_artifact_hash"] != ""

    def test_strict_review_fails_on_cli_exception(self, monkeypatch):
        test_dir = Path(tempfile.mkdtemp())
        # Supply valid composition + frames so the pre-checks pass and this
        # test isolates the CLI-exception fail-closed path specifically.
        (test_dir / "hyperframes").mkdir(parents=True, exist_ok=True)
        (test_dir / "hyperframes" / "index.html").write_text("<html><body>scene</body></html>", encoding="utf-8")
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        video_path = test_dir / "video.mp4"
        video_path.write_bytes(b"content" * 100)
        meta_path = test_dir / "meta.json"
        meta_path.write_text("{}", encoding="utf-8")

        monkeypatch.setattr("scripts.codex_agent_validation.resolve_agent_cli", lambda: "/usr/bin/codex")
        monkeypatch.setattr(validator, "_extract_frames", lambda *a, **k: [test_dir / "frame.png"])
        def _mock_exec(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["codex"], timeout=30)
        monkeypatch.setattr(validator, "_execute_cli_review", _mock_exec)

        results = validator.codex_agent_strict_review(video_path, meta_path)
        assert len(results) == 1
        assert results[0].passed is False
        assert "timed out" in results[0].message.lower() or "timeout" in results[0].message.lower()
        assert results[0].details["inspected_artifact_hash"] != ""

    def test_strict_review_fails_on_missing_category(self, monkeypatch):
        test_dir = Path(tempfile.mkdtemp())
        (test_dir / "hyperframes").mkdir(parents=True, exist_ok=True)
        (test_dir / "hyperframes" / "index.html").write_text("<html><body>scene</body></html>", encoding="utf-8")
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        video_path = test_dir / "video.mp4"
        video_path.write_bytes(b"content" * 100)
        meta_path = test_dir / "meta.json"
        meta_path.write_text("{}", encoding="utf-8")

        codex_home = test_dir / "codex_home"
        codex_home.mkdir(parents=True, exist_ok=True)
        (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": "sk-test"}', encoding="utf-8")
        (codex_home / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        monkeypatch.setenv("CODEX_HOME", str(codex_home))

        monkeypatch.setattr("scripts.codex_agent_validation.resolve_agent_cli", lambda: "/usr/bin/codex")
        monkeypatch.setattr(validator, "_extract_frames", lambda *args, **kwargs: [test_dir / "frame.png"])
        # Incomplete review output: missing brand_compliance
        incomplete_json = json.dumps({
            "visual_quality": {"passed": True, "score": 90, "notes": "ok"},
            "audio_sync": {"passed": True, "score": 90, "notes": "ok"},
            "content_appropriateness": {"passed": True, "score": 90, "notes": "ok"},
            "overall_passed": True,
        })
        class DummyProc:
            stdout = incomplete_json
            returncode = 0
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyProc())

        results = validator.codex_agent_strict_review(video_path, meta_path)
        assert len(results) == 1
        assert results[0].passed is False
        assert "missing mandatory category: brand_compliance" in results[0].message

    def test_strict_review_blocks_mock_in_production_mode(self, monkeypatch):
        test_dir = Path(tempfile.mkdtemp())
        validator = CodexAgentValidator(test_dir, strict_mode=True)
        video_path = test_dir / "video.mp4"
        video_path.write_bytes(b"content" * 100)
        meta_path = test_dir / "meta.json"
        meta_path.write_text("{}", encoding="utf-8")

        monkeypatch.setenv("CODEX_AGENT_VALIDATION_MOCK", "1")
        monkeypatch.setenv("PRODUCTION_RELEASE", "1")
        results = validator.codex_agent_strict_review(video_path, meta_path)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Mock review strictly forbidden in production mode" in results[0].message
