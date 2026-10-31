#!/usr/bin/env python3
"""Lightweight cron dispatch entrypoint for daily OpenMontage runs.

Runs in the low-resource scheduler container (0.5 CPU / 2GB RAM).
Does NOT perform video rendering, TTS, or browser automation.
Atomically enqueues a daily job record into data/daily_jobs.sqlite and exits.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add workspace root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.jobs.daily_queue import DailyJobQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cron_dispatch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue daily OpenMontage video job.")
    parser.add_argument("--market", default=os.environ.get("OPENMONTAGE_MARKET", "US"), help="Market identifier (US, VN)")
    parser.add_argument("--timezone", default=os.environ.get("PUBLISH_TZ", "America/New_York"), help="Target timezone")
    parser.add_argument("--date", default="", help="Override local date (YYYY-MM-DD)")
    parser.add_argument("--db-path", default=os.environ.get("DAILY_JOBS_DB", "data/daily_jobs.sqlite"), help="Path to jobs SQLite DB")
    args = parser.parse_args()

    tz = ZoneInfo(args.timezone)
    local_date = args.date or datetime.now(tz).strftime("%Y-%m-%d")

    logger.info("Initializing daily job dispatch for market=%s date=%s tz=%s", args.market, local_date, args.timezone)
    queue = DailyJobQueue(db_path=args.db_path)

    job, created = queue.enqueue_daily_job(
        market=args.market,
        local_date=local_date,
        timezone=args.timezone,
        job_type="daily_news_explainer",
        pipeline_version="v2.0",
        content_batch="daily",
    )

    if created:
        logger.info("Successfully enqueued NEW job: key=%s status=%s", job.job_key, job.status.value)
    else:
        logger.info("Job ALREADY EXISTS (idempotent no-op): key=%s status=%s attempt=%d", job.job_key, job.status.value, job.attempt)

    return 0


if __name__ == "__main__":
    sys.exit(main())
