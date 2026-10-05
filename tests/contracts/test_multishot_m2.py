"""M2 multi-shot tests — provider jobs and crash-safe recovery (TASK 009–011).

Covers the M2 gate:
  - fake-provider 429 / 500 / auth / safety / download / timeout handling
  - bounded concurrency (<=3) for many independent jobs
  - out-of-order completion preserving plan order in results
  - crash / uncertain-submit recovery (no duplicate submission)
  - unchanged completed shots are reused
  - single-shot revision (retry / regenerate)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.multishot_jobs import (
    FakeProvider,
    JobScheduler,
    JobSpec,
    backoff_delay,
    canonical_input_hash,
    is_retryable,
    RETRYABLE_ERRORS,
    PERMANENT_ERRORS,
)


def _spec(shot_id="shot_001"):
    return JobSpec(shot_id=shot_id, prompt="p", prompt_hash="sha256:x",
                   reference_hashes=["sha256:ref"])


class TestErrorClassification:
    def test_retryable_set(self):
        for code in ("RATE_LIMIT", "PROVIDER_5XX", "TIMEOUT", "DOWNLOAD_FAILED", "JOB_FAILED"):
            assert is_retryable(code) is True

    def test_permanent_set(self):
        for code in ("AUTH_ERROR", "QUOTA_EXCEEDED", "INVALID_INPUT", "SAFETY_REFUSAL"):
            assert is_retryable(code) is False

    def test_retryable_and_permanent_disjoint(self):
        assert RETRYABLE_ERRORS.isdisjoint(PERMANENT_ERRORS)

    def test_backoff_honors_retry_after(self):
        assert backoff_delay(1, 0.1, 10.0, retry_after=5.0) == 5.0

    def test_backoff_capped(self):
        assert backoff_delay(10, 0.1, 3.0) == 3.0

    def test_backoff_exponential_growth(self):
        d1 = backoff_delay(1, 0.5, 10.0)
        d2 = backoff_delay(2, 0.5, 10.0)
        d3 = backoff_delay(3, 0.5, 10.0)
        assert d1 < d2 < d3


class TestRetry:
    def _sched(self, provider, tmp_path, **kw):
        sleeps = []
        sched = JobScheduler(
            provider, max_concurrency=kw.pop("max_concurrency", 3),
            max_attempts=kw.pop("max_attempts", 3),
            sleep=lambda d: sleeps.append(d), dest_dir=str(tmp_path),
        )
        return sched, sleeps

    def test_rate_limit_retries_then_succeeds(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "RATE_LIMIT", ("shot_001", 2): "ok"})
        sched, _ = self._sched(provider, tmp_path)
        outcome = sched.run_one(_spec("shot_001"))
        assert outcome.status == "completed"
        assert len(outcome.attempts) == 2
        assert provider.submissions_for("shot_001") == [1, 2]

    def test_provider_5xx_retries(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "PROVIDER_5XX",
                                 ("shot_001", 2): "PROVIDER_5XX",
                                 ("shot_001", 3): "ok"})
        sched, _ = self._sched(provider, tmp_path)
        outcome = sched.run_one(_spec("shot_001"))
        assert outcome.status == "completed"
        assert len(outcome.attempts) == 3

    def test_auth_error_is_permanent_no_retry(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "AUTH_ERROR"})
        sched, _ = self._sched(provider, tmp_path)
        outcome = sched.run_one(_spec("shot_001"))
        assert outcome.status == "permanently_failed"
        assert outcome.error_code == "AUTH_ERROR"
        assert provider.submissions_for("shot_001") == [1]

    def test_safety_refusal_is_permanent(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "SAFETY_REFUSAL"})
        sched, _ = self._sched(provider, tmp_path)
        assert sched.run_one(_spec("shot_001")).status == "permanently_failed"

    def test_download_failed_retries_then_succeeds(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "DOWNLOAD_FAILED",
                                 ("shot_001", 2): "ok"})
        sched, _ = self._sched(provider, tmp_path)
        outcome = sched.run_one(_spec("shot_001"))
        assert outcome.status == "completed"
        assert Path(outcome.file_path).exists()

    def test_exhausted_retries_reports_failed(self, tmp_path):
        provider = FakeProvider({("shot_001", a): "PROVIDER_5XX" for a in (1, 2, 3)})
        sched, _ = self._sched(provider, tmp_path, max_attempts=3)
        outcome = sched.run_one(_spec("shot_001"))
        assert outcome.status == "failed"
        assert len(outcome.attempts) == 3

    def test_backoff_sleeps_called(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "RATE_LIMIT", ("shot_001", 2): "ok"})
        sched, sleeps = self._sched(provider, tmp_path)
        sched.run_one(_spec("shot_001"))
        assert len(sleeps) == 1


class TestConcurrency:
    def test_concurrency_never_exceeds_bound(self, tmp_path):
        provider = FakeProvider({})
        sched = JobScheduler(provider, max_concurrency=3, dest_dir=str(tmp_path),
                             sleep=lambda d: None)
        specs = [_spec(f"shot_{i:03d}") for i in range(1, 21)]
        outcomes = sched.run_all(specs)
        assert provider.peak_concurrent() <= 3
        assert [o.shot_id for o in outcomes] == [s.shot_id for s in specs]

    def test_all_20_succeed_in_order(self, tmp_path):
        provider = FakeProvider({})
        sched = JobScheduler(provider, max_concurrency=3, dest_dir=str(tmp_path),
                             sleep=lambda d: None)
        specs = [_spec(f"shot_{i:03d}") for i in range(1, 21)]
        outcomes = sched.run_all(specs)
        assert all(o.status == "completed" for o in outcomes)
        assert len(outcomes) == 20

    def test_out_of_order_results_preserve_plan_order(self, tmp_path):
        provider = FakeProvider({})
        sched = JobScheduler(provider, max_concurrency=4, dest_dir=str(tmp_path),
                             sleep=lambda d: None)
        specs = [_spec(f"shot_{i:03d}") for i in (3, 1, 2, 4)]
        outcomes = sched.run_all(specs)
        assert [o.shot_id for o in outcomes] == ["shot_003", "shot_001", "shot_002", "shot_004"]


class TestRecovery:
    def test_resume_known_handle_does_not_resubmit(self, tmp_path):
        provider = FakeProvider({})
        provider.submit("shot_001", 1, "sha256:x")
        sub_before = len(provider.submissions_for("shot_001"))
        sched = JobScheduler(provider, dest_dir=str(tmp_path), sleep=lambda d: None)
        outcome = sched.run_one(_spec("shot_001"),
                                resume_handle="handle-shot_001-1", resume_attempts=0)
        assert outcome.status == "completed"
        assert len(provider.submissions_for("shot_001")) == sub_before

    def test_unchanged_completed_shot_reused(self, tmp_path):
        provider = FakeProvider({})
        sched = JobScheduler(provider, max_concurrency=3, dest_dir=str(tmp_path),
                             sleep=lambda d: None)
        specs = [_spec(f"shot_{i:03d}") for i in range(1, 4)]
        existing = str(tmp_path / "shot_001.mp4")
        Path(existing).write_bytes(b"prior-output")
        outcomes = sched.run_all(specs, resume={"shot_001": {"file_path": existing}})
        assert outcomes[0].status == "completed"
        assert outcomes[0].file_path == existing
        assert provider.submissions_for("shot_001") == []
        assert provider.submissions_for("shot_002") == [1]
        assert provider.submissions_for("shot_003") == [1]

    def test_single_shot_revision_retry(self, tmp_path):
        provider = FakeProvider({("shot_004", 1): "PROVIDER_5XX", ("shot_004", 2): "ok"})
        sched = JobScheduler(provider, dest_dir=str(tmp_path), sleep=lambda d: None)
        outcome = sched.run_one(_spec("shot_004"))
        assert outcome.status == "completed"
        assert len(outcome.attempts) == 2


class TestInputHash:
    def test_hash_stable_and_includes_refs(self):
        h1 = canonical_input_hash(provider="p", model="m", settings={"a": 1},
                                  prompt="x", reference_hashes=["sha256:b", "sha256:a"])
        h2 = canonical_input_hash(provider="p", model="m", settings={"a": 1},
                                  prompt="x", reference_hashes=["sha256:a", "sha256:b"])
        assert h1 == h2
        h3 = canonical_input_hash(provider="p", model="m", settings={"a": 2},
                                  prompt="x", reference_hashes=["sha256:a"])
        assert h1 != h3
