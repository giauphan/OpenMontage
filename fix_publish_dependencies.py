#!/usr/bin/env python3
"""
Fix publishing dependencies and clear stuck scheduling records.
Run from OpenMontage root:
  PYTHONPATH=. python3 fix_publish_dependencies.py
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Ensure we're in the right directory
os.chdir(Path(__file__).parent.parent)
sys.path.insert(0, str(Path.cwd()))

# Config paths
PUBLISH_SCHEDULE = Path("config/publish_schedule.json")
PROJECTS_DIR = Path("projects")
LOGS_DIR = Path("logs")

# Dependencies to install
deps = [
    "google-auth",
    "google-auth-httplib2",
    "google-api-python-client",
    "requests",
    "requests-oauthlib",
    "python-dotenv"
]

def install_dependencies():
    """Install missing Python dependencies."""
    print("Installing dependencies...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade"] + deps,
            check=True,
            capture_output=True,
            text=True
        )
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install dependencies: {e.stderr}")
        return False

def clear_stuck_scheduling_records():
    """Clear stuck scheduling records in publish_metadata.json files."""
    print("Clearing stuck scheduling records...")
    cleared = 0

    for project_dir in PROJECTS_DIR.glob("cand_*"):
        metadata_file = project_dir / "publish_metadata.json"
        if not metadata_file.exists():
            continue

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Clear scheduling-related fields
            changed = False
            for field in ["yt_scheduled", "ig_scheduled", "fb_scheduled", "scheduling"]:
                if field in metadata:
                    del metadata[field]
                    changed = True

            if changed:
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                print(f"  ✓ Cleared scheduling records in {project_dir.name}")
                cleared += 1

        except Exception as e:
            print(f"  ✗ Failed to process {project_dir.name}: {str(e)}")

    print(f"✓ Cleared {cleared} stuck scheduling records")
    return cleared > 0

def test_publish_imports():
    """Test if critical publish modules can be imported."""
    print("Testing publish module imports...")

    try:
        from tools.publish_store import PublishStore
        print("✓ tools.publish_store import successful")
        return True
    except Exception as e:
        print(f"✗ tools.publish_store import failed: {str(e)}")
        return False

def main():
    print(f"=== Fixing OpenMontage Publishing System ===")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Step 1: Install dependencies
    if not install_dependencies():
        print("❌ Dependency installation failed. Check Python environment.")
        return 1

    # Step 2: Clear stuck records
    clear_stuck_scheduling_records()

    # Step 3: Test imports
    if not test_publish_imports():
        print("❌ Module imports still failing. Check PYTHONPATH and virtualenv.")
        return 1

    print("\n✅ Publishing system fix completed successfully!")
    print("You can now run the publishing scripts:")
    print("  PYTHONPATH=. python3 scripts/schedule_youtube_today.py")
    print("  PYTHONPATH=. python3 scripts/schedule_instagram_today.py")
    return 0

if __name__ == "__main__":
    sys.exit(main())