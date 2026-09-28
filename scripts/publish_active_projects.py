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

from scripts.publish_config import load_config, publish_timezone

CONFIG = ROOT / "config" / "publish_schedule.json"
PUBLISHER = ROOT / "scripts" / "publish_manual_video.py"


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


def write_audit_tombstone(
    project_id: str,
    project_dir: Path,
    *,
    date: str | None = None,
    status: str = "cleanup_completed",
    store=None,
    media_hashes: dict[str, str] | None = None,
    error: str | None = None,
) -> bool:
    """Write minimal audit record to logs/published_archive.jsonl before/after directory removal.
    
    Returns True on success, False on failure. Uses file locking to serialize appends.
    """
    try:
        archive_file = ROOT / "logs" / "published_archive.jsonl"
        archive_file.parent.mkdir(parents=True, exist_ok=True)

        platform_records = {}
        if store is not None and date:
            from tools.publish_store import publish_key
            for plat, kind in [("youtube", "short"), ("instagram", "reels"), ("facebook", "reels")]:
                rec = store.get(publish_key(date, project_id, plat, kind))
                if rec:
                    platform_records[f"{plat}/{kind}"] = {
                        "status": rec.get("status"),
                        "video_id": rec.get("video_id") or rec.get("platform_id"),
                        "video_url": rec.get("video_url"),
                    }

        hashes = dict(media_hashes) if media_hashes else {}
        if not hashes and project_dir.is_dir():
            from tools.publish_store import file_sha256
            for render_name in ["final_reels_vi_9x16.mp4", "final_full_vi_9x16.mp4"]:
                rf = project_dir / "renders" / render_name
                if rf.is_file():
                    hashes[render_name] = file_sha256(rf)

        tombstone = {
            "project_id": project_id,
            "date": date or datetime.now(timezone.utc).date().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "resolved_path": str(project_dir),
            "platform_records": platform_records,
            "media_hashes": hashes,
            "cleanup_state": status,
        }
        if error:
            tombstone["error"] = error

        line = json.dumps(tombstone, ensure_ascii=False) + "\n"
        lock_file = archive_file.with_suffix(".lock")
        with open(lock_file, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                with open(archive_file, "a", encoding="utf-8") as f:
                    f.write(line)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        return True
    except Exception as exc:
        print(f"ERROR: Failed to write audit tombstone for {project_id}: {exc}", file=sys.stderr)
        return False


def scheduled_projects_for_slot(
    projects: list[object],
    slot: str,
    local_date: str,
    include_overdue: bool = True,
    store=None,
) -> list[dict[str, Any]]:
    """Return valid structured project dicts due for one slot (plus uncompleted overdue entries).
    
    Preserves original publication dates, slot times, and retry status.
    Inspection of overdue projects is strictly read-only.
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

        if item.get("fatal_error") or item.get("status") in ("auth_blocked", "failed", "validation_rejected"):
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


def deactivate_project(
    project_id: str,
    *,
    project_dir: Path | str | None = None,
    store=None,
    date: str | None = None,
    instagram_mode: bool = False,
) -> bool:
    """Safely deactivate published project from schedule and delete its media directory.
    
    Coordinates the full lifecycle under schedule locking (R4):
    - Path safety & symlink checks before resolution (R5)
    - Duplicate-location rejection across all roots, even with explicit path (R5)
    - Reconciles scheduled publications explicitly before checking eligibility (R1/R2)
    - Rechecks eligibility and media hashes inside the protected boundary (R3/R4)
    - Persists audit tombstone before deletion; audit failure blocks deletion (R4)
    - Safely removes directory and surfaces post-deletion failures (R4)
    - Atomically deactivates from schedule queue (R4)
    """
    projects_root = (ROOT / "projects").resolve()
    projects_news_root = (ROOT / "projects_news").resolve()
    ig_parent = (projects_root / "instagram").resolve()
    authorized_roots = (projects_root, projects_news_root, ig_parent)

    # Pre-resolution symlink checks on input path (R5)
    if project_dir is not None:
        cand_input = Path(project_dir)
        if cand_input.is_symlink():
            print(f"❌ Safety check failed: Refusing to delete symlink: {cand_input}", file=sys.stderr)
            return False
        for parent in cand_input.parents:
            if parent.is_symlink():
                print(f"❌ Safety check failed: Refusing to delete path through symlink ancestor: {parent}", file=sys.stderr)
                return False

    # Detect duplicate project directories across locations (R5)
    found_dirs = []
    for cand in [
        projects_root / project_id,
        projects_news_root / project_id,
        ig_parent / project_id,
    ]:
        if cand.is_dir():
            found_dirs.append(cand.resolve())

    # R5: Reject duplicate project locations even when an explicit path is supplied
    if len(found_dirs) > 1:
        print(f"❌ Safety check failed: duplicate project directories found for {project_id}: {found_dirs}", file=sys.stderr)
        return False

    resolved_dir: Path | None = None
    if project_dir is not None:
        resolved_dir = Path(project_dir).resolve()
    elif found_dirs:
        resolved_dir = found_dirs[0]
    else:
        resolved_dir = (projects_root / project_id).resolve()

    if resolved_dir.name != project_id:
        print(f"❌ Safety check failed: Target folder name {resolved_dir.name} does not match {project_id}", file=sys.stderr)
        return False

    is_contained = False
    for auth_root in authorized_roots:
        try:
            rel = resolved_dir.relative_to(auth_root)
            if rel.parts and rel.parts[0] == project_id and len(rel.parts) == 1:
                is_contained = True
                parent_dir = auth_root
                break
        except ValueError:
            pass

    if not is_contained:
        print(f"❌ Safety check failed: Target {resolved_dir} is not an authorized project directory", file=sys.stderr)
        return False

    # Validate metadata identity if publish_metadata.json exists
    meta_path = resolved_dir / "publish_metadata.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_id = meta.get("id") or meta.get("project_id")
            if meta_id and meta_id != project_id:
                print(f"❌ Safety check failed: Metadata ID {meta_id} does not match {project_id}", file=sys.stderr)
                return False
        except Exception:
            pass

    # Protected finalization boundary (R4)
    with locked_schedule(CONFIG):
        # 1. Reconcile any scheduled publications if store is available (R1/R2 explicit mutation)
        pub_date = date
        if not pub_date and meta_path.is_file():
            try:
                m = json.loads(meta_path.read_text(encoding="utf-8"))
                pub_date = m.get("publish_date") or m.get("date")
            except Exception:
                pass

        if store is not None and pub_date:
            from scripts.publish_manual_video import get_required_routes_for_project
            from scripts.check_cleanup_eligibility import reconcile_project_publications
            req_routes = get_required_routes_for_project(
                project_id,
                project_dir=resolved_dir if resolved_dir.is_dir() else None,
            )
            if req_routes:
                reconcile_project_publications(store, project_id, pub_date, req_routes)

        # 2. Check verified publication eligibility inside protected boundary (R1, R2, R3, R4)
        from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
        eligible, reason, _ = is_project_eligible_for_cleanup(
            project_id,
            project_dir=resolved_dir if resolved_dir.exists() else None,
            store=store,
            date=pub_date,
            config_path=CONFIG,
            root=ROOT,
        )
        if not eligible:
            print(f"Project retained: {reason} for {project_id}")
            return False

        # 3. Compute hashes and write audit tombstone before deleting
        media_hashes = {}
        if resolved_dir.is_dir():
            from tools.publish_store import file_sha256
            for render_name in ["final_reels_vi_9x16.mp4", "final_full_vi_9x16.mp4"]:
                rf = resolved_dir / "renders" / render_name
                if rf.is_file():
                    media_hashes[render_name] = file_sha256(rf)

            # R4: Audit failure MUST block deletion
            if not write_audit_tombstone(
                project_id,
                resolved_dir,
                date=pub_date,
                status="cleanup_pending",
                store=store,
                media_hashes=media_hashes,
            ):
                print(f"❌ Failed to persist audit tombstone for {project_id}; aborting cleanup to preserve audit trail", file=sys.stderr)
                return False

            try:
                shutil.rmtree(resolved_dir)
                print(f"✓ Removed published project: {resolved_dir}")
            except OSError as exc:
                print(f"❌ Failed to remove project directory {resolved_dir}: {exc}", file=sys.stderr)
                write_audit_tombstone(
                    project_id,
                    resolved_dir,
                    date=pub_date,
                    status="cleanup_failed",
                    store=store,
                    media_hashes=media_hashes,
                    error=str(exc),
                )
                return False

            # R4: Surface failed completion-audit writes
            if not write_audit_tombstone(
                project_id,
                resolved_dir,
                date=pub_date,
                status="cleanup_completed",
                store=store,
                media_hashes=media_hashes,
            ):
                print(f"❌ Failed to persist completion audit tombstone for {project_id}", file=sys.stderr)
                return False

            if parent_dir == ig_parent and ig_parent.exists():
                try:
                    if not any(ig_parent.iterdir()):
                        ig_parent.rmdir()
                except OSError:
                    pass
        else:
            print(f"✓ Project directory already cleaned: {resolved_dir}")
            if not write_audit_tombstone(project_id, resolved_dir, date=pub_date, status="cleanup_completed", store=store):
                print(f"❌ Failed to persist completion audit tombstone for {project_id}", file=sys.stderr)
                return False

        # 4. Deactivate from active_projects queue inside lock
        if CONFIG.is_file():
            try:
                schedule = json.loads(CONFIG.read_text(encoding="utf-8"))
                active_projects = schedule.get("active_projects", [])
                if any((item.get("project_id") if isinstance(item, dict) else item) == project_id for item in active_projects):
                    schedule["active_projects"] = [
                        item for item in active_projects
                        if (item.get("project_id") if isinstance(item, dict) else item) != project_id
                    ]
                    temp_config = CONFIG.with_suffix(".json.tmp")
                    temp_config.write_text(
                        json.dumps(schedule, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    temp_config.replace(CONFIG)
                    print(f"✓ Deactivated published project: {project_id}")
            except Exception as exc:
                print(f"❌ Failed to update schedule queue for {project_id}: {exc}", file=sys.stderr)
                return False

        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish all active projects")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading or touching Firebase")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed Firebase records")
    parser.add_argument("--slot", choices=["09:15", "14:15", "21:15"], help="Run only queued VN slot")
    parser.add_argument("--date", help="Filter projects by exactly this YYYY-MM-DD date and pass to publisher")
    parser.add_argument("--only-platform", choices=["youtube", "facebook", "instagram"], help="Limit publishing to one platform")
    args = parser.parse_args()

    schedule = load_config()
    projects = schedule.get("active_projects", [])
    if not isinstance(projects, list):
        print("ERROR: active_projects must be a list")
        return 1

    if args.slot:
        local_date = args.date or datetime.now(publish_timezone(schedule)).date().isoformat()
        projects = scheduled_projects_for_slot(projects, args.slot, local_date)

    if args.date and not args.slot:
        projects = [
            p for p in projects
            if isinstance(p, dict) and p.get("publish_date") == args.date
        ]

    if not projects:
        print("No active projects configured for requested filters")
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

        print(f"\n=== Publishing {project_id} ===")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        if "MULTI_PLATFORM" not in env:
            env["MULTI_PLATFORM"] = "0"

        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
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
                            for item in sched.get("active_projects", []):
                                if (item.get("project_id") if isinstance(item, dict) else item) == project_id and isinstance(item, dict):
                                    item["status"] = "validation_rejected"
                                    item["alert"] = "quality_gate_rejected"
                            temp_cfg = CONFIG.with_suffix(".json.tmp")
                            temp_cfg.write_text(json.dumps(sched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                            temp_cfg.replace(CONFIG)
                        except Exception as err:
                            print(f"WARNING: failed to update status for rejected {project_id}: {err}")
        elif result.returncode:
            exit_code = result.returncode
            if not args.dry_run:
                with locked_schedule(CONFIG):
                    if CONFIG.is_file():
                        try:
                            sched = json.loads(CONFIG.read_text(encoding="utf-8"))
                            for item in sched.get("active_projects", []):
                                if (item.get("project_id") if isinstance(item, dict) else item) == project_id and isinstance(item, dict):
                                    retries = item.get("retry_count", 0) + 1
                                    item["retry_count"] = retries
                                    now_utc = datetime.now(timezone.utc)
                                    item["last_attempt"] = now_utc.isoformat()
                                    delay_seconds = 300 * (3 ** (retries - 1))
                                    item["next_attempt_at"] = (now_utc + timedelta(seconds=delay_seconds)).isoformat()

                                    err_text = (result.stderr or "") + " " + (result.stdout or "")
                                    if any(pattern in err_text for pattern in ["AUTH_REQUIRED", "OAuthException", "invalid_token", "invalid_grant"]):
                                        item["status"] = "auth_blocked"
                                        item["alert"] = "authentication_error_requires_operator_resolution"
                                        print(f"⚠️ Project {project_id} authentication failed; marked auth_blocked.")
                                    elif retries >= 3:
                                        item["status"] = "failed"
                                        item["alert"] = "max_retries_exceeded"
                                        print(f"⚠️ Project {project_id} reached max retries ({retries}); marked failed.")
                            temp_cfg = CONFIG.with_suffix(".json.tmp")
                            temp_cfg.write_text(json.dumps(sched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                            temp_cfg.replace(CONFIG)
                        except Exception as err:
                            print(f"WARNING: failed to update retry count for {project_id}: {err}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
