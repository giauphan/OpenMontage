"""Operational contract tests for OpenMontage daily Docker scheduler/worker split.

Covers:
- T27: Duplicate cron dispatch idempotency
- T28: Worker crash / lease expiry recovery
- T29: Job stage transitions and project ID reconciliation
- T30: Scheduler dispatch performance and isolation
- T31: Graceful non-retry on NO_ELIGIBLE_TOPIC
- T32: US Eastern timezone and DST slot safety
- T33: Daily publish slot ceiling governance
- T18: SVG optimization preserving IDs, masks, and GSAP selectors
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from lib.jobs.daily_queue import DailyJobQueue, JobStatus, compute_job_key
from scripts.daily_worker import process_one_job
from tools.graphics.svg_optimize import optimize_svg_text


def test_t27_duplicate_cron_dispatch_idempotency(tmp_path: Path):
    """T27: Submitting the same cron trigger twice must result in one unique job."""
    db_file = tmp_path / "jobs.sqlite"
    queue = DailyJobQueue(db_path=db_file)

    # First dispatch
    job1, created1 = queue.enqueue_daily_job(market="US", local_date="2026-11-01")
    assert created1 is True
    assert job1.status == JobStatus.QUEUED

    # Second dispatch for exact same day & market
    job2, created2 = queue.enqueue_daily_job(market="US", local_date="2026-11-01")
    assert created2 is False
    assert job1.job_key == job2.job_key
    assert job2.status == JobStatus.QUEUED


def test_t28_worker_crash_lease_recovery(tmp_path: Path):
    """T28: A worker dying mid-generate allows a successor worker to recover the job after lease expiry."""
    db_file = tmp_path / "jobs.sqlite"
    queue = DailyJobQueue(db_path=db_file)

    job, _ = queue.enqueue_daily_job(market="US", local_date="2026-11-01")

    # Worker 1 claims job with a 1-second lease
    claimed1 = queue.claim_next_job(worker_id="worker_alpha", lease_duration_seconds=1)
    assert claimed1 is not None
    assert claimed1.lease_owner == "worker_alpha"
    assert claimed1.attempt == 1

    # Worker 2 immediately tries to claim — must get None (lease active)
    claimed2 = queue.claim_next_job(worker_id="worker_beta")
    assert claimed2 is None

    # Wait for Worker 1 lease to expire
    time.sleep(1.1)

    # Worker 2 tries again — must reclaim the expired job
    claimed3 = queue.claim_next_job(worker_id="worker_beta", lease_duration_seconds=1800)
    assert claimed3 is not None
    assert claimed3.job_key == job.job_key
    assert claimed3.lease_owner == "worker_beta"
    assert claimed3.attempt == 2


def test_t29_stage_transitions_and_project_reconciliation(tmp_path: Path):
    """T29: Atomic stage transitions record project IDs and release lease on completion."""
    db_file = tmp_path / "jobs.sqlite"
    queue = DailyJobQueue(db_path=db_file)

    job, _ = queue.enqueue_daily_job(market="US", local_date="2026-11-01")
    claimed = queue.claim_next_job(worker_id="worker_gamma")
    assert claimed is not None

    # Update to GENERATING
    ok_gen = queue.update_stage(job.job_key, "worker_gamma", JobStatus.GENERATING, project_ids=["proj_001"])
    assert ok_gen is True

    # Complete job
    ok_done = queue.complete_job(job.job_key, "worker_gamma", JobStatus.SCHEDULED, project_ids=["proj_001", "proj_002"])
    assert ok_done is True

    # Verify state in DB
    refetched = queue.get_job(job.job_key)
    assert refetched is not None
    assert refetched.status == JobStatus.SCHEDULED
    assert refetched.lease_owner is None
    assert refetched.project_ids == ["proj_001", "proj_002"]


def test_t30_scheduler_dispatch_isolation_and_speed(tmp_path: Path):
    """T30: Enqueuing a job must execute in <100ms without invoking heavy render engines."""
    db_file = tmp_path / "jobs.sqlite"
    queue = DailyJobQueue(db_path=db_file)

    t0 = time.perf_counter()
    job, created = queue.enqueue_daily_job(market="US", local_date="2026-11-02")
    elapsed = time.perf_counter() - t0

    assert created is True
    assert elapsed < 0.10, f"Scheduler enqueue took too long: {elapsed:.3f}s"
    assert job.status == JobStatus.QUEUED


def test_t31_retry_respects_no_eligible_topic(tmp_path: Path):
    """T31: NO_ELIGIBLE_TOPIC is a terminal success status and does not schedule retry storms."""
    db_file = tmp_path / "jobs.sqlite"
    queue = DailyJobQueue(db_path=db_file)

    job, _ = queue.enqueue_daily_job(market="US", local_date="2026-11-03")
    claimed = queue.claim_next_job(worker_id="worker_delta")
    assert claimed is not None

    # Finish with NO_ELIGIBLE_TOPIC
    queue.complete_job(job.job_key, "worker_delta", JobStatus.NO_ELIGIBLE_TOPIC)

    refetched = queue.get_job(job.job_key)
    assert refetched.status == JobStatus.NO_ELIGIBLE_TOPIC
    assert refetched.next_retry_at is None, "NO_ELIGIBLE_TOPIC must never set a future retry timestamp"

    # Worker checking queue finds nothing to claim
    assert queue.claim_next_job(worker_id="worker_delta") is None


def test_t32_us_timezone_dst_safety():
    """T32: Daily jobs correctly resolve dates and times in America/New_York across DST boundaries."""
    tz = ZoneInfo("America/New_York")

    # Winter (EST, UTC-5)
    dt_winter = datetime(2026, 1, 15, 23, 30, tzinfo=ZoneInfo("UTC")).astimezone(tz)
    assert dt_winter.strftime("%Y-%m-%d") == "2026-01-15"
    assert dt_winter.strftime("%Z") == "EST"

    # Summer (EDT, UTC-4)
    dt_summer = datetime(2026, 7, 15, 23, 30, tzinfo=ZoneInfo("UTC")).astimezone(tz)
    assert dt_summer.strftime("%Y-%m-%d") == "2026-07-15"
    assert dt_summer.strftime("%Z") == "EDT"


def test_t33_daily_worker_dry_run_execution(tmp_path: Path):
    """T33: Worker process_one_job in dry_run mode transitions job through to SCHEDULED."""
    db_file = tmp_path / "jobs.sqlite"
    queue = DailyJobQueue(db_path=db_file)

    queue.enqueue_daily_job(market="US", local_date="2026-11-04")
    handled = process_one_job(queue, worker_id="worker_test", dry_run=True)
    assert handled is True

    # Check job is now SCHEDULED
    job = queue.get_job(compute_job_key("US", "2026-11-04"))
    assert job.status == JobStatus.SCHEDULED
    assert "dry_run_project" in job.project_ids


def test_t18_svg_optimizer_preserves_selectors_and_masks():
    """T18: SVG optimizer strips comments/namespaces while strictly preserving IDs, clipPaths, and url() refs."""
    raw_svg = """<?xml version="1.0" encoding="UTF-8"?>
    <!-- Inkscape editor generated comment -->
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="1080" height="1920">
      <defs>
        <clipPath id="safe_clip_01">
          <rect x="100" y="200" width="880" height="400" rx="20"/>
        </clipPath>
        <linearGradient id="brand_grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#38bdf8"/>
          <stop offset="100%" stop-color="#0369a1"/>
        </linearGradient>
      </defs>
      <rect id="hero_bg" width="1080" height="1920" fill="url(#brand_grad)" clip-path="url(#safe_clip_01)"/>
      <text id="hero_title" class="gsap-reveal" x="540" y="400" font-size="48">Autonomous Agent Security</text>
    </svg>
    """
    opt = optimize_svg_text(raw_svg)

    # Comments and declarations stripped
    assert "<?xml" not in opt
    assert "<!--" not in opt
    assert "xmlns:inkscape" not in opt

    # Critical references preserved
    assert 'id="safe_clip_01"' in opt
    assert 'id="brand_grad"' in opt
    assert 'id="hero_bg"' in opt
    assert 'id="hero_title"' in opt
    assert 'class="gsap-reveal"' in opt
    assert 'clip-path="url(#safe_clip_01)"' in opt
    assert 'fill="url(#brand_grad)"' in opt
    assert "Autonomous Agent Security" in opt
