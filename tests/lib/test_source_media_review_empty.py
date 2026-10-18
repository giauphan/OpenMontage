"""Regression test for source_media_review empty-files artifact validity.

review_source_media deliberately returns an artifact with files:[] when no user
media was supplied (or none could be reviewed) — a valid "fully generated
production" state. The schema declared files.minItems: 1, so that intended
artifact failed its own schema validation.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.source_media_review import review_source_media  # noqa: E402
from schemas.artifacts import validate_artifact  # noqa: E402


def test_no_source_media_produces_schema_valid_artifact(tmp_path):
    art = review_source_media([tmp_path / "does-not-exist.mp4"], {})
    assert art["files"] == []
    # Must not raise — this is a legitimate no-source-media artifact.
    validate_artifact("source_media_review", art)


def test_no_files_at_all_is_schema_valid():
    art = review_source_media([], {})
    assert art["files"] == []
    validate_artifact("source_media_review", art)


def test_video_probe_with_frame_sampler_and_transcriber(tmp_path):
    dummy_video = tmp_path / "test.mp4"
    dummy_video.write_bytes(b"dummy")

    class DummyResult:
        def __init__(self, success, data):
            self.success = success
            self.data = data

    class DummyFrameSampler:
        def execute(self, params):
            assert params["strategy"] == "timestamps"
            assert "timestamps" in params
            return DummyResult(True, {"frames": [{"path": "/tmp/f1.jpg", "timestamp_seconds": 0.5}]})

    class DummyTranscriber:
        def get_status(self):
            from tools.base_tool import ToolStatus
            return ToolStatus.AVAILABLE

        def execute(self, params):
            return DummyResult(True, {"segments": [{"text": "Hello world from transcript"}]})

    class DummyProbe:
        def execute(self, params):
            return DummyResult(True, {
                "duration_seconds": 10.0,
                "resolution": "1920x1080",
                "codec": "h264",
                "audio_codec": "aac",
                "channels": 2,
            })

    class DummyRegistry:
        def get(self, name):
            if name == "audio_probe":
                return DummyProbe()
            if name == "frame_sampler":
                return DummyFrameSampler()
            if name == "transcriber":
                return DummyTranscriber()
            return None

    art = review_source_media([dummy_video], {}, tool_registry=DummyRegistry())
    assert len(art["files"]) == 1
    f = art["files"][0]
    assert f["representative_frames"] == ["/tmp/f1.jpg"]
    assert "Hello world from transcript" in f["transcript_summary"]
    validate_artifact("source_media_review", art)

