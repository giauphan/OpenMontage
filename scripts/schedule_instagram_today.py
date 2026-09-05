#!/usr/bin/env python3
"""Schedule Instagram Reels for automatic publishing at configured slots.

Reads publish schedule from config/publish_schedule.json and runs publish_slot.py
for each Instagram project at its scheduled time.

Usage:
  python3 scripts/schedule_instagram_today.py [YYYY-MM-DD] [--next-day]

Options:
  --next-day: Also schedule for the day after the target date
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_SLOT = ROOT / "scripts" / "publish_slot.py"

# Job mapping: job_name -> project_id
# This maps Instagram job names to project IDs for scheduling
JOB_TO_PROJECT = {
    "topic1-instagram": "cand_80136a0e2ec3829c",
    "topic2-instagram": "cand_80136a0e2ec3829c",
    "topic3-instagram": "cand_2ea8dd2abd94305d",
}

# Slot configuration (VN time)
SLOT_TIMES = ["09:15", "14:15", "21:15"]


def get_config():
    """Load configuration from publish_schedule.json."""
    config_path = ROOT / "config" / "publish_schedule.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def get_instagram_projects(cfg):
    """Get Instagram projects from active_projects with their scheduled slots."""
    projects = cfg.get("active_projects", [])
    instagram_projects = []

    for item in projects:
        if not isinstance(item, dict):
            continue
        project_id = item.get("project_id")
        publish_date = item.get("publish_date")
        publish_time = item.get("publish_time")

        if not project_id or not publish_date or not publish_time:
            continue

        # Check if this project has Instagram content
        project_dir = ROOT / "projects" / project_id
        meta_path = project_dir / "publish_metadata.json"

        if not meta_path.is_file():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # Check for Instagram reels in metadata
        has_instagram = (
            meta.get("ig_reels") or
            "instagram" in meta.get("platforms", []) or
            meta.get("ig_reels") is not None
        )

        if has_instagram:
            instagram_projects.append({
                "project_id": project_id,
                "publish_date": publish_date,
                "publish_time": publish_time,
                "title": meta.get("title", project_id),
            })

    return instagram_projects


def run_publish_slot(job_name: str) -> bool:
    """Run publish_slot.py for a specific Instagram job.

    Returns True if successful, False otherwise.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(PUBLISH_SLOT), job_name],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        print(f"publish_slot.py {job_name}: exit={result.returncode}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"STDERR: {result.stderr}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"publish_slot.py {job_name}: timed out")
        return False
    except Exception as e:
        print(f"publish_slot.py {job_name}: error - {e}")
        return False


def schedule_instagram(day, cfg):
    """Schedule Instagram publishing for the given day."""
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    date = day.isoformat()

    instagram_projects = get_instagram_projects(cfg)

    if not instagram_projects:
        print(f"No Instagram projects scheduled for {date}")
        return

    print(f"Found {len(instagram_projects)} Instagram project(s) for {date}")

    # Group projects by slot time
    slots = {}
    for proj in instagram_projects:
        slot = proj["publish_time"]
        if slot not in slots:
            slots[slot] = []
        slots[slot].append(proj)

    # Process each slot
    for slot_time, projects in sorted(slots.items()):
        slot_dt = datetime.combine(day, datetime.strptime(slot_time, "%H:%M").time(), tz)

        # Skip if slot already passed (with 20 minute buffer)
        if slot_dt <= now + timedelta(minutes=20):
            print(f"Skip {slot_time}: slot already passed")
            continue

        print(f"\n=== Processing slot {slot_time} ({len(projects)} project(s)) ===")

        for proj in projects:
            project_id = proj["project_id"]

            # Find the Instagram job for this project
            # Jobs follow format: <project_id_prefix>-instagram
            job_name = f"{project_id}-instagram"

            # Check if this job exists in publish_slot.py JOBS
            # For now, we'll use a direct approach with metadata-based jobs
            print(f"Checking project {project_id}...")

            # Check if asset exists
            project_dir = ROOT / "projects" / project_id
            ig_reels_rel = proj.get("ig_reels") if proj.get("ig_reels") else "renders/final_reels_vi_9x16.mp4"
            asset_path = project_dir / ig_reels_rel

            if not asset_path.is_file():
                print(f"  Skip {project_id}: asset not found at {asset_path}")
                continue

            print(f"  Found asset: {asset_path}")

            # Run publish_slot.py with this job
            # We need to create a job dynamically based on metadata
            success = run_publish_slot_for_project(project_id, ig_reels_rel, slot_dt)
            if success:
                print(f"  Scheduled {project_id} for {slot_time}")


def run_publish_slot_for_project(project_id: str, asset_rel: str, slot_dt: datetime) -> bool:
    """Run publish_slot.py for a project by dynamically creating job metadata."""
    project_dir = ROOT / "projects" / project_id
    meta_path = project_dir / "publish_metadata.json"

    if not meta_path.is_file():
        print(f"  Skip {project_id}: missing metadata")
        return False

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    title = meta.get("title", project_id)
    description = meta.get("description", "")

    # Create job entry dynamically
    asset_path = project_dir / asset_rel
    job = {
        "topic": project_id,
        "kind": "reels",
        "platform": "instagram",
        "title": title,
        "description": description,
        "path": asset_rel,
    }

    # The job name format for publish_slot.py
    # We'll run publish_slot.py directly with a custom job setup

    # Use publish_manual_video.py directly since it handles all platforms
    # and we want automatic Instagram publishing
    return run_auto_publish_instagram(project_id, meta, asset_path, slot_dt)


def run_auto_publish_instagram(project_id: str, meta: dict, asset_path: Path, slot_dt: datetime) -> bool:
    """Publish Instagram video automatically via Meta Graph API with scheduled time."""
    cfg = get_config()
    ig_account_id = cfg["meta"]["ig_account_id"]

    print(f"Publishing Instagram for {project_id} at {slot_dt.isoformat()}")

    # Use MetaPublisher with scheduled_publish_time
    result = subprocess.run(
        [sys.executable, "-c", f"""
import sys
sys.path.insert(0, r"{ROOT}")
from pathlib import Path
from datetime import datetime, timezone

from tools.publishers.meta_publisher import MetaPublisher

asset_path = Path(r"{asset_path}")
publish_time = datetime.fromisoformat(r"{slot_dt.isoformat()}")
scheduled_epoch = int(publish_time.astimezone(timezone.utc).timestamp())

publisher = MetaPublisher()
result = publisher.execute({{
    "video_path": str(asset_path),
    "caption": "{meta.get('title', 'Instagram Video')}",
    "page_id": "{ig_account_id}",
    "post_to_facebook": False,
    "post_to_instagram": True,
    "scheduled_publish_time": scheduled_epoch,
}})

if result.success:
    print(f"OK: Instagram scheduled for {asset_path.name}")
    print(f"Media ID: {{result.data.get('instagram_media_id', 'N/A')}}")
    sys.exit(0)
else:
    print(f"FAILED: {{result.error}}")
    sys.exit(1)
        """],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Schedule Instagram Reels for publishing")
    parser.add_argument("target_date", nargs="?", help="Target date in YYYY-MM-DD format (default: today)")
    parser.add_argument("--next-day", action="store_true", help="Also schedule for the day after the target date")
    args = parser.parse_args()

    cfg = get_config()
    tz = ZoneInfo(cfg["timezone"])

    target = datetime.now(tz).date()
    if args.target_date:
        target = datetime.fromisoformat(args.target_date).date()

    try:
        schedule_instagram(target, cfg)
        if args.next_day:
            next_day = target + timedelta(days=1)
            schedule_instagram(next_day, cfg)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
