import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_vn_subtitles.py"
spec = importlib.util.spec_from_file_location("vn_subtitles", SCRIPT)
subtitles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subtitles)


def test_estimated_timings_fit_duration_and_limits():
    cues, words = subtitles.estimate_subtitles("mot hai ba bon nam", 1.25, max_words=2)
    assert words[-1]["end"] == 1.25
    assert all(0 <= word["start"] < word["end"] <= 1.25 for word in words)
    assert all(len(cue["text"].split()) <= 2 for cue in cues)
    assert all(cue["end"] - cue["start"] <= 4 for cue in cues)


@pytest.mark.parametrize("bad_words", [0, -1])
def test_rejects_invalid_max_words(bad_words):
    with pytest.raises(ValueError, match="positive integer"):
        subtitles.estimate_subtitles("xin", 1, max_words=bad_words)
    digest = "a" * 64
    transcript = {"timing_source": "asr", "audio_sha256": digest, "language": "vi",
                  "word_timestamps": [{"word": "xin", "start": 0, "end": .2}]}
    with pytest.raises(ValueError, match="positive integer"):
        subtitles.aligned_subtitles(transcript, digest, 1, max_words=bad_words)


def test_rejects_overlapping_and_nonfinite_word_timings():
    digest = "a" * 64
    for pair in (({"word": "xin", "start": 0, "end": .5}, {"word": "chao", "start": .4, "end": .7}),
                 ({"word": "xin", "start": 0, "end": float("inf")},)):
        transcript = {"timing_source": "asr", "audio_sha256": digest, "language": "vi",
                      "word_timestamps": list(pair)}
        with pytest.raises(ValueError, match="finite, chronological"):
            subtitles.aligned_subtitles(transcript, digest, 1)


def test_srt_rounding_carries_millisecond_overflow():
    assert "00:00:01,000" in subtitles.format_srt([{"number": 1, "start": .9996, "end": 1.0, "text": "xin"}])


def test_aligned_preserves_times_and_rejects_mismatch_or_invalid():
    digest = "a" * 64
    transcript = {"timing_source": "asr", "audio_sha256": digest, "language": "vi",
                  "word_timestamps": [{"word": "xin", "start": .127, "end": .391}]}
    _, words = subtitles.aligned_subtitles(transcript, digest, 1)
    assert words == transcript["word_timestamps"]
    with pytest.raises(ValueError, match="does not match"):
        subtitles.aligned_subtitles(transcript, "b" * 64, 1)
    transcript["word_timestamps"][0]["end"] = 1.1
    with pytest.raises(ValueError, match="within audio"):
        subtitles.aligned_subtitles(transcript, digest, 1)


def test_cli_rejects_stale_transcript_and_probe_failure_without_overwrite(tmp_path, monkeypatch):
    text = tmp_path / "text.txt"
    audio = tmp_path / "audio.wav"
    transcript_file = tmp_path / "transcript.json"
    output = tmp_path / "captions.srt"
    text.write_text("xin chao", encoding="utf-8")
    audio.write_bytes(b"audio bytes")
    output.write_text("previous", encoding="utf-8")
    transcript_file.write_text(json.dumps({"timing_source": "asr", "audio_sha256": "stale",
                                           "language": "vi", "word_timestamps": []}), encoding="utf-8")
    monkeypatch.setattr(subtitles, "get_audio_duration", lambda _: 2.0)
    assert subtitles.main([str(text), str(audio), str(output), "--transcript-json", str(transcript_file)]) == 1
    assert output.read_text(encoding="utf-8") == "previous"
    monkeypatch.setattr(subtitles, "get_audio_duration", lambda _: (_ for _ in ()).throw(ValueError("probe failed")))
    assert subtitles.main([str(text), str(audio), str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "previous"


def test_cli_requires_alignment_and_keeps_aligned_word_times(tmp_path, monkeypatch):
    text, audio, output, report = (tmp_path / name for name in ("text.txt", "audio.wav", "out.srt", "times.json"))
    transcript_file = tmp_path / "transcript.json"
    text.write_text("Xin chao!", encoding="utf-8")
    audio.write_bytes(b"audio")
    output.write_text("previous", encoding="utf-8")
    monkeypatch.setattr(subtitles, "get_audio_duration", lambda _: 1.0)
    assert subtitles.main([str(text), str(audio), str(output), "--require-aligned"]) == 1
    assert output.read_text(encoding="utf-8") == "previous"
    timestamp = {"word": "Xin", "start": .123, "end": .456}
    transcript_file.write_text(json.dumps({"timing_source": "asr", "audio_sha256": hashlib.sha256(b"audio").hexdigest(),
                                           "language": "vi", "word_timestamps": [timestamp]}), encoding="utf-8")
    assert subtitles.main([str(text), str(audio), str(output), "--transcript-json", str(transcript_file),
                           "--output-json", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["word_timestamps"] == [timestamp]
    assert data["script_matches_transcript"] is False
    assert data["timing_verified"] is False
    assert "00:00:00,123 --> 00:00:00,456" in output.read_text(encoding="utf-8")


def test_cli_marks_asr_derived_text_comparison_unavailable(tmp_path, monkeypatch):
    text, audio, output, report = (tmp_path / name for name in ("asr.txt", "audio.wav", "out.srt", "times.json"))
    transcript_file = tmp_path / "transcript.json"
    audio.write_bytes(b"audio")
    text.write_text("same words", encoding="utf-8")
    transcript_file.write_text(json.dumps({
        "timing_source": "asr",
        "audio_sha256": hashlib.sha256(b"audio").hexdigest(),
        "language": "vi",
        "word_timestamps": [
            {"word": "same", "start": 0.1, "end": 0.3},
            {"word": "words", "start": 0.4, "end": 0.7},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(subtitles, "get_audio_duration", lambda _: 1.0)

    assert subtitles.main([
        str(text), str(audio), str(output), "--output-json", str(report),
        "--transcript-json", str(transcript_file), "--require-aligned",
        "--no-script-comparison",
    ]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["script_matches_transcript"] is None
    assert data["script_comparison_available"] is False
    assert data["timing_verified"] is False


def test_cli_emits_estimated_provenance(tmp_path, monkeypatch):
    text = tmp_path / "text.txt"
    audio = tmp_path / "audio.wav"
    out = tmp_path / "captions.srt"
    report = tmp_path / "timings.json"
    text.write_text("mot hai", encoding="utf-8")
    audio.write_bytes(b"audio")
    monkeypatch.setattr(subtitles, "get_audio_duration", lambda _: 1.0)
    assert subtitles.main([str(text), str(audio), str(out), "--output-json", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["timing_source"] == "estimated"
    assert data["timing_verified"] is False
    assert data["audio_sha256"] == hashlib.sha256(b"audio").hexdigest()
