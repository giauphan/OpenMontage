import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/app")
SCHEDULE_PATH = ROOT / "config" / "publish_schedule.json"
TARGET_DATE = "2026-09-19"
SLOTS = ["09:15", "14:15", "21:15"]

def main():
    projects_dir = ROOT / "projects"
    candidates = sorted([p for p in projects_dir.glob("cand_*") if p.is_dir()])

    valid_candidates = []
    for cand in candidates:
        meta = cand / "publish_metadata.json"
        if not meta.is_file():
            continue
        try:
            data = json.loads(meta.read_text())
            if data.get("id") and data.get("yt_shorts"):
                valid_candidates.append(cand.name)
        except Exception:
            continue

    print(f"Found valid candidate projects: {valid_candidates}")

    if len(valid_candidates) < 3:
        print(f"Warning: Only {len(valid_candidates)} valid candidates found, need 3 for complete daily schedule.")

    schedule = json.loads(SCHEDULE_PATH.read_text())
    active = schedule.setdefault("active_projects", [])

    # Remove older stale attempts for this target date to start fresh with verified projects
    active = [p for p in active if p.get("publish_date") != TARGET_DATE]

    for i, pid in enumerate(valid_candidates[:3]):
        slot = SLOTS[i]
        active.append({
            "project_id": pid,
            "publish_date": TARGET_DATE,
            "publish_time": slot
        })
        print(f"Scheduled {pid} for {TARGET_DATE} at {slot}")

    schedule["active_projects"] = sorted(active, key=lambda x: (x.get("publish_date", ""), x.get("publish_time", "")))
    SCHEDULE_PATH.write_text(json.dumps(schedule, indent=2) + "\n")
    print(f"Updated {SCHEDULE_PATH} successfully!")

if __name__ == "__main__":
    main()
