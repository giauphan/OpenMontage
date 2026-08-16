#!/usr/bin/env python3
"""Ad-hoc inspector: show YouTube publish/uniqueness state for given project dirs."""
import json
import sys
from pathlib import Path

from tools.publish_store import PublishStore, file_sha256, publish_key, uniqueness_key

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "primary"
KINDS = [("short", "yt_shorts")]


def main():
    store = PublishStore()
    for proj in sys.argv[1:]:
        meta = json.loads((ROOT / "projects" / proj / "publish_metadata.json").read_text())
        pid = meta["id"]
        print("===", proj)
        for kind, field in KINDS:
            asset = ROOT / meta[field]
            if not asset.is_file():
                print(f"  {kind}: MISSING {asset}")
                continue
            sha = file_sha256(asset)
            for itype, value in [
                ("source", sha),
                ("source_path", str(asset.resolve())),
                ("title", meta["title"]),
                ("topic", pid),
            ]:
                rec = store.get(uniqueness_key("youtube", ACCOUNT, kind, itype, value))
                if rec:
                    print(
                        f"  {kind} {itype}: status={rec.get('status')} date={rec.get('date')} "
                        f"vid={rec.get('video_id')} url={rec.get('video_url')} "
                        f"pubkey={rec.get('publish_key')}"
                    )


if __name__ == "__main__":
    main()
