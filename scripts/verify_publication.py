#!/usr/bin/env python3
"""Encode cand_62804ede094ca10c publication state into an exit code + compact stdout."""
import sys
sys.path.insert(0, "/app")
from tools.publish_store import PublishStore  # noqa: E402

DEFECTIVE = {"07Ol9RX2xyM", "18114815959765217", "1381660060190961"}
PREFIX = "cand_62804ede094ca10c"

def decode(doc):
    fields = doc.get("fields", {})
    out = {}
    for k, v in fields.items():
        if "stringValue" in v: out[k] = v["stringValue"]
        elif "integerValue" in v: out[k] = v["integerValue"]
        elif "booleanValue" in v: out[k] = v["booleanValue"]
    return out

def main():
    store = PublishStore()
    r = store.session.get(store.base_url, params={"pageSize": 100}, timeout=30)
    if r.status_code != 200:
        print("LIST_ERR", r.status_code)
        return 5
    docs = r.json().get("documents", [])
    rows = [decode(d) for d in docs]
    match = [x for x in rows if PREFIX in (x.get("key") or "")]
    if not match:
        print("NO_RECORDS")
        return 4
    new_live = 0
    old = 0
    pub = 0
    for x in match:
        st = x.get("status"); vid = x.get("video_id"); pl = x.get("platform")
        print(f"P={pl} S={st} V={vid}")
        if st == "published":
            pub += 1
            if vid and vid not in DEFECTIVE:
                new_live += 1
            else:
                old += 1
    print(f"SUMMARY published={pub} new_live={new_live} old={old}")
    if new_live >= 1:
        return 0                       # a NEW (non-defective) video is live
    if pub and old == pub:
        return 1                       # only the defective originals are live
    return 2                           # in transition (replaced/uploading/failed)

if __name__ == "__main__":
    sys.exit(main())