#!/usr/bin/env python3
"""OpenMontage Pipeline Monitoring and Structured Error Reporting.

Centralized error logging, retry tracking, and incident reporting for:
- scripts/run_daily_news_pipeline.sh
- scripts/run_strict_docker_publish.sh
- scripts/codex_agent_validation.py
- scripts/repair_hyperframes_quality.py
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import logging
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
JSON_REPORT_PATH = LOGS_DIR / "pipeline_monitoring_report.json"
LOG_REPORT_PATH = LOGS_DIR / "pipeline_error_report.log"


def _ensure_logs_dir() -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


class MonitoringReportError(RuntimeError):
    """The monitoring history cannot safely be read or persisted."""


@contextmanager
def _report_lock(for_write: bool = True) -> Iterator[None]:
    """Serialize report operations across processes sharing this filesystem."""
    _ensure_logs_dir()
    lock_path = JSON_REPORT_PATH.with_suffix(JSON_REPORT_PATH.suffix + ".lock")
    lock_file = None
    try:
        try:
            mode = "a" if for_write else "r"
            lock_file = open(lock_path, mode, encoding="utf-8")
        except (FileNotFoundError, PermissionError):
            if not for_write:
                try:
                    lock_file = open(lock_path, "r", encoding="utf-8")
                except (OSError, PermissionError):
                    lock_file = None
            else:
                try:
                    lock_file = open(lock_path, "a", encoding="utf-8")
                except PermissionError:
                    raise
        if lock_file is not None:
            flock_op = fcntl.LOCK_EX if for_write else fcntl.LOCK_SH
            fcntl.flock(lock_file.fileno(), flock_op)
        yield
    finally:
        if lock_file is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            lock_file.close()


def _read_json_report_unlocked() -> List[Dict[str, Any]]:
    try:
        report_exists = os.path.lexists(JSON_REPORT_PATH)
        if not report_exists:
            return []
        if not JSON_REPORT_PATH.is_file():
            raise MonitoringReportError(
                f"Monitoring history at {JSON_REPORT_PATH} is not a regular file; "
                "the original path was preserved"
            )
        data = json.loads(JSON_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MonitoringReportError(
            f"Cannot read monitoring history at {JSON_REPORT_PATH}; "
            "the original file was preserved"
        ) from exc
    if not isinstance(data, list) or any(not isinstance(record, dict) for record in data):
        raise MonitoringReportError(
            f"Monitoring history at {JSON_REPORT_PATH} has an invalid structure; "
            "the original file was preserved"
        )
    return data


def _load_json_report() -> List[Dict[str, Any]]:
    try:
        with _report_lock(for_write=False):
            return _read_json_report_unlocked()
    except (PermissionError, OSError):
        return _read_json_report_unlocked()


def _save_json_report(records: List[Dict[str, Any]]) -> None:
    _ensure_logs_dir()
    # Keep last 500 events to prevent unbounded growth.
    truncated = records[-500:] if len(records) > 500 else records
    payload = json.dumps(truncated, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{JSON_REPORT_PATH.name}.", suffix=".tmp", dir=LOGS_DIR)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        tmp_path.replace(JSON_REPORT_PATH)
        dir_fd = os.open(LOGS_DIR, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def append_monitoring_event(
    event_type: str,
    stage: str,
    project_id: str = "",
    status: str = "INFO",
    error_type: str = "",
    message: str = "",
    details: Optional[Dict[str, Any]] = None,
    attempt: int = 1,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """Append a structured monitoring event to both JSON and text reports."""
    _ensure_logs_dir()
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    event = {
        "timestamp": now_utc,
        "event_type": event_type,
        "stage": stage,
        "project_id": project_id,
        "status": status,
        "error_type": error_type,
        "message": message,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "details": details or {},
    }

    try:
        with _report_lock():
            records = _read_json_report_unlocked()
            records.append(event)
            _save_json_report(records)

        # Append to human-readable log
        icon = "🔴" if status in ("ERROR", "FAIL", "CRASH") else ("🟡" if status in ("RETRY", "WARN") else "🟢")
        log_line = (
            f"[{now_utc}] {icon} [{status}] stage={stage} project={project_id or 'none'} "
            f"attempt={attempt}/{max_attempts} error_type={error_type or 'none'}: {message}\n"
        )
        if details:
            details_str = json.dumps(details, ensure_ascii=False)
            log_line += f"       └─ details: {details_str}\n"

        with open(LOG_REPORT_PATH, "a", encoding="utf-8") as f:
            f.write(log_line)
    except OSError as e:
        logger.warning("Pipeline monitoring could not persist event due to OSError (%s): %s", e, message)

    return event


def log_pipeline_error(
    stage: str,
    project_id: str = "",
    error_type: str = "PIPELINE_ERROR",
    message: str = "",
    details: Optional[Dict[str, Any]] = None,
    attempt: int = 1,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    return append_monitoring_event(
        event_type="error",
        stage=stage,
        project_id=project_id,
        status="ERROR",
        error_type=error_type,
        message=message,
        details=details,
        attempt=attempt,
        max_attempts=max_attempts,
    )


def log_pipeline_retry(
    stage: str,
    project_id: str = "",
    reason: str = "",
    attempt: int = 1,
    max_attempts: int = 3,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return append_monitoring_event(
        event_type="retry",
        stage=stage,
        project_id=project_id,
        status="RETRY",
        error_type="RETRY_ATTEMPT",
        message=reason,
        details=details,
        attempt=attempt,
        max_attempts=max_attempts,
    )


def log_pipeline_success(
    stage: str,
    project_id: str = "",
    message: str = "Stage completed successfully",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return append_monitoring_event(
        event_type="success",
        stage=stage,
        project_id=project_id,
        status="SUCCESS",
        error_type="",
        message=message,
        details=details,
        attempt=1,
        max_attempts=1,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline Monitoring & Error Logging CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # log-error
    err_p = subparsers.add_parser("log-error", help="Log a pipeline error")
    err_p.add_argument("--stage", required=True, help="Pipeline stage name")
    err_p.add_argument("--project-id", default="", help="Project ID if applicable")
    err_p.add_argument("--error-type", default="PIPELINE_ERROR", help="Category of error")
    err_p.add_argument("--message", required=True, help="Error message")
    err_p.add_argument("--details", default="{}", help="JSON string of error details")
    err_p.add_argument("--attempt", type=int, default=1, help="Current attempt count")
    err_p.add_argument("--max-attempts", type=int, default=3, help="Max allowed attempts")

    # log-retry
    ret_p = subparsers.add_parser("log-retry", help="Log a retry attempt")
    ret_p.add_argument("--stage", required=True, help="Pipeline stage name")
    ret_p.add_argument("--project-id", default="", help="Project ID if applicable")
    ret_p.add_argument("--reason", required=True, help="Retry reason")
    ret_p.add_argument("--attempt", type=int, required=True, help="Attempt number")
    ret_p.add_argument("--max-attempts", type=int, default=3, help="Max allowed attempts")
    ret_p.add_argument("--details", default="{}", help="JSON string of details")

    # log-success
    succ_p = subparsers.add_parser("log-success", help="Log a success event")
    succ_p.add_argument("--stage", required=True, help="Pipeline stage name")
    succ_p.add_argument("--project-id", default="", help="Project ID if applicable")
    succ_p.add_argument("--message", default="Stage completed successfully", help="Success message")
    succ_p.add_argument("--details", default="{}", help="JSON string of details")

    # dump-summary
    subparsers.add_parser("summary", help="Print recent monitoring summary")

    args = parser.parse_args()

    if args.command == "log-error":
        details = {}
        try:
            details = json.loads(args.details)
        except Exception:
            details = {"raw": args.details}
        log_pipeline_error(
            stage=args.stage,
            project_id=args.project_id,
            error_type=args.error_type,
            message=args.message,
            details=details,
            attempt=args.attempt,
            max_attempts=args.max_attempts,
        )
        print(f"Logged ERROR to {JSON_REPORT_PATH}")
    elif args.command == "log-retry":
        details = {}
        try:
            details = json.loads(args.details)
        except Exception:
            details = {"raw": args.details}
        log_pipeline_retry(
            stage=args.stage,
            project_id=args.project_id,
            reason=args.reason,
            attempt=args.attempt,
            max_attempts=args.max_attempts,
            details=details,
        )
        print(f"Logged RETRY to {JSON_REPORT_PATH}")
    elif args.command == "log-success":
        details = {}
        try:
            details = json.loads(args.details)
        except Exception:
            details = {"raw": args.details}
        log_pipeline_success(
            stage=args.stage,
            project_id=args.project_id,
            message=args.message,
            details=details,
        )
        print(f"Logged SUCCESS to {JSON_REPORT_PATH}")
    elif args.command == "summary":
        records = _load_json_report()
        errors = [r for r in records if r.get("status") in ("ERROR", "FAIL", "CRASH")]
        retries = [r for r in records if r.get("status") in ("RETRY", "WARN")]
        print(f"Total events: {len(records)}, Errors: {len(errors)}, Retries: {len(retries)}")
        if records:
            print("\nRecent 5 events:")
            for r in records[-5:]:
                print(f"  [{r['timestamp']}] {r['status']} ({r['stage']}): {r['message']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
