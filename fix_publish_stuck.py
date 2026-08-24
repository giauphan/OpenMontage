#!/usr/bin/env python3
"""
Fix stuck publishing records and force retry.
Run inside Docker:
  docker exec -it openmontage_scheduler python3 /app/fix_publish_stuck.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Config
PROJECTS_DIR = Path('/app/projects')
CONFIG_FILE = Path('/app/config/publish_schedule.json')


def clear_stuck_records():
    """Clear stuck scheduling records in publish_metadata.json files."""
    print("=== Clearing stuck scheduling records ===")
    cleared = 0

    for project_dir in PROJECTS_DIR.glob('cand_*'):
        metadata_file = project_dir / 'publish_metadata.json'
        if not metadata_file.exists():
            continue

        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            # Clear scheduling-related fields
            changed = False
            for field in ['yt_scheduled', 'ig_scheduled', 'fb_scheduled', 'scheduling']:
                if field in metadata:
                    del metadata[field]
                    changed = True

            if changed:
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                print(f"  ✓ Cleared {project_dir.name}")
                cleared += 1

        except Exception as e:
            print(f"  ✗ Failed to process {project_dir.name}: {str(e)}")

    print(f"✓ Cleared {cleared} stuck scheduling records")
    return cleared

def force_retry_publish():
    """Force retry of failed publishes by clearing Firebase records."""
    print("\n=== Forcing retry of failed publishes ===")

    try:
        # Import inside function to avoid breaking if deps are missing
        from tools.publish_store import PublishStore
        store = PublishStore()

        # Clear failed records for active projects
        schedule = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        projects = schedule.get('active_projects', [])

        cleared = 0
        for project_id in projects:
            try:
                # Clear YouTube failed records
                yt_key = f"youtube/{project_id}"
                if store.exists(yt_key):
                    record = store.get(yt_key)
                    if record.get('status') == 'failed':
                        store.delete(yt_key)
                        print(f"  ✓ Cleared failed YouTube record for {project_id}")
                        cleared += 1

                # Clear Instagram failed records
                ig_key = f"instagram/{project_id}"
                if store.exists(ig_key):
                    record = store.get(ig_key)
                    if record.get('status') == 'failed':
                        store.delete(ig_key)
                        print(f"  ✓ Cleared failed Instagram record for {project_id}")
                        cleared += 1

                # Clear Facebook failed records
                fb_key = f"facebook/{project_id}"
                if store.exists(fb_key):
                    record = store.get(fb_key)
                    if record.get('status') == 'failed':
                        store.delete(fb_key)
                        print(f"  ✓ Cleared failed Facebook record for {project_id}")
                        cleared += 1

            except Exception as e:
                print(f"  ✗ Failed to process {project_id}: {str(e)}")

        print(f"✓ Cleared {cleared} failed publish records")
        return cleared

    except Exception as e:
        print(f"✗ Failed to initialize PublishStore: {str(e)}")
        print("  This is expected if Firebase credentials are missing.")
        return 0

def main():
    print(f"=== OpenMontage Publishing Fix ===")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Step 1: Clear stuck records
    clear_stuck_records()

    # Step 2: Force retry of failed publishes
    force_retry_publish()

    print("\n✅ Publishing fix completed!")
    print("You can now run the publishing scripts:")
    print("  docker exec openmontage_scheduler python3 /app/scripts/publish_active_projects.py --retry-failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())