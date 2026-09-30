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

    validator = validation.CLAUDEAgentValidator(tmp_path, strict_mode=True)
    monkeypatch.setattr(validator, "_extract_frames", lambda *_args: [tmp_path / "frame.png"])
    results = validator.claude_agent_strict_review(tmp_path / "video.mp4", tmp_path / "publish_metadata.json")

    assert [result.passed for result in results] == [True, True, True, True]
