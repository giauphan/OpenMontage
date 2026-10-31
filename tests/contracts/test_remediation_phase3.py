"""Phase 3 Remediation Contract Tests: Render Binding, Timing & Frame-Level Proof.

Verifies:
- T11: Fail-closed on pre-render visual staging failure (no || true bypass)
- T12: Script/asset/plan hash changes after render QA invalidates approval
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest

from lib.qa_signing import sign_approval_record, verify_approval_record


def test_hash_change_invalidates_render(tmp_path: Path):
    """T12: Script or visual plan modification after approval invalidates verification."""
    proj = tmp_path / "proj_t12"
    proj.mkdir(parents=True)
    art = proj / "artifacts"
    art.mkdir()
    renders = proj / "renders"
    renders.mkdir()

    # 1. Create canonical on-disk artifacts
    script_file = art / "script_en_US.json"
    script_file.write_text(json.dumps({"title": "Test", "sections": [{"id": "sec_0", "text": "Original text"}]}))
    
    plan_file = art / "news_visual_plan.json"
    plan_file.write_text(json.dumps({"schema_version": "1.0", "beats": [{"id": "vb-01", "visual_intent": "Original"}]}))

    ledger_file = art / "claim_ledger.json"
    ledger_file.write_text(json.dumps({"claims": [{"claim_id": "C001", "statement": "Original"}]}))

    media_file = renders / "final_short_en_US_9x16.mp4"
    media_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 500)

    meta_file = proj / "publish_metadata.json"
    meta_file.write_text(json.dumps({"title": "Test", "media_path": "renders/final_short_en_US_9x16.mp4"}))

    # 2. Sign approval record
    approval = sign_approval_record(
        project_id="proj_t12",
        media_sha256=hashlib.sha256(media_file.read_bytes()).hexdigest(),
        claim_ledger_sha256=hashlib.sha256(ledger_file.read_bytes()).hexdigest(),
        reviewer="QA Supervisor",
        project_dir=proj,
        use_manifest=True,
    )
    (proj / "approval.json").write_text(json.dumps(approval, indent=2))

    # Initial verification should be valid
    valid, msg = verify_approval_record(approval, project_id="proj_t12", project_dir=proj, require_manifest=True)
    assert valid, f"Expected initial approval to be valid, got: {msg}"

    # 3. Modify script after approval
    script_file.write_text(json.dumps({"title": "Test", "sections": [{"id": "sec_0", "text": "TAMPERED text after approval"}]}))
    valid_after_script_tamper, msg1 = verify_approval_record(approval, project_id="proj_t12", project_dir=proj, require_manifest=True)
    assert not valid_after_script_tamper, "Expected script tamper to invalidate approval"
    assert "script SHA mismatch" in msg1

    # Restore script, then tamper visual plan
    script_file.write_text(json.dumps({"title": "Test", "sections": [{"id": "sec_0", "text": "Original text"}]}))
    plan_file.write_text(json.dumps({"schema_version": "1.0", "beats": [{"id": "vb-01", "visual_intent": "TAMPERED PLAN"}]}))
    valid_after_plan_tamper, msg2 = verify_approval_record(approval, project_id="proj_t12", project_dir=proj, require_manifest=True)
    assert not valid_after_plan_tamper, "Expected visual plan tamper to invalidate approval"
    assert "visual plan SHA mismatch" in msg2


def test_no_silent_staging_bypass():
    """T11: In scripts/run_daily_news_pipeline.sh, pre-render preparation must not use '|| true' bypass."""
    pipeline_sh = Path(__file__).resolve().parents[2] / "scripts" / "run_daily_news_pipeline.sh"
    content = pipeline_sh.read_text(encoding="utf-8")
    
    # Check that prepare_news_visuals.py is NOT run after render (which was around line 1238)
    assert 'prepare_news_visuals.py" "$PROJECT_DIR" >/dev/null 2>&1 || true' not in content, (
        "Post-render prepare_news_visuals.py with '|| true' must be removed from run_daily_news_pipeline.sh"
    )
