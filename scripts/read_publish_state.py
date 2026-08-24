#!/usr/bin/env python3
"""Read-only: dump PublishStore docs for a candidate (Firestore ListDocuments),
and print a compact stdout summary."""
import sys
import json
from pathlib import Path
sys.path.insert(0, "/app")
from tools.publish_store import PublishStore  # noqa: E402

OUT = Path("/app/.scr_pub_state.txt")

def decode(doc):
    fields = doc.get("fields", {})
    out = {}
    for k, v in fields.items():
        if "stringValue" in v: out[k] = v["stringValue"]
        elif "integerValue" in v: out[k] = v["integerValue"]
        elif "booleanValue" in v: out[k] = v["booleanValue"]
        elif "timestampValue" in v: out[k] = v["timestampValue"]
        elif "nullValue" in v: out[k] = None
        else: out[k] = json.dumps(v)[:120]
    return out

def list_all(store):
    r = store.session.get(store.base_url, params={"pageSize": 100}, timeout=30)
    if r.status_code != 200:
        return None, (r.status_code, (r.text or "")[:400])
    return r.json().get("documents", []), None

def main(prefix):
    store = PublishStore()
    docs, err = list_all(store)
    if err:
        print(f"LIST_ERROR status={err[0]} msg={err[1]}")
        return 1
    rows = [decode(d) for d in docs]
    matched = [r for r in rows if prefix in (r.get("key") or r.get("id") or "")]
    with OUT.open("w", encoding="utf-8") as f:
        f.write(f"TOTAL_DOCS={len(rows)}\n")
        for r in matched:
            f.write("KEY=" + str(r.get("key")) + "\n")
            for fld in ("date", "platform", "kind", "topic", "status",
                        "video_id", "video_url", "published_at", "updated_at", "error"):
                if r.get(fld):
                    f.write(f"{fld.upper()}={str(r[fld])[:240]}\n")
            f.write("---\n")
    # Compact stdout summary.
    print(f"TOTAL={len(rows)} MATCH={len(matched)}")
    for r in matched:
        print(f"ROW platform={r.get('platform')} kind={r.get('kind')} status={r.get('status')} vid={r.get('video_id')} url={(r.get('video_url') or '')[:70]}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "cand_62804ede094ca10c"))