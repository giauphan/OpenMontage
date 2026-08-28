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
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "publish_schedule.json"
PUBLISHER = ROOT / "scripts" / "publish_manual_video.py"


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

    schedule = json.loads(CONFIG.read_text(encoding="utf-8"))
    projects = schedule.get("active_projects", [])
    if args.slot:
        local_date = datetime.now(ZoneInfo(schedule.get("timezone", "Asia/Ho_Chi_Minh"))).date().isoformat()
        projects = [
            item["project_id"] for item in projects
            if isinstance(item, dict)
            and item.get("publish_date") == local_date
            and item.get("publish_time") == args.slot
        ]
    if not projects:
        print("No active projects configured")
        return 1

    exit_code = 0
    eligible_projects = 0
    for project in projects:
        project_id = project["project_id"] if isinstance(project, dict) else project
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
