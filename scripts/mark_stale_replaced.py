#!/usr/bin/env python3
"""Authorized: mark cand_62804ede094ca10c's stale DEFECTIVE publish records as
'replaced' so the verified replacement can be published, preserving old ids.

Only touches the 3 keys for this candidate (facebook/instagram/youtube). Read-only
except the intended status flip. Prints compact confirmation.
"""
import sys
sys.path.insert(0, "/app")
from tools.publish_store import PublishStore  # noqa: E402

PREFIX = "cand_62804ede094ca10c"
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
        if old_status in ("replaced", "failed", "uploading"):
            # Already unblocked earlier; keep old id reference intact.
            upd = {"status": "replaced", "previous_status": old_status,
                   "replaced_for": "verified replacement", "replaced_at": None}
        else:
            upd = {"status": "replaced", "previous_status": old_status,
                   "old_video_id": old_vid, "replaced_for": "verified replacement",
                   "replaced_at": None}
        try:
            store.update(key, upd)
            print(f"MARKED {key}")
        except Exception as e:
            print(f"MARK_FAIL {key} err={e}")

if __name__ == "__main__":
    main()