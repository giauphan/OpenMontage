"""Tests for strict resume integrity in JobScheduler."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from lib.multishot_jobs import (
    FakeProvider,
    JobScheduler,
    JobSpec,
    MultishotValidationError,
    file_hash,
)

def _spec(shot_id="shot_001"):
    return JobSpec(
        shot_id=shot_id,
        prompt="A nice test video.",
        prompt_hash="sha256:fake",
        duration_sec=1,
    )

@pytest.fixture
def video(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Requires ffmpeg and ffprobe")
    path = tmp_path / "integrity_fixture.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=64x64:r=10:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
    return path

class TestResumeIntegrity:
    def test_path_only_external_completion_rejected(self, tmp_path, video):
        # A resume intent that lacks original hashes and validation must fail closed.
        sched = JobScheduler(FakeProvider(), dest_dir=str(tmp_path))
        spec = _spec()
        digest = file_hash(video)
        resume_data = {
            spec.shot_id: {
                "file_path": str(video),
                "content_hash": digest,
                "validation": {"valid": True, "content_hash": digest, "input_hash": spec.fingerprint()}
                # Intentionally omitting input_hash
            }
        }
        outcome = sched.run_all([spec], resume=resume_data)[0]
        assert outcome.status == "failed"
        assert outcome.error_code == "INVALID_INPUT"

    def test_missing_validation_fails_resume(self, tmp_path, video):
        sched = JobScheduler(FakeProvider(), dest_dir=str(tmp_path))
        spec = _spec()
        digest = file_hash(video)
        inputs = spec.fingerprint()
        resume_data = {
            spec.shot_id: {
                "file_path": str(video),
                "content_hash": digest,
                "input_hash": inputs,
            }
        }
        outcome = sched.run_all([spec], resume=resume_data)[0]
        assert outcome.status == "failed"

    def test_mismatched_input_hash_fails_resume(self, tmp_path, video):
        sched = JobScheduler(FakeProvider(), dest_dir=str(tmp_path))
        spec = _spec()
        digest = file_hash(video)
        wrong_inputs = "sha256:wrong"
        resume_data = {
            spec.shot_id: {
                "file_path": str(video),
                "content_hash": digest,
                "input_hash": wrong_inputs,
                "validation": {"valid": True, "content_hash": digest, "input_hash": wrong_inputs}
            }
        }
        outcome = sched.run_all([spec], resume=resume_data)[0]
        assert outcome.status == "failed"

    def test_mismatched_content_hash_fails_resume(self, tmp_path, video):
        sched = JobScheduler(FakeProvider(), dest_dir=str(tmp_path))
        spec = _spec()
        wrong_digest = "sha256:wrong"
        inputs = spec.fingerprint()
        resume_data = {
            spec.shot_id: {
                "file_path": str(video),
                "content_hash": wrong_digest,
                "input_hash": inputs,
                "validation": {"valid": True, "content_hash": wrong_digest, "input_hash": inputs}
            }
        }
        outcome = sched.run_all([spec], resume=resume_data)[0]
        assert outcome.status == "failed"

    def test_corrupted_video_fails_resume(self, tmp_path, video):
        sched = JobScheduler(FakeProvider(), dest_dir=str(tmp_path))
        spec = _spec()
        corrupt_video = tmp_path / "corrupt.mp4"
        corrupt_video.write_bytes(b"not a video but nonempty")

        digest = file_hash(corrupt_video)
        inputs = spec.fingerprint()
        resume_data = {
            spec.shot_id: {
                "file_path": str(corrupt_video),
                "content_hash": digest,
                "input_hash": inputs,
                "validation": {"valid": True, "content_hash": digest, "input_hash": inputs}
            }
        }
        outcome = sched.run_all([spec], resume=resume_data)[0]
        assert outcome.status == "failed"
        assert outcome.error_code == "CORRUPT_OUTPUT"

    def test_same_job_download_retry_on_corruption(self, tmp_path, video):
        import shutil
        class CorruptionProvider(FakeProvider):
            def __init__(self, expected_video):
                super().__init__()
                self.expected = expected_video
                self.dl_count = 0

            def download(self, handle, dest_dir):
                self.dl_count += 1
                target = Path(dest_dir) / "output.mp4"
                target.parent.mkdir(parents=True, exist_ok=True)
                if self.dl_count == 1:
                    target.write_bytes(b"corrupted partial download")
                else:
                    shutil.copyfile(self.expected, target)
                return str(target)

        provider = CorruptionProvider(video)
        # Using 0 delays for fast test
        sched = JobScheduler(provider, dest_dir=str(tmp_path), max_attempts=3, sleep=lambda d: None)
        spec = _spec()
        outcome = sched.run_one(spec)

        # After first corrupt download it should retry download inside the same job and succeed
        assert provider.dl_count == 2
        assert len(provider.submissions_for(spec.shot_id)) == 1
        assert outcome.status == "completed"
        assert outcome.file_path is not None
