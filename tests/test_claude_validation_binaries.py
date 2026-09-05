"""Regression tests for direct strict-validator media binary discovery."""

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


def test_strict_review_uses_two_minute_timeout(monkeypatch, tmp_path):
    validator = validation.CLAUDEAgentValidator(tmp_path, strict_mode=True)
    captured = {}

    class Result:
        returncode = 1
        stdout = ""
        stderr = "failed"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return Result()

    monkeypatch.setattr(validation.subprocess, "run", fake_run)

    results = validator.claude_agent_strict_review(tmp_path / "video.mp4", tmp_path / "publish_metadata.json")

    assert captured["timeout"] == 120
    assert results[0].passed is False
