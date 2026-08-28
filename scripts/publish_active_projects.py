#!/usr/bin/env python3
"""Publish every project listed in config/publish_schedule.json."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish_config import load_config, publish_timezone

CONFIG = ROOT / "config" / "publish_schedule.json"
PUBLISHER = ROOT / "scripts" / "publish_manual_video.py"


def scheduled_projects_for_slot(projects: list[object], slot: str, local_date: str) -> list[str]:
    """Return valid structured entries due for one slot.

    Legacy string entries remain supported by unfiltered publishing, but lack
    scheduling metadata and are skipped when a slot is requested.
    """
    queued_projects: list[str] = []
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
        if publish_date == local_date and publish_time == slot:
            queued_projects.append(project_id)
    return queued_projects


def deactivate_project(project_id: str) -> None:
    """Remove a fully published project from the schedule and disk."""
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

    project_dir = ROOT / "projects" / project_id
    if project_dir.exists():
        shutil.rmtree(project_dir)
        print(f"✓ Removed published project directory: {project_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish all active projects")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading or touching Firebase")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed Firebase records")
    parser.add_argument("--slot", choices=["09:15", "14:15", "21:15"], help="Run only queued VN slot")
    args = parser.parse_args()

    schedule = load_config()
    projects = schedule.get("active_projects", [])
    if not isinstance(projects, list):
        print("ERROR: active_projects must be a list")
        return 1
    if args.slot:
        local_date = datetime.now(publish_timezone(schedule)).date().isoformat()
        projects = scheduled_projects_for_slot(projects, args.slot, local_date)
    if not projects:
        print("No active projects configured")
        return 1

    exit_code = 0
    eligible_projects = 0
    for project in projects:
        if isinstance(project, dict):
            project_id = project.get("project_id")
            if not project_id:
                print(f"WARNING: skipping malformed project entry: {project!r}")
                continue
        else:
            project_id = project
        project_dir = ROOT / "projects" / project_id
        metadata_path = project_dir / "publish_metadata.json"
        if not metadata_path.is_file():
            print(f"WARNING: skipping {project_id}: missing {metadata_path}")
            continue
        eligible_projects += 1
        command = [sys.executable, str(PUBLISHER), str(project_dir)]
        if args.dry_run:
            command.append("--dry-run")
        if args.retry_failed:
            command.append("--retry-failed")
        print(f"\n=== Publishing {project_id} ===")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        result = subprocess.run(command, cwd=ROOT, env=env)
        if result.returncode:
            exit_code = result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
