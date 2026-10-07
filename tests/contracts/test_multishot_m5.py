"""M5 multi-shot tests — resume, single-shot retry/regeneration, metrics.

TASK 019–021 + plan §8 observability.

M5 ties the M2 scheduler and M1 continuity/reference engines together into
the resume / single-shot-retry / single-shot-regeneration workflows, and
exercises the §8 metrics aggregator. No provider calls, no paid work.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.multishot_jobs import FakeProvider, JobScheduler, JobSpec
from lib.multishot_metrics import summarize_run, dimension
from lib.multishot_continuity import mark_downstream_stale
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_shot_keyframe,
    invalidate_dependent_jobs,
)


def _spec(shot_id):
    return JobSpec(shot_id=shot_id, prompt="p", prompt_hash="sha256:x",
                   reference_hashes=["sha256:ref"])


class TestResume:
    """TASK 019 — 6-shot crash after shots 1–3 complete; restart reuses them."""

    def _sched(self, tmp_path, max_concurrency=3):
        return JobScheduler(FakeProvider(), dest_dir=str(tmp_path), max_concurrency=max_concurrency,
                            sleep=lambda d: None, download_validator=lambda path, spec: {"valid": True})

    def test_resume_reuses_completed_and_runs_remaining_in_order(self, tmp_path):
        sched = self._sched(tmp_path)
        provider = sched.provider
        specs = [_spec(f"shot_{i:03d}") for i in range(1, 7)]
        completed = {f"shot_{i:03d}": {"file_path": str(tmp_path / f"shot_{i:03d}.mp4"),
                                       "input_hash": _spec(f"shot_{i:03d}").fingerprint(), "content_hash": "sha256:d",
                                       "validation": {"valid": True, "input_hash": _spec(f"shot_{i:03d}").fingerprint(), "content_hash": "sha256:d"}}
                     for i in range(1, 4)}
        for p in completed.values():
            Path(p["file_path"]).write_bytes(b"prior")
            import hashlib
            p["content_hash"] = "sha256:" + hashlib.sha256(b"prior").hexdigest()
            p["validation"]["content_hash"] = p["content_hash"]
        outcomes = sched.run_all(specs, resume=completed)

        # Shots 1–3 reused without re-submission.
        assert [o.status for o in outcomes[:3]] == ["completed"] * 3
        assert provider.submissions_for("shot_001") == []
        # Shots 4–6 freshly submitted.
        assert provider.submissions_for("shot_004") == [1]
        assert provider.submissions_for("shot_005") == [1]
        assert provider.submissions_for("shot_006") == [1]
        # Plan order preserved across resume + fresh mix.
        assert [o.shot_id for o in outcomes] == [f"shot_{i:03d}" for i in range(1, 7)]

    def test_crash_mid_shot_reconciles_running_handle_no_duplicate(self, tmp_path):
        # Prior run submitted shot_004 attempt 1 (handle known) before crash.
        provider = FakeProvider({("shot_004", 1): "ok", ("shot_004", "download"): "ok"})
        sub_before = len(provider.submissions_for("shot_004"))
        sched = JobScheduler(provider, dest_dir=str(tmp_path), sleep=lambda d: None,
                             download_validator=lambda path, spec: {"valid": True})
        outcome = sched.run_one(_spec("shot_004"),
                                resume_handle="handle-shot_004-1", resume_attempts=0)
        assert outcome.status == "completed"
        # No duplicate submit for the already-known in-flight handle.
        assert len(provider.submissions_for("shot_004")) == sub_before


class TestSingleShotRetry:
    """TASK 020 — shot 4 failed transiently; retry only shot 4, others untouched."""

    def test_retry_only_failed_shot(self, tmp_path):
        provider = FakeProvider({("shot_004", 1): "PROVIDER_5XX", ("shot_004", 2): "ok", ("shot_004", "download"): "ok"})
        sched = JobScheduler(provider, dest_dir=str(tmp_path), sleep=lambda d: None,
                             download_validator=lambda path, spec: {"valid": True})
        outcome = sched.run_one(_spec("shot_004"))
        assert outcome.status == "completed"
        assert len(outcome.attempts) == 2
        assert provider.submissions_for("shot_004") == [1, 2]
        # Unrelated shots were never touched.
        assert provider.submissions_for("shot_001") == []


class TestRegeneration:
    """TASK 021 — regenerate one shot, preserve locks, mark downstream stale."""

    def test_regenerate_earlier_shot_marks_downstream_stale(self):
        shot_orders = {f"shot_{i:03d}": i for i in range(1, 7)}
        stale = mark_downstream_stale(shot_orders, "shot_003")
        assert stale == ["shot_004", "shot_005", "shot_006"]

    def test_regenerate_last_shot_marks_nothing(self):
        shot_orders = {f"shot_{i:03d}": i for i in range(1, 7)}
        assert mark_downstream_stale(shot_orders, "shot_006") == []

    def test_charactermaster_change_invalidates_derived_keyframes(self, tmp_path):
        store = new_reference_store()
        master = tmp_path / "char_master.png"
        Image.new("RGB", (2, 2), "red").save(master)
        register_character_master(store, "char_mochi", master)
        for i in range(1, 4):
            kf = tmp_path / f"kf_{i:03d}.png"
            Image.new("RGB", (2, 2), "blue").save(kf)
            register_shot_keyframe(store, f"shot_{i:03d}", kf,
                                   derived_from_character="char_mochi")
        invalidated = invalidate_dependent_jobs(store, "character_master:char_mochi")
        assert invalidated == {"shot_001", "shot_002", "shot_003"}


class TestMetrics:
    """Plan §8 — the run summary exposes the required observability fields."""

    def _outcomes(self, tmp_path):
        provider = FakeProvider({("shot_001", 1): "RATE_LIMIT", ("shot_001", 2): "ok",
                                 ("shot_002", 1): "ok"})
        sched = JobScheduler(provider, dest_dir=str(tmp_path), sleep=lambda d: None,
                             download_validator=lambda path, spec: {"valid": True})
        return sched.run_all([_spec("shot_001"), _spec("shot_002")])

    def test_summary_has_required_metric_fields(self, tmp_path):
        outcomes = self._outcomes(tmp_path)
        m = summarize_run(outcomes, planning_time_sec=12.0,
                          total_raw_duration_sec=30.0, final_duration_sec=30.1)
        for key in ("project_total_time_sec", "planning_time_sec",
                    "avg_generation_time_per_shot_sec", "attempts_per_shot",
                    "provider_failure_count", "total_raw_duration_sec",
                    "final_duration_sec"):
            assert key in m, f"missing metric {key}"
        assert m["shots"] == 2
        assert m["shots_completed"] == 2
        assert m["provider_failure_count"] == 1
        assert m["provider_failures_by_code"]["RATE_LIMIT"] == 1

    def test_dimension_labels(self):
        d = dimension(provider="acme", model="m1", project_id="p9",
                      shot_id="shot_004", error_type="RATE_LIMIT")
        assert d == {"provider": "acme", "model": "m1", "project_id": "p9",
                     "shot_id": "shot_004", "error_type": "RATE_LIMIT"}
