#!/usr/bin/env python3
"""CLI validator for diagram_animation_plan.json artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.visual_style import (
    DiagramAnimationPlan,
    evaluate_plan_qa,
    validate_diagram_plan_data,
)


def main():
    parser = argparse.ArgumentParser(description="Validate Diagram Animation Plan v1")
    parser.add_argument("plan_path", type=Path, help="Path to diagram_animation_plan.json or project directory")
    parser.add_argument("--strict", action="store_true", help="Enforce non-placeholder strict SHA256 hashes")
    args = parser.parse_args()

    plan_file = args.plan_path
    if plan_file.is_dir():
        plan_file = plan_file / "artifacts" / "diagram_animation_plan.json"

    if not plan_file.is_file():
        print(f"ERROR: Plan file not found at {plan_file}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(plan_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: Failed to parse JSON at {plan_file}: {exc}", file=sys.stderr)
        sys.exit(1)

    errors = validate_diagram_plan_data(data, strict_hashes=args.strict)
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} errors):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    plan = DiagramAnimationPlan.from_dict(data)
    qa_report = evaluate_plan_qa(plan, strict_hashes=args.strict)
    print(json.dumps(qa_report, indent=2))

    if qa_report["status"] != "PASS":
        sys.exit(1)

    print(f"SUCCESS: {plan_file} is valid.")
    sys.exit(0)


if __name__ == "__main__":
    main()
