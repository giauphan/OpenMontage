#!/usr/bin/env python3
"""Durable worker execution daemon for OpenMontage daily jobs.

Runs on the dedicated worker container (1.75 CPU / 4GB RAM).
Claims jobs from data/daily_jobs.sqlite, maintains a background heartbeat,
executes the daily pipeline with full resource isolation, and marks results.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.jobs.daily_queue import DailyJobQueue, JobStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("daily_worker")


class HeartbeatThread(threading.Thread):
    def __init__(self, queue: DailyJobQueue, job_key: str, worker_id: str, interval_seconds: int = 60) -> None:
        super().__init__(daemon=True)
        self.queue = queue
        self.job_key = job_key
        self.worker_id = worker_id
        self.interval = interval_seconds
        self.stopped = threading.Event()

    def run(self) -> None:
        while not self.stopped.wait(self.interval):
            success = self.queue.heartbeat(self.job_key, self.worker_id)
            if not success:
                logger.warning("Heartbeat extension failed for job %s (lease lost)", self.job_key)
                break

    def stop(self) -> None:
        self.stopped.set()


def process_one_job(queue: DailyJobQueue, worker_id: str, dry_run: bool = False) -> bool:
    job = queue.claim_next_job(worker_id)
    if not job:
        return False

    logger.info("Claimed job %s for market=%s date=%s (attempt %d)", job.job_key, job.market, job.local_date, job.attempt)
    heartbeat = HeartbeatThread(queue, job.job_key, worker_id)
    heartbeat.start()

    try:
        queue.update_stage(job.job_key, worker_id, JobStatus.GENERATING)

        if dry_run:
            logger.info("[Dry Run] Simulating pipeline execution for job %s", job.job_key)
            time.sleep(1)
            queue.complete_job(job.job_key, worker_id, JobStatus.SCHEDULED, project_ids=["dry_run_project"])
            return True

        # Run pipeline runner with environment overrides
        env = os.environ.copy()
        env["OPENMONTAGE_MARKET"] = job.market
        env["PUBLISH_TZ"] = job.timezone
        env["DAILY_JOB_KEY"] = job.job_key
        env["DAILY_JOB_QUEUE_ENABLED"] = "1"

        runner_script = ROOT / "scripts" / "run_daily_news_pipeline.sh"
        cmd = ["bash", str(runner_script)]

        logger.info("Spawning daily pipeline execution: %s", " ".join(cmd))
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(ROOT))

        if proc.returncode == 0:
            logger.info("Pipeline completed successfully for job %s", job.job_key)
            queue.complete_job(job.job_key, worker_id, JobStatus.SCHEDULED, run_logs=proc.stdout[-2000:])
            return True
        elif "NO_ELIGIBLE_TOPIC" in proc.stdout or "NO_ELIGIBLE_TOPIC" in proc.stderr:
            logger.info("Pipeline finished with NO_ELIGIBLE_TOPIC for job %s", job.job_key)
            queue.complete_job(job.job_key, worker_id, JobStatus.NO_ELIGIBLE_TOPIC, run_logs=proc.stdout[-2000:])
            return True
        else:
            logger.error("Pipeline failed with exit code %d: %s", proc.returncode, proc.stderr[-500:])
            queue.fail_job(job.job_key, worker_id, error_code=f"EXIT_{proc.returncode}", retryable=True, run_logs=proc.stderr[-2000:])
            return False

    except Exception as exc:
        logger.exception("Unexpected exception in worker job %s: %s", job.job_key, exc)
        queue.fail_job(job.job_key, worker_id, error_code="WORKER_EXCEPTION", retryable=False, run_logs=str(exc))
        return False
    finally:
        heartbeat.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily job consumer worker daemon.")
    parser.add_argument("--worker-id", default=f"worker_{os.getpid()}", help="Worker identifier")
    parser.add_argument("--db-path", default=os.environ.get("DAILY_JOBS_DB", "data/daily_jobs.sqlite"), help="Jobs database path")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without running pipeline")
    args = parser.parse_args()

    queue = DailyJobQueue(db_path=args.db_path)
    logger.info("Daily worker %s started, listening on db=%s", args.worker_id, args.db_path)

    if args.once:
        handled = process_one_job(queue, args.worker_id, dry_run=args.dry_run)
        logger.info("Worker once-mode finished (handled=%s)", handled)
        return 0

    while True:
        handled = process_one_job(queue, args.worker_id, dry_run=args.dry_run)
        if not handled:
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
