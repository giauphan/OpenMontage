#!/usr/bin/env python3
"""Offline fail-closed news evidence gate for a project workspace."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.news_evidence import MAX_SOURCE_AGE_HOURS, validate_news_evidence


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps({"ok": False, "status": "failed", "errors": [message]}, sort_keys=True))
        raise SystemExit(2)


def main() -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path, help="Project workspace containing artifacts/script_vi.json")
    parser.add_argument("--max-source-age-hours", type=float, required=True,
                        help=f"Explicit source freshness limit in (0, {MAX_SOURCE_AGE_HOURS:g}] hours")
    args = parser.parse_args()
    if not math.isfinite(args.max_source_age_hours) or not 0 < args.max_source_age_hours <= MAX_SOURCE_AGE_HOURS:
        result = {"ok": False, "status": "failed", "errors": [f"--max-source-age-hours must be finite and in (0, {MAX_SOURCE_AGE_HOURS:g}]"]}
    else:
        result = validate_news_evidence(args.project_dir, args.max_source_age_hours)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
