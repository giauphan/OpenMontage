#!/usr/bin/env python3
"""Dry-run or execute uniqueness document clearing for a publish topic.

Usage:
    python3 scripts/clear_uniqueness.py <topic_id> [--dry-run]

Without --dry-run, deletes all uniqueness documents for the given topic from
Firestore.  This is safe because uniqueness docs are purely an anti-duplicate
guard — they have no platform credentials and can always be recreated by a
fresh publish attempt.

Add to publish_manual_video.py --retry-failed path before store.claim()
so that previously-published topics can be republished.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.publish_store import PublishStore


def clear_uniqueness(store: PublishStore, topic: str, dry_run: bool = False) -> tuple[int, int]:
    """Delete uniqueness documents for a topic. Returns (found, deleted)."""
    base_url = store.base_url
    deleted = 0
    found = 0
    page_token = None
    while True:
        params = {"pageSize": 300}
        if page_token:
            params["pageToken"] = page_token
        try:
            r = store.session.get(base_url, params=params, timeout=30)
        except Exception as e:
            print(f"[ERROR] Could not list documents: {e}", file=sys.stderr)
            break
        if r.status_code != 200:
            print(f"[ERROR] List failed: {r.status_code} {r.text[:200]}", file=sys.stderr)
            break
        docs = r.json().get("documents", [])
        if not docs:
            break
        for doc in docs:
            fields = doc.get("fields", {})
            rec_type = fields.get("record_type", {}).get("stringValue", "")
            pub_key = fields.get("publish_key", {}).get("stringValue", "")
            if rec_type == "uniqueness" and topic in pub_key:
                found += 1
                doc_name = doc["name"]
                print(f"  FOUND uniqueness: {pub_key[:60]}")
                if not dry_run:
                    doc_url = f"{store.documents_url.split('/projects/', 1)[0]}/{doc_name}"
                    dr = store.session.delete(doc_url, timeout=30)
                    if dr.status_code == 200:
                        deleted += 1
                        print(f"  DELETED")
                    else:
                        print(f"  DELETE_FAILED: {dr.status_code}")
        page_token = r.json().get("nextPageToken")
        if not page_token:
            break
    return found, deleted


def main() -> int:
    ap = argparse.ArgumentParser(description="Clear uniqueness docs for a topic")
    ap.add_argument("topic", help="Topic ID (e.g. cand_62804ede094ca10c)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = ap.parse_args()

    store = PublishStore()
    found, deleted = clear_uniqueness(store, args.topic, dry_run=args.dry_run)

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"[{mode}] topic={args.topic} found={found} deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
