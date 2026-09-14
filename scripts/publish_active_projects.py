#!/usr/bin/env python3
"""Publish every project listed in config/publish_schedule.json.

DEFAULT: YouTube only (single-platform to prevent duplicates).
Multi-platform mode can be enabled via MULTI_PLATFORM=1 environment variable.
"""

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
    
    For Instagram slots, also check projects/instagram/ folder for projects
    that were moved there after YouTube/Facebook scheduling.
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
    
    # For Instagram slots, also add projects from projects/instagram/ folder
    # These were moved there after YouTube/Facebook scheduling
    instagram_dir = ROOT / "projects" / "instagram"
    if instagram_dir.exists():
        for project_dir in instagram_dir.iterdir():
            if project_dir.is_dir():
                project_id = project_dir.name
                # Check if this project has valid metadata
                metadata_file = project_dir / "publish_metadata.json"
                if metadata_file.exists():
                    queued_projects.append(project_id)
    
    return queued_projects


def deactivate_project(project_id: str, *, store=None, date: str | None = None, instagram_mode: bool = False) -> bool:
    """Move project to instagram folder after YouTube/Facebook scheduling for Instagram cron jobs.
    
    When instagram_mode=True: delete project from instagram folder after successful Instagram publish.
    When instagram_mode=False: move project to instagram folder after YouTube/FB scheduling.
    """
    if store is not None:
        from scripts.publish_manual_video import canonical_platform_records_published

        if not date or not canonical_platform_records_published(store, date=date, topic=project_id):
            print(f"Project retained: canonical Firebase publish records are incomplete for {project_id}")
            return False

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

    if instagram_mode:
        # Instagram mode: delete project from instagram folder after successful Instagram publish
        project_dir = ROOT / "projects" / "instagram" / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)
            print(f"✓ Removed Instagram-published project: {project_dir}")
    else:
        # Find project directory in any location
        project_dir = ROOT / "projects" / project_id
        if not project_dir.exists():
            project_dir = ROOT / "projects_news" / project_id
        
        # If project exists and is not already in instagram folder, move it there
        if project_dir.exists() and "instagram" not in str(project_dir):
            instagram_dir = ROOT / "projects" / "instagram"
            instagram_dir.mkdir(parents=True, exist_ok=True)
            
            destination = instagram_dir / project_id
            if destination.exists():
                shutil.rmtree(destination)
            
            shutil.move(str(project_dir), str(destination))
            print(f"✓ Moved project to Instagram folder: {destination}")
        elif project_dir.exists():
            # Already in instagram folder, keep it there
            print(f"✓ Project already in Instagram folder: {project_dir}")
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
            if not project_id:
                print(f"WARNING: skipping malformed project entry: {project!r}")
                continue
        else:
            project_id = project
            publish_date = None

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
        if args.retry_failed:
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
        # Pass through MULTI_PLATFORM setting to publisher
        if "MULTI_PLATFORM" not in env:
            env["MULTI_PLATFORM"] = "0"  # Default to single-platform
        # Set INSTAGRAM_MODE for Instagram-only publishing to delete from instagram folder
        if args.only_platform == "instagram":
            env["INSTAGRAM_MODE"] = "1"
        result = subprocess.run(command, cwd=ROOT, env=env)
        if result.returncode:
            exit_code = result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
