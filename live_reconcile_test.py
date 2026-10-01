import sys, os
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.environ.get("OPENMONTAGE_ROOT", str(Path(__file__).resolve().parent)))

from tools.publish_store import PublishStore
from scripts.check_cleanup_eligibility import reconcile_scheduled_record, is_project_eligible_for_cleanup

def run():
    print(f"--- TIMESTAMPS: START {datetime.now(timezone.utc).isoformat()} ---")
    store = PublishStore()
    
    # Check queue
    cfg_file = Path("config/publish_schedule.json")
    if cfg_file.exists():
        print(f"\n--- QUEUE BEFORE ---")
        print(cfg_file.read_text())
    
    # Try reconciliation on one known project
    vid = "vq610Irj9O8"
    key = f"2026-09-30_youtube_test_reconcile"
    # Create dummy scheduled record for this run
    r = {
        "status": "scheduled",
        "scheduled_for": "2026-09-30T00:00:00Z",
        "platform": "youtube",
        "video_id": vid
    }
    print(f"\n--- RECONCILING VIDEO {vid} ---")
    updated = reconcile_scheduled_record(store, key, r)
    print(f"Status after: {updated.get('status')}")
    
    # Check cleanup eligibility
    print(f"\n--- CLEANUP SAFETY ---")
    project_id = "cand_78bef16961a32278"  # matches vq610Irj9O8
    elig, reason, _ = is_project_eligible_for_cleanup(project_id, store=store, date="2026-09-30")
    print(f"Project Eligible: {elig}")
    print(f"Reason: {reason}")
    
    print(f"\n--- TIMESTAMPS: END {datetime.now(timezone.utc).isoformat()} ---")

if __name__ == "__main__":
    run()
