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


def _normalize_script_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    try:
        normalized = json.loads(json.dumps(payload))
        if "version" in normalized:
            normalized["version"] = "1.0"

        if "title_vi" in normalized and "title" not in normalized:
            normalized["title"] = normalized["title_vi"]
        if "title_en" in normalized and "title" not in normalized:
            normalized["title"] = normalized["title_en"]
        if "title" not in normalized:
            normalized["title"] = "Untitled"

        if "total_duration" in normalized and "total_duration_seconds" not in normalized:
            normalized["total_duration_seconds"] = float(normalized["total_duration"])
        if "total_duration_secs" in normalized and "total_duration_seconds" not in normalized:
            normalized["total_duration_seconds"] = float(normalized["total_duration_secs"])
        if "total_duration_seconds" not in normalized:
            normalized["total_duration_seconds"] = 60.0

        if "sections" not in normalized and "scenes" in normalized and isinstance(normalized["scenes"], list):
            normalized["sections"] = normalized["scenes"]

        valid_root_keys = {"version", "title", "total_duration_seconds", "sections", "metadata", "voice_performance"}
        normalized = {k: v for k, v in normalized.items() if k in valid_root_keys}

        # Normalize voice_performance.provider_notes values to strings (schema requires string values)
        if "voice_performance" in normalized and isinstance(normalized["voice_performance"], dict):
            vp = normalized["voice_performance"]
            if "provider_notes" in vp and isinstance(vp["provider_notes"], dict):
                vp["provider_notes"] = {k: str(v) for k, v in vp["provider_notes"].items()}

        valid_enhancement_types = {"overlay", "broll", "diagram", "stat_card", "code_snippet", "animation"}
        valid_sec_keys = {"id", "label", "text", "start_seconds", "end_seconds", "speaker_directions",
                          "delivery_cues", "enhancement_cues", "pronunciation_guides", "source_ref"}
        accumulated_time = 0.0
        for idx, sec in enumerate(normalized.get("sections", [])):
            if not isinstance(sec, dict):
                continue

            sec["id"] = str(sec.get("id") or f"sec_{idx}")
            sec["text"] = sec.get("text") or sec.get("text_vi") or sec.get("text_va") or sec.get("narration_vi") or sec.get("narration")
            duration = sec.get("duration", sec.get("duration_secs", sec.get("duration_seconds")))
            if duration is not None:
                duration = float(duration)
                sec["start_seconds"] = accumulated_time
                sec["end_seconds"] = accumulated_time + duration
            else:
                sec["start_seconds"] = float(sec.get("start_seconds", accumulated_time))
                sec["end_seconds"] = float(sec.get("end_seconds", sec["start_seconds"]))
            accumulated_time = sec["end_seconds"]

            if isinstance(sec.get("enhancement_cues"), list):
                for cue in sec["enhancement_cues"]:
                    if isinstance(cue, dict) and cue.get("type") not in valid_enhancement_types:
                        cue["type"] = "overlay"

            for key in list(sec.keys()):
                if key not in valid_sec_keys:
                    del sec[key]

        validate_artifact("script", normalized)
    except Exception:
        return None

    sections = normalized.get("sections")
    if not isinstance(sections, list) or not sections:
        return None
    if not any(isinstance(section.get("text"), str) and section["text"].strip()
               for section in sections if isinstance(section, dict)):
        return None
    return normalized


def _is_valid_script_payload(payload: Any) -> bool:
    return _normalize_script_payload(payload) is not None


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
            normalized = _normalize_script_payload(artifacts["script"])
            if normalized is not None:
                return normalized

    return None


def _promote_to_canonical(canonical_script: Path, normalized: Dict[str, Any]) -> None:
    tmp = canonical_script.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(canonical_script)


def _has_required_compositions(project_dir: Path) -> bool:
    return all((project_dir / path).is_file() and (project_dir / path).stat().st_size > 0 for path in (
        "hyperframes/index.html",
        "hyperframes_reels/index.html",
    ))


def validate_and_promote_director_artifacts(project_dir: Path, min_mtime_ns: int = 0, require_compositions: bool = False) -> bool:
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    canonical_script = artifacts_dir / "script_vi.json"

    if canonical_script.is_file():
        try:
            normalized = _normalize_script_payload(json.loads(canonical_script.read_text(encoding="utf-8")))
            if normalized is not None:
                _promote_to_canonical(canonical_script, normalized)
                return not require_compositions or _has_required_compositions(project_dir)
        except (OSError, json.JSONDecodeError):
            pass

    # Fresh noncanonical script artifacts from the current director run.
    # Every promotion source is mtime-gated so stale output cannot pass.
    fallback_candidates = [artifacts_dir / "script.json"]
    for candidate in fallback_candidates:
        if not candidate.is_file():
            continue
        if min_mtime_ns and candidate.stat().st_mtime_ns < min_mtime_ns:
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        normalized = _normalize_script_payload(payload)
        if normalized is not None:
            _promote_to_canonical(canonical_script, normalized)
            return not require_compositions or _has_required_compositions(project_dir)

    # Attempt promotion from a current nested checkpoint
    promoted_payload = _load_nested_checkpoint_script(project_dir, min_mtime_ns=min_mtime_ns)
    if promoted_payload:
        _promote_to_canonical(canonical_script, promoted_payload)
        return not require_compositions or _has_required_compositions(project_dir)

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure NewsNow director artifacts exist at canonical paths")
    parser.add_argument("project_dir", type=Path, help="Path to project directory")
    parser.add_argument("--min-mtime-ns", type=int, default=0, help="Minimum allowed checkpoint mtime nanoseconds")
    parser.add_argument("--require-compositions", action="store_true", help="Require both canonical HyperFrames compositions")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        print(f"ERROR: project directory does not exist: {project_dir}", file=sys.stderr)
        return 1

    ok = validate_and_promote_director_artifacts(
        project_dir,
        min_mtime_ns=args.min_mtime_ns,
        require_compositions=args.require_compositions,
    )
    if not ok:
        required = "script artifact and both compositions" if args.require_compositions else "canonical script artifact"
        print(f"ERROR: missing or invalid {required} for {project_dir.name}", file=sys.stderr)
        return 1

    print(f"✓ Validated director artifacts for {project_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
