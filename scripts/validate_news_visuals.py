#!/usr/bin/env python3
"""CLI wrapper for news visual QA validation.

Usage:
    python scripts/validate_news_visuals.py --project-dir <path> [--mode strict|flag_off|advisory]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.news_visual.qa import run_news_visual_qa


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate news video visual quality and coverage")
    parser.add_argument("--project-dir", required=True, type=Path, help="Path to project directory")
    parser.add_argument(
        "--mode",
        choices=["auto", "strict", "flag_off", "advisory"],
        default="auto",
        help="Validation mode (strict fails on any blocker; flag_off skips blocking; auto follows NEWS_VISUAL_MODE)",
    )
    args = parser.parse_args()

    if not args.project_dir.is_dir():
        print(f"Error: Project directory {args.project_dir} does not exist", file=sys.stderr)
        return 1

    report = run_news_visual_qa(args.project_dir, mode=args.mode)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not report.get("passed", False) and args.mode == "strict":
        print("Visual QA failed with blocking findings.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
