#!/usr/bin/env python3
"""Publish every project listed in config/publish_schedule.json.

DEFAULT: YouTube only (single-platform to prevent duplicates).
Multi-platform mode can be enabled via MULTI_PLATFORM=1 environment variable.
"""

import argparse
import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("OPENMONTAGE_ROOT") or Path(__file__).resolve().parents[1])
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_config import (
    load_config,
    publish_timezone,
    canonical_platform_name,
    get_held_platforms,
    is_platform_held,
    get_enabled_platforms,
    is_platform_enabled,
)

try:
    from dotenv import load_dotenv
    if (ROOT / ".env").is_file():
        load_dotenv(ROOT / ".env")
except ImportError:
    pass

CONFIG = ROOT / "config" / "publish_schedule.json"
PUBLISHER = ROOT / "scripts" / "publish_manual_video.py"
# Bounded deadline for a single project publish so a hung publisher cannot
# stall the whole slot run indefinitely. Child is killed on expiry.
PUBLISHER_TIMEOUT_SECONDS = int(os.environ.get("PUBLISHER_TIMEOUT_SECONDS", "3600"))


def write_slot_heartbeat(slot: str | None, status: str, extra: dict[str, Any] | None = None) -> None:
    """Write a per-slot heartbeat for the independent missed-run checker."""
    if not slot:
        return
    hb_dir = ROOT / "logs" / "heartbeat"
    rec: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "slot": slot,
        "status": status,
    }
    if extra:
        rec.update(extra)
    try:
        hb_dir.mkdir(parents=True, exist_ok=True)
        (hb_dir / f"slot_{slot.replace(':', '')}.json").write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        print(f"WARNING: failed to write slot heartbeat for {slot}: {exc}", file=sys.stderr)


def _finish_slot_heartbeat(slot: str | None, exit_code: int, dry_run: bool) -> None:
    if dry_run or not slot:
        return
    write_slot_heartbeat(slot, "completed" if exit_code == 0 else "failed", {"exit_code": exit_code})


