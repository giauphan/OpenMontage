#!/usr/bin/env python3
"""Verify scheduled publication records for 2026-09-01."""
from tools.publish_store import PublishStore, publish_key

store = PublishStore()
projects = ['cand_80136a0e2ec3829c', 'cand_2ea8dd2abd94305d', 'cand_10a7c768f3a3a190']

print("=== 2026-09-01 PUBLISH STATE ===\n")
for proj in projects:
    print(f"Project: {proj}")
    for plat, kind in [('youtube', 'short'), ('facebook', 'video')]:
        key = publish_key('2026-09-01', proj, plat, kind)
        doc = store.get(key)
        if doc:
            status = doc.get('status', 'unknown')
            url = doc.get('video_url', '')
            scheduled_for = doc.get('scheduled_for', '')
            print(f"  {plat}/{kind}: {status} @ {scheduled_for} -> {url}")
        else:
            print(f"  {plat}/{kind}: no record")
    print()
