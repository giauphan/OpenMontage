"""Durable daily job queue for OpenMontage scheduler/worker split.

Stores job state in SQLite on a shared persistent mount (data/daily_jobs.sqlite).
Guarantees idempotent enqueuing, lease management with heartbeat, atomic transitions,
and crash recovery without mounting Docker sockets.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    READY_TO_QUEUE = "READY_TO_QUEUE"
    SCHEDULED = "SCHEDULED"
    PRIVATE_CANARY = "PRIVATE_CANARY"
    NO_ELIGIBLE_TOPIC = "NO_ELIGIBLE_TOPIC"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    QUARANTINED = "QUARANTINED"


@dataclass
class DailyJob:
    job_key: str
    job_type: str
    market: str
    local_date: str
    timezone: str
    status: JobStatus
    attempt: int
    created_at_utc: float
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    heartbeat_at: float | None = None
    project_ids: list[str] | None = None
    last_error_code: str | None = None
    source_commit: str | None = None
    config_hash: str | None = None
    run_logs: str | None = None
    next_retry_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_key": self.job_key,
            "job_type": self.job_type,
            "market": self.market,
            "local_date": self.local_date,
            "timezone": self.timezone,
            "status": self.status.value,
            "attempt": self.attempt,
            "created_at_utc": self.created_at_utc,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
            "project_ids": self.project_ids or [],
            "last_error_code": self.last_error_code,
            "source_commit": self.source_commit,
            "config_hash": self.config_hash,
            "run_logs": self.run_logs,
            "next_retry_at": self.next_retry_at,
        }


def compute_job_key(
    market: str,
    local_date: str,
    pipeline_version: str = "v2.0",
    content_batch: str = "daily",
) -> str:
    """Deterministically compute a composite SHA256 key for a daily run."""
    raw = f"{market.strip().upper()}|{local_date.strip()}|{pipeline_version.strip()}|{content_batch.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DailyJobQueue:
    """Persistent SQLite job queue with lease-based concurrency governance."""

    def __init__(self, db_path: Path | str = "data/daily_jobs.sqlite") -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_jobs (
                    job_key TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    market TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    created_at_utc REAL NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    heartbeat_at REAL,
                    project_ids_json TEXT,
                    last_error_code TEXT,
                    source_commit TEXT,
                    config_hash TEXT,
                    run_logs TEXT,
                    next_retry_at REAL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_lease ON daily_jobs(status, lease_expires_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_date ON daily_jobs(market, local_date);")
            conn.commit()

    def enqueue_daily_job(
        self,
        market: str = "US",
        local_date: str = "",
        timezone: str = "America/New_York",
        job_type: str = "daily_news_explainer",
        pipeline_version: str = "v2.0",
        content_batch: str = "daily",
        source_commit: str = "",
        config_hash: str = "",
    ) -> tuple[DailyJob, bool]:
        """Idempotently enqueue a daily job.
        
        Returns:
            (job, created): where created is True if newly inserted, False if already present.
        """
        if not local_date:
            raise ValueError("local_date must be provided (YYYY-MM-DD)")

        key = compute_job_key(market, local_date, pipeline_version, content_batch)
        now = time.time()

        with self._get_connection() as conn:
            # Check existing
            cur = conn.execute("SELECT * FROM daily_jobs WHERE job_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return self._row_to_job(row), False

            # Insert new
            conn.execute(
                """
                INSERT INTO daily_jobs (
                    job_key, job_type, market, local_date, timezone, status, attempt,
                    created_at_utc, project_ids_json, source_commit, config_hash
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, '[]', ?, ?)
                """,
                (
                    key,
                    job_type,
                    market.upper(),
                    local_date,
                    timezone,
                    JobStatus.QUEUED.value,
                    now,
                    source_commit,
                    config_hash,
                ),
            )
            conn.commit()

            cur = conn.execute("SELECT * FROM daily_jobs WHERE job_key = ?", (key,))
            return self._row_to_job(cur.fetchone()), True

    def claim_next_job(
        self,
        worker_id: str,
        lease_duration_seconds: int = 1800,
        allowed_markets: list[str] | None = None,
    ) -> DailyJob | None:
        """Atomically claim the next queued or expired job with lease ownership."""
        now = time.time()
        lease_expires = now + lease_duration_seconds

        with self._get_connection() as conn:
            # Find eligible candidate:
            # 1. QUEUED and not in future retry
            # 2. LEASED/GENERATING/VALIDATING but lease_expires_at < now (stale worker crash)
            query = """
                SELECT * FROM daily_jobs
                WHERE (
                    status = 'QUEUED' AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ) OR (
                    status IN ('LEASED', 'GENERATING', 'VALIDATING') AND lease_expires_at IS NOT NULL AND lease_expires_at < ?
                )
            """
            params: list[Any] = [now, now]
            if allowed_markets:
                query += f" AND market IN ({','.join('?' for _ in allowed_markets)})"
                params.extend([m.upper() for m in allowed_markets])

            query += " ORDER BY created_at_utc ASC LIMIT 1"

            cur = conn.execute(query, params)
            candidate = cur.fetchone()
            if not candidate:
                return None

            job_key = candidate["job_key"]
            old_status = candidate["status"]
            new_attempt = candidate["attempt"] + (1 if old_status != JobStatus.QUEUED.value else 1)

            # Atomic claim
            update_cur = conn.execute(
                """
                UPDATE daily_jobs
                SET status = 'LEASED',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    heartbeat_at = ?,
                    attempt = ?
                WHERE job_key = ? AND (
                    status = 'QUEUED' OR (status IN ('LEASED', 'GENERATING', 'VALIDATING') AND lease_expires_at < ?)
                )
                """,
                (worker_id, lease_expires, now, new_attempt, job_key, now),
            )
            if update_cur.rowcount == 0:
                # Lost race to another worker
                return None

            conn.commit()
            cur = conn.execute("SELECT * FROM daily_jobs WHERE job_key = ?", (job_key,))
            return self._row_to_job(cur.fetchone())

    def heartbeat(self, job_key: str, worker_id: str, extend_seconds: int = 1800) -> bool:
        """Extend lease expiration for an active job."""
        now = time.time()
        lease_expires = now + extend_seconds

        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE daily_jobs
                SET heartbeat_at = ?,
                    lease_expires_at = ?
                WHERE job_key = ? AND lease_owner = ? AND status IN ('LEASED', 'GENERATING', 'VALIDATING')
                """,
                (now, lease_expires, job_key, worker_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_stage(
        self,
        job_key: str,
        worker_id: str,
        status: JobStatus,
        project_ids: list[str] | None = None,
        last_error_code: str | None = None,
        run_logs: str | None = None,
    ) -> bool:
        """Update job stage while holding lease."""
        with self._get_connection() as conn:
            fields = ["status = ?", "heartbeat_at = ?"]
            vals: list[Any] = [status.value, time.time()]

            if project_ids is not None:
                fields.append("project_ids_json = ?")
                vals.append(json.dumps(project_ids))

            if last_error_code is not None:
                fields.append("last_error_code = ?")
                vals.append(last_error_code)

            if run_logs is not None:
                fields.append("run_logs = ?")
                vals.append(run_logs)

            vals.extend([job_key, worker_id])
            query = f"UPDATE daily_jobs SET {', '.join(fields)} WHERE job_key = ? AND lease_owner = ?"
            cur = conn.execute(query, vals)
            conn.commit()
            return cur.rowcount > 0

    def complete_job(
        self,
        job_key: str,
        worker_id: str,
        final_status: JobStatus,
        project_ids: list[str] | None = None,
        run_logs: str | None = None,
    ) -> bool:
        """Finalize job and release lease."""
        with self._get_connection() as conn:
            fields = [
                "status = ?",
                "lease_owner = NULL",
                "lease_expires_at = NULL",
                "heartbeat_at = ?",
            ]
            vals: list[Any] = [final_status.value, time.time()]

            if project_ids is not None:
                fields.append("project_ids_json = ?")
                vals.append(json.dumps(project_ids))

            if run_logs is not None:
                fields.append("run_logs = ?")
                vals.append(run_logs)

            vals.extend([job_key, worker_id])
            query = f"UPDATE daily_jobs SET {', '.join(fields)} WHERE job_key = ? AND lease_owner = ?"
            cur = conn.execute(query, vals)
            conn.commit()
            return cur.rowcount > 0

    def fail_job(
        self,
        job_key: str,
        worker_id: str,
        error_code: str,
        retryable: bool = False,
        retry_delay_seconds: int = 3600,
        max_attempts: int = 3,
        run_logs: str | None = None,
    ) -> bool:
        """Mark job failed with bounded retry or terminal quarantine."""
        now = time.time()
        job = self.get_job(job_key)
        if not job:
            return False

        if retryable and job.attempt < max_attempts:
            status = JobStatus.FAILED_RETRYABLE
            next_retry = now + retry_delay_seconds
        else:
            status = JobStatus.FAILED_FINAL if not retryable else JobStatus.QUARANTINED
            next_retry = None

        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE daily_jobs
                SET status = ?,
                    last_error_code = ?,
                    next_retry_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = ?,
                    run_logs = coalesce(?, run_logs)
                WHERE job_key = ? AND lease_owner = ?
                """,
                (status.value, error_code, next_retry, now, run_logs, job_key, worker_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_job(self, job_key: str) -> DailyJob | None:
        """Fetch job by primary key."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM daily_jobs WHERE job_key = ?", (job_key,))
            row = cur.fetchone()
            return self._row_to_job(row) if row else None

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> DailyJob:
        project_ids = []
        if row["project_ids_json"]:
            try:
                project_ids = json.loads(row["project_ids_json"])
            except Exception:
                project_ids = []

        return DailyJob(
            job_key=row["job_key"],
            job_type=row["job_type"],
            market=row["market"],
            local_date=row["local_date"],
            timezone=row["timezone"],
            status=JobStatus(row["status"]),
            attempt=row["attempt"],
            created_at_utc=row["created_at_utc"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            heartbeat_at=row["heartbeat_at"],
            project_ids=project_ids,
            last_error_code=row["last_error_code"],
            source_commit=row["source_commit"],
            config_hash=row["config_hash"],
            run_logs=row["run_logs"],
            next_retry_at=row["next_retry_at"],
        )
