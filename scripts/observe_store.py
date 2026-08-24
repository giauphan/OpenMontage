#!/usr/bin/env python3
"""Read-only: paginate ALL PublishStore docs, filter candidate, print compact."""
import sys
import json
sys.path.insert(0, "/app")
from tools.publish_store import PublishStore  # noqa: E402

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "cand_62804ede094ca10c"
OUT = "/app/.scr_store_state.txt"

def decode(doc):
    out = {}
    for k, v in doc.get("fields", {}).items():
        t = v.keys() & {"stringValue", "integerValue", "booleanValue"}
        if "stringValue" in v: out[k] = v["stringValue"]
        elif "integerValue" in v: out[k] = v["integerValue"]
        elif "booleanValue" in v: out[k] = v["booleanValue"]
        elif "timestampValue" in v: out[k] = v["timestampValue"]
        else: out[k] = json.dumps(v)[:100]
    return out

def main():
    store = PublishStore()
    token = None
    rows = []
    while True:
        params = {"pageSize": 300}
        if token:
            params["pageToken"] = token
        r = store.session.get(store.base_url, params=params, timeout=40)
        if r.status_code != 200:
            print(f"LIST_ERR status={r.status_code} msg={(r.text or '')[:300]}")
            return 5
        data = r.json()
        rows.extend(data.get("documents", []))
        token = data.get("nextPageToken")
        if not token:
            break
        if len(rows) > 5000:
            break
    matched = []
    for d in rows:
        dec = decode(d)
        key = dec.get("key") or d.get("name", "").rsplit("/", 1)[-1]
        if PREFIX in key:
            dec["_key"] = key
            matched.append(dec)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"TOTAL_ALL={len(rows)} MATCH={len(matched)}\n")
        for x in matched:
            f.write("KEY=" + str(x.get("_key")) + "\n")
            for fld in ("date", "platform", "kind", "topic", "status",
                        "video_id", "video_url", "published_at", "updated_at",
                        "previous_status", "old_video_id", "error"):
                if x.get(fld):
                    f.write(f"{fld.upper()}={str(x[fld])[:220]}\n")
            f.write("---\n")
    print(f"TOTAL_ALL={len(rows)} MATCH={len(matched)}")
    for x in matched:
        print(f"ROW key={x.get('_key')} st={x.get('status')} vid={x.get('video_id') or ('-' )} url={(x.get('video_url') or '')[:60]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())