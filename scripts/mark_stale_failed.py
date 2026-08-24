#!/usr/bin/env python3
"""Authorized: mark cand_62804ede094ca10c's stale DEFECTIVE records as 'failed'
so the publisher --retry-failed will REPLACE them with verified uploads.
Preserves old video ids in the record for audit. Prints compact confirmation."""
import sys
sys.path.insert(0, "/app")
from tools.publish_store import PublishStore  # noqa: E402

KEYS = [
    "2026-08-23_facebook_cand_62804ede094ca10c_page_video",
    "2026-08-23_instagram_cand_62804ede094ca10c_reels",
    "2026-08-23_youtube_cand_62804ede094ca10c_short",
]

def main():
    store = PublishStore()
    for key in KEYS:
        doc = store.get(key)
        if doc is None:
            print(f"KEY {key} MISSING")
            continue
        old_status = doc.get("status")
        old_vid = doc.get("video_id")
        upd = {
            "status": "failed",
            "previous_status": old_status,
            "old_video_id": old_vid,
            "replaced_intent": "verified replacement",
            "replaced_at": None,
        }
        try:
            store.update(key, upd)
            print(f"MARKED_FAIL {key} oldstatus={old_status} oldvid={old_vid}")
        except Exception as e:
            print(f"MARK_FAIL {key} err={e}")

if __name__ == "__main__":
    main()