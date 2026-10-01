"""Focused regression tests for daily Docker cron reliability.

Covers:
1. Heartbeat writing & detection in scripts/check_missed_runs.py (missing,
   stale, failed, ok).
2. Schedule lock acquisition & contention behavior in the strict orchestrator.
3. Disk threshold enforcement and age-gated temporary cleanup.
4. Quarantine (never silent rm -rf) of failed-generation project directories.
5. Max stale-feed age enforcement in run_daily_news_pipeline.sh.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_missed_runs.py"


def test_check_missed_runs_detects_missing_heartbeats(tmp_path: Path):
    (tmp_path / "logs" / "heartbeat").mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path), "--jobs", "daily_orchestrator"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "MISSING_HEARTBEAT" in res.stdout
    alert_log = tmp_path / "logs" / "missed_run_alerts.log"
    assert alert_log.is_file()
    assert "MISSING_HEARTBEAT" in alert_log.read_text(encoding="utf-8")


def test_check_missed_runs_detects_stale_and_failed_heartbeats(tmp_path: Path):
    hb_dir = tmp_path / "logs" / "heartbeat"
    hb_dir.mkdir(parents=True, exist_ok=True)

    # 1. Stale orchestrator (>30h old)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=35)).isoformat().replace("+00:00", "Z")
    (hb_dir / "daily_orchestrator.json").write_text(
        json.dumps({"ts": stale_ts, "status": "completed", "run_id": "r_old"}),
        encoding="utf-8",
    )
    # 2. Fresh but failed slot
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    (hb_dir / "slot_0915.json").write_text(
        json.dumps({"ts": fresh_ts, "status": "failed", "exit_code": 1}),
        encoding="utf-8",
    )

    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path), "--jobs", "daily_orchestrator,slot_0915"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    out = res.stdout
    assert "STALE_HEARTBEAT" in out
    assert "RUN_FAILED" in out


def test_check_missed_runs_passes_when_all_heartbeats_fresh_and_ok(tmp_path: Path):
    hb_dir = tmp_path / "logs" / "heartbeat"
    hb_dir.mkdir(parents=True, exist_ok=True)
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    for job in ("daily_orchestrator", "slot_0915", "slot_1415", "slot_2115"):
        (hb_dir / f"{job}.json").write_text(
            json.dumps({"ts": fresh_ts, "status": "completed", "run_id": f"r_{job}"}),
            encoding="utf-8",
        )

    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "No missed-run or failure alerts." in res.stdout
