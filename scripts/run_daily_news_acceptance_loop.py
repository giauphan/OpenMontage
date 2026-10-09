#!/usr/bin/env python3
"""Run bounded acceptance verification; this never runs production or publishes."""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.daily_news_acceptance_loop import AcceptanceLoop


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--rehearsal-manifest", type=Path, action="append", default=[],
                        help="Repeat exactly three times, once for each independent full shell run")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--wall-seconds", type=float, default=900)
    parser.add_argument("--suite-timeout", type=float, default=600)
    args = parser.parse_args()
    if (args.max_attempts < 1 or not math.isfinite(args.wall_seconds)
            or not math.isfinite(args.suite_timeout) or args.wall_seconds <= 0 or args.suite_timeout <= 0):
        parser.error("attempt count and time limits must be finite and positive")
    # At most one explicit-interruption recovery; deterministic failures never retry.
    if args.max_attempts not in (1, 2):
        parser.error("max-attempts must be 1 or 2")
    return AcceptanceLoop(ROOT, args.state_dir, args.rehearsal_manifest,
                          args.max_attempts, args.wall_seconds, args.suite_timeout).run()


if __name__ == "__main__":
    raise SystemExit(main())
