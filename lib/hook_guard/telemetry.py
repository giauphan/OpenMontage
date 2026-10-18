"""Telemetry, structured logging, and canary metrics for HookGuard."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def record_hook_telemetry(
    project_id: str,
    project_dir: Optional[Path | str],
    hook_plan: dict[str, Any],
    baseline_fingerprint: str,
    final_fingerprint: str,
    render_runtime: str = "remotion",
    duration_variance_seconds: float = 0.0,
    publish_id: Optional[str] = None,
) -> dict[str, Any]:
    """Record comprehensive HookGuard execution record for audit and observability.
    
    Fields logged:
      - run_id / timestamp
      - project_id
      - hook policy & rule version
      - candidate count, selected_candidate_id, intent
      - reasons for skip/reject
      - baseline and final body EDL fingerprints
      - render runtime and duration variance
      - publish_id
    """
    guard_res = hook_plan.get("guard_result", {})
    selected_id = hook_plan.get("selected_candidate_id")
    candidates = hook_plan.get("candidates", [])
    selected_cand = next((c for c in candidates if c.get("id") == selected_id), {})

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "rule_version": guard_res.get("rule_version", "hookguard-1"),
        "policy": hook_plan.get("policy", {}),
        "overall_status": hook_plan.get("status", "UNKNOWN"),
        "guard_status": guard_res.get("status", "UNKNOWN"),
        "reason_codes": guard_res.get("reason_codes", []),
        "candidate_count": len(candidates),
        "selected_candidate_id": selected_id,
        "selected_intent": selected_cand.get("intent"),
        "selected_mode": selected_cand.get("mode"),
        "selected_text": selected_cand.get("text"),
        "baseline_body_edl_sha256": baseline_fingerprint,
        "final_body_edl_sha256": final_fingerprint,
        "fingerprints_match": (baseline_fingerprint == final_fingerprint),
        "render_runtime": render_runtime,
        "duration_variance_seconds": round(duration_variance_seconds, 3),
        "publish_id": publish_id,
    }

    if project_dir:
        pdir = Path(project_dir)
        artifacts_dir = pdir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        telemetry_file = artifacts_dir / "hook_telemetry.json"
        try:
            with open(telemetry_file, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2)
        except OSError as exc:
            logger.warning("Could not write hook telemetry to %s: %s", telemetry_file, exc)

    return entry
