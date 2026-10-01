#!/usr/bin/env python3
"""Independent missed-run / failure checker for the daily Docker cron pipeline.

Run this OUTSIDE the scheduler container (e.g. a host cron job or a monitor
that reads the bind-mounted OpenMontage tree). That makes scheduler downtime
detectable even when the scheduler itself cannot emit alerts.

Each cron entry writes a heartbeat file under ``logs/heartbeat/`` when it runs
and updates it on completion. This checker reads those heartbeats, flags any
that are missing, stale, or whose last run failed, and emits a structured
alert.

Exit codes:
    0 - all expected heartbeats present and current, no failures
    1 - one or more alerts (missing / stale / failed) were emitted
    2 - operational error (bad root, unreadable tree)

It never mutates pipeline state; it only reads and appends to its own alert
log. Alerts are redacted: no credentials or API values are ever written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def expected_jobs(args: argparse.Namespace) -> list[dict[str, object]]:
    """Heartbeat jobs to check. Names map to logs/heartbeat/<name>.json."""
    jobs = [
        # Daily orchestrator (run_strict_docker_publish.sh) at 23:00 UTC.
        {"name": "daily_orchestrator", "max_age_hours": args.orchestrator_max_age_hours},
        # Instagram slot publishers (ICT slot names: 09:15/14:15/21:15 ICT).
        {"name": "slot_0915", "max_age_hours": args.slot_max_age_hours},
        {"name": "slot_1415", "max_age_hours": args.slot_max_age_hours},
        {"name": "slot_2115", "max_age_hours": args.slot_max_age_hours},
    ]
    if args.jobs:
        wanted = set(args.jobs.split(","))
        jobs = [j for j in jobs if j["name"] in wanted]
    return jobs


def check_heartbeat(root: Path, name: str, max_age_hours: float) -> dict:
    hb_path = root / "logs" / "heartbeat" / f"{name}.json"
    now = _utcnow()
    result: dict = {"name": name, "file": str(hb_path), "now": now.isoformat()}

    if not hb_path.is_file():
        result.update(state="missing", alert="MISSING_HEARTBEAT",
                      detail="no heartbeat file; the scheduled job may never have run")
        return result

    try:
        data = json.loads(hb_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result.update(state="invalid", alert="INVALID_HEARTBEAT", detail=f"unreadable heartbeat: {exc}")
        return result

    ts = _parse_ts(str(data.get("ts", "")))
    status = str(data.get("status", "unknown"))
    result["last_status"] = status
    result["last_ts"] = data.get("ts")

    if ts is None:
        result.update(state="invalid", alert="INVALID_HEARTBEAT", detail="heartbeat has no parseable ts")
        return result

    age_hours = (now - ts).total_seconds() / 3600.0
    result["age_hours"] = round(age_hours, 3)

    if status in ("failed", "error"):
        result.update(state="failed", alert="RUN_FAILED",
                      detail=f"last heartbeat status={status} at {data.get('ts')}")
        return result

    if age_hours > max_age_hours:
        result.update(state="stale", alert="STALE_HEARTBEAT",
                      detail=f"last heartbeat {age_hours:.1f}h old (max {max_age_hours}h); "
                             f"scheduler may be down or the job missed its window")
        return result

    result.update(state="ok", alert=None, detail=f"current ({status})")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent missed-run / failure checker")
    parser.add_argument("--root", default=None,
                        help="OpenMontage root (default: $OPENMONTAGE_ROOT or this file's repo root)")
    parser.add_argument("--jobs", default=None,
                        help="comma-separated heartbeat names to check (default: all)")
    parser.add_argument("--orchestrator-max-age-hours", type=float, default=30.0,
                        help="max allowed age for the daily orchestrator heartbeat (default 30)")
    parser.add_argument("--slot-max-age-hours", type=float, default=30.0,
                        help="max allowed age for a slot heartbeat (default 30)")
    parser.add_argument("--quiet", action="store_true",
                        help="only print alerts, not ok lines")
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    elif os.environ.get("OPENMONTAGE_ROOT"):
        root = Path(os.environ["OPENMONTAGE_ROOT"]).resolve()
    else:
        root = Path(__file__).resolve().parents[1]

    if not root.is_dir():
        print(f"ERROR: OpenMontage root not found: {root}", file=sys.stderr)
        return 2

    alerts: list[dict] = []
    for job in expected_jobs(args):
        res = check_heartbeat(root, str(job["name"]), float(job["max_age_hours"]))
        res["max_age_hours"] = job["max_age_hours"]
        if res.get("alert"):
            alerts.append(res)
        if not args.quiet or res.get("alert"):
            print(json.dumps(res, ensure_ascii=False))

    # Append a durable, redacted audit of alerts so an operator can replay them.
    if alerts:
        alert_log = root / "logs" / "missed_run_alerts.log"
        try:
            alert_log.parent.mkdir(parents=True, exist_ok=True)
            with alert_log.open("a", encoding="utf-8") as f:
                for a in alerts:
                    f.write(json.dumps({
                        "checked_at": _utcnow().isoformat(),
                        "alert": a["alert"],
                        "name": a["name"],
                        "state": a["state"],
                        "detail": a["detail"],
                        "last_status": a.get("last_status"),
                        "last_ts": a.get("last_ts"),
                        "age_hours": a.get("age_hours"),
                    }, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"WARNING: could not append alert log: {exc}", file=sys.stderr)

    if alerts:
        print(f"\n{len(alerts)} alert(s): " + ", ".join(str(a["alert"]) for a in alerts))
        return 1
    print("\nNo missed-run or failure alerts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
