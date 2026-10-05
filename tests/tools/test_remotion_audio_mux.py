import shutil
import subprocess
import math
import wave
import struct
from pathlib import Path
from unittest import mock

import pytest

from tools.video.video_compose import VideoCompose

_ffmpeg_available = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


def _run(command: list[str]) -> None:
    subprocess.run(command, capture_output=True, check=True, timeout=30)


def _make_video(duration_s: float, path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"color=c=red:s=320x180:d={duration_s}:r=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ])


def _make_audio(duration_s: float, path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"sine=frequency=440:duration={duration_s}", str(path),
    ])


def _format_duration(path: Path) -> float:
    duration = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    return float(duration)


def _extract_audio_wav(path: Path, wav_path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-i", str(path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", str(wav_path),
    ])


def _audio_rms_stats(wav_path: Path) -> tuple[float, float, float]:
    """Return (overall_rms, first_half_rms, second_half_rms) for a PCM s16 mono/stereo WAV."""
    with wave.open(str(wav_path), "rb") as wav:
        frames = wav.getnframes()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        assert sample_width == 2, "expected PCM s16 WAV"
        data = wav.readframes(frames)

    total = len(data)
    if total == 0:
        return 0.0, 0.0, 0.0

    def _rms(samples: bytes) -> float:
        count = len(samples) // 2
        if count == 0:
            return 0.0
        values = struct.unpack(f"<{count}h", samples)
        sq_sum = sum(value * value for value in values)
        rms = math.sqrt(sq_sum / count) / 32768.0
        return float(rms)

    overall = _rms(data)
    half = total // 2
    first = _rms(data[:half])
    second = _rms(data[half:])
    return overall, first, second


def _assert_mux_command_is_bounded(mux_cmd: list[str]) -> None:
    assert "-nostdin" in mux_cmd
    assert "-shortest" not in mux_cmd
    assert "-t" in mux_cmd
    # The padding bound is a standalone argument "-af apad=whole_dur=<d>";
    # assert the "apad=whole_dur=" token is present so unbounded padding is rejected.
    assert any("apad=whole_dur=" in token for token in mux_cmd)


