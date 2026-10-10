import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "generate_news_captions.py"
spec = importlib.util.spec_from_file_location("news_captions", HELPER)
captions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(captions)


class FakeTranscriber:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, options):
        self.calls.append(options)
        return SimpleNamespace(success=True, data=self.payload, error=None)


def _payload(audio_bytes, word):
    return {
        "timing_source": "asr",
        "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "language": "vi",
        "word_timestamps": [{"word": word, "start": 0.1, "end": 0.4}],
    }


def test_full_and_reels_are_transcribed_and_converted_separately(tmp_path, monkeypatch):
    full_audio = tmp_path / "full.mp3"
    reels_audio = tmp_path / "reels.mp3"
    full_audio.write_bytes(b"full audio")
    reels_audio.write_bytes(b"different reels audio")
    calls = []
    monkeypatch.setattr(captions.subprocess, "run", lambda command, check: calls.append(command) or SimpleNamespace(returncode=0))

    full_transcriber = FakeTranscriber(_payload(b"full audio", "Toàn"))
    reels_transcriber = FakeTranscriber(_payload(b"different reels audio", "Reels"))
    captions.generate_captions(full_audio, tmp_path / "full", transcriber=full_transcriber, converter="converter.py")
    captions.generate_captions(reels_audio, tmp_path / "reels", transcriber=reels_transcriber, converter="converter.py")

    assert full_transcriber.calls[0]["input_path"] == str(full_audio)
    assert reels_transcriber.calls[0]["input_path"] == str(reels_audio)
    assert full_transcriber.calls[0]["local_files_only"] is True
    assert len(calls) == 2
    assert all("--require-aligned" in command for command in calls)
    assert all("--transcript-json" in command for command in calls)
    assert all("--no-script-comparison" in command for command in calls)
    full_text = (tmp_path / "full" / "transcript.txt").read_text(encoding="utf-8")
    reels_text = (tmp_path / "reels" / "transcript.txt").read_text(encoding="utf-8")
    assert full_text == "Toàn"
    assert reels_text == "Reels"
    assert json.loads((tmp_path / "reels" / "transcript.json").read_text(encoding="utf-8"))["audio_sha256"] == hashlib.sha256(b"different reels audio").hexdigest()


def test_caption_alignment_failure_fails_closed_before_conversion(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    transcriber = FakeTranscriber({"timing_source": "estimated", "word_timestamps": []})
    converter_calls = []
    monkeypatch.setattr(captions.subprocess, "run", lambda *args, **kwargs: converter_calls.append(args))

    try:
        captions.generate_captions(audio, tmp_path / "captions", transcriber=transcriber, converter="converter.py")
    except RuntimeError as exc:
        assert "did not return ASR timings" in str(exc)
    else:
        raise AssertionError("non-ASR timing source must fail closed")
    assert converter_calls == []


def test_cached_model_missing_fails_with_actionable_message(tmp_path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    transcriber = SimpleNamespace(execute=lambda options: SimpleNamespace(
        success=False, error="model small not found in cache", data=None
    ))

    try:
        captions.generate_captions(audio, tmp_path / "captions", transcriber=transcriber, converter="converter.py")
    except RuntimeError as exc:
        assert "already cached" in str(exc)
        assert "will not download" in str(exc)
    else:
        raise AssertionError("missing cached model must fail with guidance")


def test_cli_entrypoint_imports_project_without_pythonpath(tmp_path):
    audio = tmp_path / "missing-audio.mp3"
    output = tmp_path / "captions"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    completed = subprocess.run(
        [sys.executable, str(HELPER), str(audio), str(output)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Input file not found" in completed.stderr
    assert "No module named 'tools'" not in completed.stderr


def test_caption_conversion_failure_propagates(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(captions.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))

    try:
        captions.generate_captions(audio, tmp_path / "captions", transcriber=FakeTranscriber(_payload(b"audio", "Xin")), converter="converter.py")
    except RuntimeError as exc:
        assert "Strict caption conversion failed" in str(exc)
    else:
        raise AssertionError("strict converter failure must propagate")