def _record_retry(project_id: str, err_text: str) -> None:
    """Increment retry_count with exponential backoff; mark terminal states.

    Fail-closed: on write error the schedule is left untouched.
    """
    with locked_schedule(CONFIG):
        if not CONFIG.is_file():
            return
        try:
            sched = json.loads(CONFIG.read_text(encoding="utf-8"))
            for item in sched.get("active_projects", []):
                if not isinstance(item, dict) or item.get("project_id") != project_id:
                    continue
                retries = item.get("retry_count", 0) + 1
                item["retry_count"] = retries
                now_utc = datetime.now(timezone.utc)
                item["last_attempt"] = now_utc.isoformat()
                delay_seconds = 300 * (3 ** (retries - 1))
                item["next_attempt_at"] = (now_utc + timedelta(seconds=delay_seconds)).isoformat()

                if any(pattern in err_text for pattern in ["AUTH_REQUIRED", "OAuthException", "invalid_token", "invalid_grant"]):
                    item["status"] = "auth_blocked"
                    item["alert"] = "authentication_error_requires_operator_resolution"
                    print(f"⚠️ Project {project_id} authentication failed; marked auth_blocked.")
                elif retries >= 3:
                    item["status"] = "failed"
                    item["alert"] = "max_retries_exceeded"
                    print(f"⚠️ Project {project_id} reached max retries ({retries}); marked failed.")
            cfg = CONFIG.resolve()
            temp_cfg = cfg.with_suffix(".json.tmp").resolve()
            try:
                temp_cfg.relative_to(ROOT.resolve())
            except ValueError:
                raise ValueError(f"Temporary config path outside root: {temp_cfg}")
            if temp_cfg.parent != cfg.parent:
                raise ValueError("Temporary config parent directory mismatch")
            temp_cfg.write_text(json.dumps(sched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp_cfg.replace(cfg)
        except Exception as err:
            print(f"WARNING: failed to update retry count for {project_id}: {err}")


def _run_publisher(
    command: list[str],
    env: dict[str, str],
    project_id: str,
    args: argparse.Namespace,
) -> subprocess.CompletedProcess | None:
    """Run the publisher with a bounded deadline; record retry state on timeout.

    A timeout kills the child mid-upload. The persisted Firebase claim is NOT
    reset: the next retry runs with --retry-failed and reconciles the remote
    record before re-uploading, so uploads are never blindly repeated.
    Returns None when the run timed out (caller must set a non-zero exit code).
    """
    try:
        return subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True,
            timeout=PUBLISHER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        print(
            f"TIMEOUT: publisher for {project_id} exceeded {PUBLISHER_TIMEOUT_SECONDS}s; "
            "child killed, remote claim preserved for reconciliation on retry",
            file=sys.stderr,
        )
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        if not args.dry_run:
            _record_retry(project_id, f"publisher timeout after {PUBLISHER_TIMEOUT_SECONDS}s")
        return None


@contextlib.contextmanager
def locked_schedule(config_path: Path):
    """Atomic file lock for publish_schedule.json to prevent race conditions.
    
    Fails closed if the lockfile cannot be opened or acquired.
    """
    lock_path = config_path.with_suffix(".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_f = open(lock_path, "w")
    except OSError as err:
        raise RuntimeError(f"Failed to open lockfile {lock_path}: {err}") from err
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
            lock_f.close()
        except OSError:
            pass


from scripts.project_deactivator import (
    deactivate_project,
    write_audit_tombstone,
)


def scheduled_projects_for_slot(
    projects: list[object],
    slot: str,
    local_date: str,
    include_overdue: bool = False,
    store=None,
) -> list[dict[str, Any]]:
    """Return valid structured project dicts due for one exact slot only.

    Overdue entries are excluded by default to prevent burst publishing.
    """
    queued_projects: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in projects:
        if not isinstance(item, dict):
            print(f"WARNING: skipping malformed scheduled project entry: {item!r}")
            continue
        project_id = item.get("project_id")
        publish_date = item.get("publish_date")
        publish_time = item.get("publish_time")
        if not isinstance(project_id, str) or not project_id or not isinstance(publish_date, str) or not isinstance(publish_time, str):
            print(f"WARNING: skipping {project_id or '<unknown>'}: missing publish metadata")
            continue

        if item.get("fatal_error") or item.get("status") in ("auth_blocked", "failed", "validation_rejected", "published", "archived"):
            print(f"INFO: skipping {project_id}: marked {item.get('status')} / fatal_error (operator intervention needed)")
            continue

        if item.get("retry_count", 0) >= 3:
            print(f"INFO: skipping {project_id}: reached max retries (3)")
            continue

        # Check exponential backoff eligibility
        next_attempt_at = item.get("next_attempt_at")
        if next_attempt_at and now_iso < next_attempt_at:
            print(f"INFO: skipping {project_id}: in backoff delay until {next_attempt_at}")
            continue

        is_exact = (publish_date == local_date and publish_time == slot)
        is_overdue = False
        if include_overdue and not is_exact:
            if publish_date < local_date or (publish_date == local_date and publish_time < slot):
                is_overdue = True

        if is_exact:
            queued_projects.append(item)
        elif is_overdue:
            if store is not None:
                from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
                eligible, _, _ = is_project_eligible_for_cleanup(project_id, store=store, date=publish_date, root=ROOT)
                if eligible:
                    continue
            print(f"INFO: queuing overdue project {project_id} (scheduled for {publish_date} {publish_time}) in slot {slot}")
            queued_projects.append(item)

    return queued_projects





def main() -> int:
    parser = argparse.ArgumentParser(description="Publish all active projects")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading or touching Firebase")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed Firebase records")
    parser.add_argument("--slot", help="Run only queued VN slot (e.g. 09:15, 14:15, 19:15, 21:15, 23:30)")
    parser.add_argument("--date", help="Filter projects by exactly this YYYY-MM-DD date and pass to publisher")
    parser.add_argument("--only-platform", type=str, default=None, help="Limit publishing to one platform (e.g. ig, fb, tiktok, ytb)")
    parser.add_argument("--include-overdue", action="store_true", help="Include uncompleted overdue projects from earlier slots")
    parser.add_argument(
        "--hold-platform",
        action="append",
        default=[],
        dest="hold_platforms_list",
        help="Hold (pause/skip) publishing to specific platform (e.g. ig, fb, tiktok, ytb). Can be repeated.",
    )
    parser.add_argument(
        "--hold-platforms",
        type=str,
        default="",
        help="Comma-separated platforms to hold (e.g. 'ig,fb,tiktok,ytb')",
    )
    parser.add_argument("--hold-ig", action="store_true", help="Hold Instagram publishing")
    parser.add_argument("--hold-fb", action="store_true", help="Hold Facebook publishing")
    parser.add_argument("--hold-tiktok", action="store_true", help="Hold TikTok publishing")
    parser.add_argument("--hold-ytb", action="store_true", help="Hold YouTube publishing")
    parser.add_argument(
        "--enabled-platforms",
        type=str,
        default="",
        help="Comma or space separated platforms to enable (e.g. 'ytb' or 'youtube,instagram')",
    )
    parser.add_argument(
        "--enable-platform",
        action="append",
        default=[],
        dest="enabled_platforms_list",
        help="Enable a specific platform (e.g. ytb, ig, fb, tiktok). Can be repeated.",
    )
    args = parser.parse_args()

    cli_held: list[str] = list(args.hold_platforms_list)
    if args.hold_platforms:
        cli_held.append(args.hold_platforms)
    if args.hold_ig:
        cli_held.append("instagram")
    if args.hold_fb:
        cli_held.append("facebook")
    if args.hold_tiktok:
        cli_held.append("tiktok")
    if args.hold_ytb:
        cli_held.append("youtube")

    cli_enabled: list[str] = list(args.enabled_platforms_list)
    if args.enabled_platforms:
        cli_enabled.append(args.enabled_platforms)
    if not cli_enabled:
        cli_enabled = None

    if not args.dry_run:
        write_slot_heartbeat(args.slot, "started")

    schedule = load_config()

    if args.only_platform:
        args.only_platform = canonical_platform_name(args.only_platform)
        if not is_platform_enabled(args.only_platform, cfg=schedule, extra_held=cli_held, extra_enabled=cli_enabled):
            print(f"⏸️ DISABLED/HELD: Platform {args.only_platform} is not enabled or is held. Exiting cleanly.")
            _finish_slot_heartbeat(args.slot, 0, args.dry_run)
            return 0

    projects = schedule.get("active_projects", [])
    if not isinstance(projects, list):
        print("ERROR: active_projects must be a list")
        _finish_slot_heartbeat(args.slot, 1, args.dry_run)
        return 1

    if args.slot:
        local_date = args.date or datetime.now(publish_timezone(schedule)).date().isoformat()
        include_overdue = args.include_overdue or os.environ.get("PUBLISH_INCLUDE_OVERDUE", "0") == "1"
        projects = scheduled_projects_for_slot(projects, args.slot, local_date, include_overdue=include_overdue)

    if args.date and not args.slot:
        projects = [
            p for p in projects
            if isinstance(p, dict) and p.get("publish_date") == args.date
        ]

    if not projects:
        print("No active projects configured for requested filters")
        _finish_slot_heartbeat(args.slot, 0, args.dry_run)
        return 0

    exit_code = 0
    eligible_projects = 0
    for project in projects:
        if isinstance(project, dict):
            project_id = project.get("project_id")
            publish_date = project.get("publish_date")
            retry_count = project.get("retry_count", 0)
            if not project_id:
                print(f"WARNING: skipping malformed project entry: {project!r}")
                continue
        else:
            project_id = project
            publish_date = None
            retry_count = 0

        # Check multiple possible locations for project directory
        project_dir = ROOT / "projects" / project_id
        if not project_dir.exists():
            project_dir = ROOT / "projects_news" / project_id
        if not project_dir.exists():
            # Check projects/instagram/ folder for Instagram cron jobs
            project_dir = ROOT / "projects" / "instagram" / project_id
        metadata_path = project_dir / "publish_metadata.json"
        if not metadata_path.is_file():
            print(f"WARNING: skipping {project_id}: missing {metadata_path}")
            continue
        eligible_projects += 1
        command = [sys.executable, str(PUBLISHER), str(project_dir)]
        if args.dry_run:
            command.append("--dry-run")
        if args.retry_failed or retry_count > 0:
            command.append("--retry-failed")
        if publish_date:
            command.extend(["--date", publish_date])
        elif args.date:
            command.extend(["--date", args.date])

        if hasattr(args, "only_platform") and args.only_platform:
            command.extend(["--only-platform", args.only_platform])

        for p in cli_held:
            command.extend(["--hold-platform", p])

        if cli_enabled:
            for p in cli_enabled:
                command.extend(["--enable-platform", p])

        print(f"\n=== Publishing {project_id} ===")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        if "MULTI_PLATFORM" not in env:
            env["MULTI_PLATFORM"] = "0"

        held_set = get_held_platforms(schedule, extra_held=cli_held)
        if held_set:
            env["HOLD_PLATFORMS"] = ",".join(sorted(held_set))

        enabled_set = get_enabled_platforms(schedule, extra_enabled=cli_enabled)
        if enabled_set is not None:
            env["ENABLED_PLATFORMS"] = ",".join(sorted(enabled_set))

        result = _run_publisher(command, env, project_id, args)
        if result is None:
            exit_code = 1
            continue
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if result.returncode == 2:
            print(f"STRICT QUALITY GATE REJECTED {project_id} (exit 2). Project retained for diagnosis.")
            exit_code = result.returncode
            if not args.dry_run:
                with locked_schedule(CONFIG):
                    if CONFIG.is_file():
                        try:
                            sched = json.loads(CONFIG.read_text(encoding="utf-8"))
                            val_file = project_dir / "validation_status.json"
                            is_verified = False
                            if val_file.is_file():
                                try:
                                    v_raw = json.loads(val_file.read_text(encoding="utf-8"))
                                    v_recs = v_raw if isinstance(v_raw, list) else [v_raw]
                                    is_verified = any(r.get("status") == "PASS" and r.get("strict_quality_pass") is True for r in v_recs)
                                except Exception:
                                    pass

                            for item in sched.get("active_projects", []):
                                if (item.get("project_id") if isinstance(item, dict) else item) == project_id and isinstance(item, dict):
                                    if not is_verified:
                                        item["status"] = "validation_rejected"
                                        item["alert"] = "quality_gate_rejected"
                                    else:
                                        item["alert"] = "platform_publish_retry_needed"
                            cfg = CONFIG.resolve()
                            temp_cfg = cfg.with_suffix(".json.tmp").resolve()
                            try:
                                temp_cfg.relative_to(ROOT.resolve())
                            except ValueError:
                                raise ValueError(f"Temporary config path outside root: {temp_cfg}")
                            if temp_cfg.parent != cfg.parent:
                                raise ValueError("Temporary config parent directory mismatch")
                            temp_cfg.write_text(json.dumps(sched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                            temp_cfg.replace(cfg)
                        except Exception as err:
                            print(f"WARNING: failed to update status for rejected {project_id}: {err}")
        elif result.returncode:
            exit_code = result.returncode
            if not args.dry_run:
                _record_retry(project_id, (result.stderr or "") + " " + (result.stdout or ""))

    _finish_slot_heartbeat(args.slot, exit_code, args.dry_run)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
