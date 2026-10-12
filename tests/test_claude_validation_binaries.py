"""Regression tests for direct strict-validator media binary discovery."""
import json
import subprocess
from pathlib import Path

import scripts.claude_agent_validation as validation

def test_main_passes_discovered_media_binaries(monkeypatch, tmp_path):
    ffprobe = tmp_path / "ffprobe"
    ffmpeg = tmp_path / "ffmpeg"
    ffprobe.touch()
    ffmpeg.touch()
    captured = {}

    class Validator:
        def __init__(self, **_kwargs):
            pass

        def execute_validation(self, **kwargs):
            captured.update(kwargs)
            return {
                "overall_status": "PASS",
                "color": "green",
                "total_checks": 0,
                "passed_checks": 0,
                "failed_checks": 0,
                "results": [],
            }

        def print_validation_report(self, _data):
            pass

    monkeypatch.setattr(validation, "resolve_ffprobe_ffmpeg", lambda: (str(ffprobe), str(ffmpeg)))
    monkeypatch.setattr(validation, "CLAUDEAgentValidator", Validator)
    monkeypatch.setattr(validation, "ValidationStatusLogger", None)
    monkeypatch.setattr("sys.argv", ["claude_agent_validation.py", str(tmp_path), "--strict"])

    try:
        validation.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured["ffprobe_bin"] == str(ffprobe)
    assert captured["ffmpeg_bin"] == str(ffmpeg)

def test_strict_review_uses_canonical_codex_result(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_AGENT_VALIDATION_MOCK", raising=False)
    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({
                "visual_quality": {"passed": True, "score": 95, "notes": "ok"},
                "audio_sync": {"passed": True, "score": 95, "notes": "ok"},
                "content_appropriateness": {"passed": True, "score": 95, "notes": "ok"},
                "brand_compliance": {"passed": True, "score": 95, "notes": "ok"},
                "overall_passed": True,
                "summary": "passed",
            }),
            stderr="",
        )

    (tmp_path / "hyperframes").mkdir()
    (tmp_path / "hyperframes" / "index.html").write_text("<html><body>scene</body></html>")
    (tmp_path / "video.mp4").write_bytes(b"video")

    monkeypatch.setattr(validation, "resolve_codex_cli", lambda: "/usr/bin/codex")
    monkeypatch.setattr(validation.subprocess, "run", run)

    # R1: Provide a hermetic CODEX_HOME so resolve_and_validate_codex_home does
    # not probe the host filesystem for credentials/config.
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text('{"OPENAI_API_KEY": "sk-test"}')
    (codex_home / "config.toml").write_text('model_provider = "openai"\n')
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    # Patch the resolver used by codex_agent_strict_review so it returns a
    # non-empty CLI path regardless of the host (CI runners have no codex bin).
    monkeypatch.setattr(
        "scripts.codex_agent_validation.resolve_agent_cli",
        lambda: "/usr/bin/codex",
    )

    validator = validation.CLAUDEAgentValidator(tmp_path, strict_mode=True)
    # Mock _extract_frames to return exactly 3 extracted frames so strict
    # visual pre-check passes in CI hermetic mode.
    monkeypatch.setattr(
        validator,
        "_extract_frames",
        lambda *_args: [tmp_path / f"frame-{i}.png" for i in range(3)],
    )
    results = validator.claude_agent_strict_review(tmp_path / "video.mp4", tmp_path / "publish_metadata.json")

    assert [result.passed for result in results] == [True, True, True, True]
