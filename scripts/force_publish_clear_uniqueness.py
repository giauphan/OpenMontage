#!/usr/bin/env python3
"""
Force publish by clearing uniqueness records from Firestore.
WARNING: This mutates Firestore — use only with explicit user authorization.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_store import PublishStore, uniqueness_key, normalize_identity, file_sha256, media_fingerprint


def clear_uniqueness_for_project(store: PublishStore, project_name: str, platform: str = "youtube", account: str = "primary", kind: str = "short"):
    """Clear all uniqueness records for a project on a given platform."""
    meta_file = Path("projects") / project_name / "publish_metadata.json"
    if not meta_file.is_file():
        print(f"❌ {project_name}: publish_metadata.json not found")
        return False

    meta = json.loads(meta_file.read_text())
    pid = meta["id"]
    title = meta.get("title", "")
    asset_path = Path("projects") / project_name / meta.get("asset_path", "renders/final_full.mp4")

    if not asset_path.is_file():
        print(f"❌ {project_name}: asset not found at {asset_path}")
        return False

    source_sha256 = file_sha256(asset_path)
    visual_sha256 = media_fingerprint(asset_path)
    source_topic = meta.get("source_topic", pid)

    identities = {
        "topic": pid,
        "title": title,
        "source_topic": source_topic,
        "source_path": str(asset_path.resolve()),
        "source_visual": visual_sha256,
        "source": source_sha256,
    }

    print(f"\n🔍 {project_name}:")
    print(f"   Topic: {pid}")
    print(f"   Title: {title}")

    cleared = []
    for identity_type, value in identities.items():
        unique_key = uniqueness_key(platform, account, kind, identity_type, value)
        rec = store.get(unique_key)
        if rec:
            try:
                # Delete the uniqueness record from Firestore
                store.session.delete(store._url(unique_key), timeout=30)
                cleared.append(identity_type)
                print(f"   ✓ Cleared {identity_type} uniqueness record")
            except Exception as e:
                print(f"   ❌ Failed to clear {identity_type}: {e}")
                return False
        else:
            print(f"   - {identity_type} uniqueness record not found (already clear)")

    if cleared:
        print(f"   ✅ Cleared {len(cleared)} uniqueness records")
        return True
    else:
        print(f"   ⚠️ No uniqueness records to clear (already fresh)")
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 force_publish_clear_uniqueness.py <project1> [<project2> ...]")
        print("Example: python3 force_publish_clear_uniqueness.py cand_84512389f8bd5d40 cand_03bd5f9a6df87841 cand_a3ab95da15808d74")
        sys.exit(1)

    projects = sys.argv[1:]
    store = PublishStore()

    print("=" * 80)
    print("FIRESTORE UNIQUENESS CLEAR — FORCE REPUBLISH")
    print("=" * 80)
    print(f"⚠️  This will DELETE uniqueness records from Firestore.")
    print(f"⚠️  Only proceed if explicitly authorized by the user.\n")

    success_count = 0
    for proj in projects:
        if clear_uniqueness_for_project(store, proj):
            success_count += 1

    print("\n" + "=" * 80)
    print(f"Summary: {success_count}/{len(projects)} projects cleared")
    print("=" * 80)

    if success_count == len(projects):
        print("✅ All projects cleared. Ready for fresh publish.")
        sys.exit(0)
    else:
        print("❌ Some projects failed to clear. Fix issues above and retry.")
        sys.exit(1)
