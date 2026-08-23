#!/usr/bin/env python3
"""Publish every project listed in config/publish_schedule.json."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "publish_schedule.json"
PUBLISHER = ROOT / "scripts" / "publish_manual_video.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish all active projects")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading or touching Firebase")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed Firebase records")
    args = parser.parse_args()

    schedule = json.loads(CONFIG.read_text(encoding="utf-8"))
    projects = schedule.get("active_projects", [])
    if not projects:
        print("No active projects configured")
        return 1

    exit_code = 0
    for project_id in projects:
        project_dir = ROOT / "projects" / project_id
        metadata_path = project_dir / "publish_metadata.json"
        if not metadata_path.is_file():
            print(f"WARNING: skipping {project_id}: missing {metadata_path}")
            continue
        command = [sys.executable, str(PUBLISHER), str(project_dir)]
        if args.dry_run:
            command.append("--dry-run")
        if args.retry_failed:
            command.append("--retry-failed")
        print(f"\n=== Publishing {project_id} ===")
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            exit_code = result.returncode
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
