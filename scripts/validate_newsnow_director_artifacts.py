#!/usr/bin/env python3
"""Validate and ensure director stage artifacts exist at canonical paths.

If a Claude director run placed a valid script payload inside a nested checkpoint file
(e.g., projects/<id>/<id>/checkpoint_script.json) during the current run, promote it
to the flat canonical artifact path projects/<id>/artifacts/script_vi.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schemas.artifacts import validate_artifact


def _is_valid_script_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        # Strip text_vi before validation as it's not in the strict schema
        payload_for_validation = json.loads(json.dumps(payload))
        for sec in payload_for_validation.get("sections", []):
            if isinstance(sec, dict) and "text_vi" in sec:
                if "text" not in sec:
                    sec["text"] = sec["text_vi"]
                del sec["text_vi"]
        validate_artifact("script", payload_for_validation)
    except Exception:
        return False

    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return False

    for section in sections:
        if not isinstance(section, dict):
            return False
        text = section.get("text_vi") or section.get("text")
        if isinstance(text, str) and text.strip():
            return True

    return False


def _load_nested_checkpoint_script(project_dir: Path, min_mtime_ns: int = 0) -> Optional[Dict[str, Any]]:
    # Look for nested checkpoint produced under projects/<id>/<id>/
    candidates = sorted(project_dir.glob("*/checkpoint_script.json"))
    for candidate in candidates:
        if min_mtime_ns and candidate.stat().st_mtime_ns < min_mtime_ns:
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        artifacts = data.get("artifacts")
        if isinstance(artifacts, dict) and "script" in artifacts:
            script_payload = artifacts["script"]
            if _is_valid_script_payload(script_payload):
                return script_payload

    return None


def validate_and_promote_director_artifacts(project_dir: Path, min_mtime_ns: int = 0) -> bool:
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    canonical_script = artifacts_dir / "script_vi.json"

    if canonical_script.is_file():
        try:
            data = json.loads(canonical_script.read_text(encoding="utf-8"))
            if _is_valid_script_payload(data):
                return True
        except (OSError, json.JSONDecodeError):
            pass

    # Attempt promotion from a current nested checkpoint
    promoted_payload = _load_nested_checkpoint_script(project_dir, min_mtime_ns=min_mtime_ns)
    if promoted_payload:
        tmp = canonical_script.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(promoted_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(canonical_script)
        return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure NewsNow director artifacts exist at canonical paths")
    parser.add_argument("project_dir", type=Path, help="Path to project directory")
    parser.add_argument("--min-mtime-ns", type=int, default=0, help="Minimum allowed checkpoint mtime nanoseconds")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        print(f"ERROR: project directory does not exist: {project_dir}", file=sys.stderr)
        return 1

    ok = validate_and_promote_director_artifacts(project_dir, min_mtime_ns=args.min_mtime_ns)
    if not ok:
        print(f"ERROR: missing or invalid canonical script artifact for {project_dir.name}", file=sys.stderr)
        return 1

    print(f"✓ Validated director artifacts for {project_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