@_ffmpeg_available
def test_external_audio_mux_adds_audible_stream_without_changing_video_length(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    _make_video(2.0, video)
    _make_audio(1.0, audio)

    result = VideoCompose()._mux_external_audio(video, audio)

    assert result.success, result.error

    streams = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type", "-of", "csv=p=0", str(video),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()

    duration = _format_duration(video)
    wav = tmp_path / "decoded_audio.wav"
    _extract_audio_wav(video, wav)
    overall_rms, first_half_rms, _second_half_rms = _audio_rms_stats(wav)

    assert "video" in streams
    assert "audio" in streams
    assert duration == pytest.approx(2.0, abs=0.15)
    assert overall_rms > 0.0, "audio should be audible somewhere in the output"
    assert first_half_rms > 0.0, "audio signal should exist in the first half of the video"


@_ffmpeg_available
def test_audio_mux_pads_short_audio_to_video_duration(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    _make_video(2.0, video)
    _make_audio(1.0, audio)

    result = VideoCompose()._mux_external_audio(video, audio)

    assert result.success, result.error
    duration = _format_duration(video)
    assert duration == pytest.approx(2.0, abs=0.15)

    wav = tmp_path / "decoded_audio.wav"
    _extract_audio_wav(video, wav)
    overall_rms, first_half_rms, _second_half_rms = _audio_rms_stats(wav)
    assert first_half_rms > 0.0, "first half should contain the audible sine wave"
    assert _second_half_rms < 0.05, "padded second half should be near-silence"


@_ffmpeg_available
def test_audio_mux_trims_long_audio_to_video_duration(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    _make_video(2.0, video)
    _make_audio(4.0, audio)

    result = VideoCompose()._mux_external_audio(video, audio)

    assert result.success, result.error
    duration = _format_duration(video)
    assert duration == pytest.approx(2.0, abs=0.15)

    wav = tmp_path / "decoded_audio.wav"
    _extract_audio_wav(video, wav)
    overall_rms, first_half_rms, second_half_rms = _audio_rms_stats(wav)
    assert overall_rms > 0.0, "audio should be audible after trimming"
    assert first_half_rms > 0.0 and second_half_rms > 0.0, "both halves should retain the trimmed sine wave"


@_ffmpeg_available
def test_audio_mux_equal_durations_completes_normally(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    _make_video(2.0, video)
    _make_audio(2.0, audio)

    result = VideoCompose()._mux_external_audio(video, audio)

    assert result.success, result.error
    duration = _format_duration(video)
    assert duration == pytest.approx(2.0, abs=0.15)

    wav = tmp_path / "decoded_audio.wav"
    _extract_audio_wav(video, wav)
    overall_rms, _first_half_rms, _second_half_rms = _audio_rms_stats(wav)
    assert overall_rms > 0.0, "audio should be audible throughout the video"


def test_invalid_video_duration_fails_before_mux(tmp_path) -> None:
    """If ffprobe cannot report a valid video stream duration, the mux must abort without touching the video."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video-bytes")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake-audio-bytes")

    compose = VideoCompose()
    with mock.patch.object(
        type(compose),
        "_probe_video_stream_duration",
        side_effect=RuntimeError("No video stream duration reported for fake video"),
    ) as probe_mock:
        with mock.patch.object(
            type(compose),
            "run_command",
            side_effect=AssertionError("mux should not run when duration is unavailable"),
        ) as run_mock:
            result = compose._mux_external_audio(video, audio)

    assert not result.success
    assert "No video stream duration" in result.error
    probe_mock.assert_called_once_with(video)
    run_mock.assert_not_called()
    assert video.read_bytes() == b"fake-video-bytes", "original video should remain unchanged"
    leftover_tmp = list(tmp_path.glob(".video.audio-mux-*.mp4"))
    assert not leftover_tmp, f"temporary mux output was left behind: {leftover_tmp}"


def test_ffmpeg_timeout_leaves_original_intact_and_cleans_temp_output(tmp_path) -> None:
    """When the mux subprocess exceeds its wall-clock limit, original video stays and temp file is removed."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"original-video-bytes")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio-bytes")

    compose = VideoCompose()

    def _raise_timeout(cmd: list[str], *args, **kwargs):
        # Simulate a stalled encode that would otherwise leave a partial output
        # behind. The mux command's final token is the temp output path (its name
        # embeds ".audio-mux-"); write a partial file so the finally block has
        # to clean it up.
        for token in reversed(cmd):
            if ".audio-mux-" in token:
                Path(token).write_bytes(b"partial-output")
                break
        raise subprocess.TimeoutExpired(cmd, 30)

    with mock.patch.object(
        type(compose),
        "_probe_video_stream_duration",
        return_value=2.0,
    ) as probe_mock:
        with mock.patch.object(
            type(compose),
            "run_command",
            side_effect=_raise_timeout,
        ) as run_mock:
            result = compose._mux_external_audio(video, audio)

    assert not result.success
    assert "Audio mux timed out" in result.error
    probe_mock.assert_called_once_with(video)
    run_mock.assert_called_once()
    # Verify command shape: bounded duration + -nostdin + finite timeout
    mux_cmd = run_mock.call_args[0][0]
    _assert_mux_command_is_bounded(mux_cmd)
    assert run_mock.call_args.kwargs["timeout"] == 60
    assert video.read_bytes() == b"original-video-bytes", "original video must survive the timeout"
    leftover_tmp = list(tmp_path.glob(".video.audio-mux-*.mp4"))
    assert not leftover_tmp, f"temporary mux output should be cleaned up: {leftover_tmp}"


def test_non_finite_or_non_positive_video_durations_are_rejected(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    compose = VideoCompose()

    for bad_value in [float("inf"), 0.0, -1.0, float("nan")]:
        with mock.patch.object(
            type(compose),
            "_probe_video_stream_duration",
            side_effect=RuntimeError(f"simulated bad duration {bad_value}"),
        ) as probe_mock:
            with mock.patch.object(
                type(compose),
                "run_command",
                side_effect=AssertionError("mux should not run with invalid duration"),
            ) as run_mock:
                result = compose._mux_external_audio(video, audio)

        assert not result.success
        assert "simulated bad duration" in result.error
        probe_mock.assert_called_once_with(video)
        run_mock.assert_not_called()


def test_probe_rejects_unparseable_or_nonpositive_ffprobe_output(tmp_path) -> None:
    compose = VideoCompose()
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")

    for bad_output in ["N/A", "0", "-1", "inf", "nan", ""]:
        with mock.patch(
            "subprocess.check_output",
            return_value=bad_output,
        ) as check_output_mock:
            with pytest.raises(RuntimeError) as exc_info:
                compose._probe_video_stream_duration(video)

            msg = str(exc_info.value)
            assert (
                "not finite and positive" in msg
                or "No video stream duration" in msg
                or "Unparseable" in msg
            )
            check_output_mock.assert_called_once()


def test_probe_uses_finite_subprocess_timeout(tmp_path) -> None:
    """The ffprobe duration probe itself must carry a finite wall-clock timeout."""
    compose = VideoCompose()
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")

    with mock.patch(
        "subprocess.check_output",
        return_value="3.5",
    ) as check_output_mock:
        duration = compose._probe_video_stream_duration(video)

    assert duration == 3.5
    check_output_mock.assert_called_once()
    assert check_output_mock.call_args.kwargs["timeout"] == 15


def test_non_timeout_mux_failure_preserves_original_and_cleans_temp(tmp_path) -> None:
    """A non-zero ffmpeg exit (not a timeout) also leaves the original intact and removes the temp output."""
    from tools.base_tool import ToolCommandError

    video = tmp_path / "video.mp4"
    video.write_bytes(b"original-video-bytes")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio-bytes")

    compose = VideoCompose()

    def _fail(cmd: list[str], *args, **kwargs):
        for token in reversed(cmd):
            if ".audio-mux-" in token:
                Path(token).write_bytes(b"partial-output")
                break
        raise ToolCommandError(
            1, cmd, output="ffmpeg: error", stderr="simulated encoder failure",
        )

    with mock.patch.object(
        type(compose),
        "_probe_video_stream_duration",
        return_value=2.0,
    ):
        with mock.patch.object(
            type(compose),
            "run_command",
            side_effect=_fail,
        ) as run_mock:
            result = compose._mux_external_audio(video, audio)

    assert not result.success
    assert "Could not mux mixed audio" in result.error
    run_mock.assert_called_once()
    assert video.read_bytes() == b"original-video-bytes", "original video must survive a mux failure"
    leftover_tmp = list(tmp_path.glob(".video.audio-mux-*.mp4"))
    assert not leftover_tmp, f"temporary mux output should be cleaned up: {leftover_tmp}"
