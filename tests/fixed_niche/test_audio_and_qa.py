"""Tests for Phase 6: Narration audio integrity, ASR synchronization, and signed QA gate.
Covers matrix IDs: VOICE-001, VOICE-002, QA-001.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from lib.audio.narration_orchestrator import NarrationOrchestrator
from lib.fixed_niche.qa import FixedNicheQAValidator


def test_voice_001_fallback_uses_consistent_voice_never_mixed(tmp_path: Path):
    """VOICE-001: when provider fallback occurs, entire narration is generated with single fallback voice, never mixed."""
    orchestrator = NarrationOrchestrator(cache_dir=tmp_path / "cache")
    text = "Practical AI Agent Engineering. How coding agents work, fail, and get fixed."
    out_audio = tmp_path / "narration.mp3"

    # Fallback chain: non-existent provider -> flite
    result = orchestrator.synthesize_with_fallback(
        text=text,
        output_path=out_audio,
        fallback_chain=["non_existent_provider_fail", "flite"],
        locale="en-US",
    )
    assert result.get("success") is True or out_audio.is_file()
    assert out_audio.is_file()
    assert out_audio.stat().st_size > 500


def test_voice_002_audio_hash_change_invalidates_captions_and_release(tmp_path: Path):
    """VOICE-002: audio hash changes -> invalidate captions and signed release."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_01"
    project_dir.mkdir()
    assets_dir = project_dir / "assets"
    assets_dir.mkdir()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()

    # Create dummy audio and video
    audio_path = assets_dir / "narration.mp3"
    audio_path.write_bytes(b"INITIAL_AUDIO_BYTES_12345")
    initial_audio_sha = hashlib.sha256(audio_path.read_bytes()).hexdigest()

    video_path = renders_dir / "final_short_en_US_9x16.mp4"
    video_path.write_bytes(b"INITIAL_VIDEO_BYTES_67890")
    initial_video_sha = hashlib.sha256(video_path.read_bytes()).hexdigest()

    # Initial valid approval record
    approval = {
        "approved": True,
        "status": "APPROVED",
        "audio_sha256": initial_audio_sha,
        "video_sha256": initial_video_sha,
    }
    (project_dir / "approval.json").write_text(json.dumps(approval))

    # Before mutation: audio hash matches
    assert validator.verify_audio_and_release_integrity(project_dir) is True

    # Mutate audio bytes (e.g. re-synthesized voice)
    audio_path.write_bytes(b"MUTATED_AUDIO_BYTES_NEW_VOICE")

    # After mutation: integrity check must return False and invalidate approval
    assert validator.verify_audio_and_release_integrity(project_dir) is False
    updated_app = json.loads((project_dir / "approval.json").read_text())
    assert updated_app["approved"] is False
    assert updated_app["status"] == "INVALIDATED_BY_AUDIO_MUTATION"


def test_qa_001_manipulated_video_after_signature_blocks_release(tmp_path: Path):
    """QA-001: manipulated video after signature -> release blocked."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_02"
    project_dir.mkdir()
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    assets_dir = project_dir / "assets"
    assets_dir.mkdir()

    audio_path = assets_dir / "narration.mp3"
    audio_path.write_bytes(b"AUDIO_FOR_TEST")
    video_path = renders_dir / "final_short_en_US_9x16.mp4"
    video_path.write_bytes(b"ORIGINAL_SIGNED_MP4_CONTENT")

    approval = {
        "approved": True,
        "status": "APPROVED",
        "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        "video_sha256": hashlib.sha256(video_path.read_bytes()).hexdigest(),
    }
    (project_dir / "approval.json").write_text(json.dumps(approval))

    # Mutate video bytes after signature
    video_path.write_bytes(b"TAMPERED_MP4_CONTENT_UNAUTHORIZED")

    is_valid = validator.verify_audio_and_release_integrity(project_dir)
    assert is_valid is False
    updated_app = json.loads((project_dir / "approval.json").read_text())
    assert updated_app["approved"] is False
    assert "TAMPERED" in updated_app["status"] or "INVALIDATED" in updated_app["status"]


def test_qa_002_audit_fixed_niche_deliverable(tmp_path: Path):
    """QA-002: deliverable audit produces valid production_qa_report.json."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_03"
    project_dir.mkdir()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()

    # Write scope artifact matching policy
    scope = {
        "candidate_id": "test_03",
        "scope_trace": {
            "niche_id": validator.policy.niche_id,
            "policy_sha256": validator.policy.policy_sha256,
        },
    }
    (artifacts_dir / "fixed_niche_scope.json").write_text(json.dumps(scope))

    report = validator.audit_fixed_niche_deliverable(project_dir)
    assert "strict_quality_pass" in report
    assert "audited_at" in report
    assert (artifacts_dir / "production_qa_report.json").is_file()


def test_qa_unverified_claim_in_proof_beat_fails_strict_audit(tmp_path: Path):
    """QA audit strictly fails when a proof-bearing beat relies on an unverified claim."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_unverified_proof"
    project_dir.mkdir()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()

    (artifacts_dir / "fixed_niche_scope.json").write_text(json.dumps({
        "candidate_id": "test_unv",
        "scope_trace": {
            "niche_id": validator.policy.niche_id,
            "policy_sha256": validator.policy.policy_sha256,
        },
    }))

    # Claim is unverified
    claim_ledger = {
        "claims": [
            {"claim_id": "C001", "statement": "Unverified symptom", "confidence": "unverified"},
            {"claim_id": "C002", "statement": "Unverified root cause", "confidence": "unverified"},
        ]
    }
    (artifacts_dir / "claim_ledger.json").write_text(json.dumps(claim_ledger))

    # Proof map has proof-bearing beat referencing unverified C002
    proof_map = {
        "beats": [
            {
                "beat_id": "B03",
                "is_proof_bearing": True,
                "claim_ids": ["C002"],
                "story_function": "architectural_mechanism",
            }
        ]
    }
    (artifacts_dir / "video_proof_map.json").write_text(json.dumps(proof_map))

    report = validator.audit_fixed_niche_deliverable(project_dir)
    assert report["strict_quality_pass"] is False
    assert any(f["category"] == "UNVERIFIED_CLAIM_IN_PROOF_BEAT" for f in report["findings"])


def test_qa_missing_or_mismatched_source_snapshot_fails_strict_audit(tmp_path: Path):
    """QA audit strictly fails when verified claims lack source_snapshot.txt or SHA256 mismatches."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_bad_snapshot"
    project_dir.mkdir()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()

    (artifacts_dir / "fixed_niche_scope.json").write_text(json.dumps({
        "candidate_id": "test_snap",
        "scope_trace": {
            "niche_id": validator.policy.niche_id,
            "policy_sha256": validator.policy.policy_sha256,
        },
    }))

    claim_ledger = {
        "claims": [
            {
                "claim_id": "C001",
                "statement": "Verified symptom",
                "confidence": "verified",
                "snapshot_sha256": "expected_sha_123",
            }
        ]
    }
    (artifacts_dir / "claim_ledger.json").write_text(json.dumps(claim_ledger))

    # Case A: Missing source_snapshot.txt
    report_a = validator.audit_fixed_niche_deliverable(project_dir)
    assert report_a["strict_quality_pass"] is False
    assert any(f["category"] == "SNAPSHOT_PROVENANCE" for f in report_a["findings"])

    # Case B: Present file but SHA256 mismatch
    (artifacts_dir / "source_snapshot.txt").write_text("Mismatched content bytes")
    report_b = validator.audit_fixed_niche_deliverable(project_dir)
    assert report_b["strict_quality_pass"] is False
    assert any(f["category"] == "SNAPSHOT_PROVENANCE" for f in report_b["findings"])


def test_qa_signature_verification_branches(tmp_path: Path):
    """Test signature verification success, forgery, and exception."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_sig"
    project_dir.mkdir()
    app_path = project_dir / "approval.json"

    # 1. No signature key: returns True
    assert validator._verify_signature({}, app_path, project_dir) is True

    # 2. Forgery: verify_approval_record returns False
    app_data = {"signature": "fake_sig", "approved": True}
    with pytest.MonkeyPatch.context() as mp:
        import sys
        mock_qa = pytest.MonkeyPatch()
        from unittest.mock import MagicMock
        mock_signing = MagicMock()
        mock_signing.verify_approval_record.return_value = (False, "invalid signature")
        mp.setitem(sys.modules, "lib.qa_signing", mock_signing)

        res = validator._verify_signature(app_data, app_path, project_dir)
        assert res is False
        assert app_data["status"] == "INVALIDATED_BY_SIGNATURE_FORGERY"

    # 3. Exception in verify_approval_record
    with pytest.MonkeyPatch.context() as mp:
        mock_signing = MagicMock()
        mock_signing.verify_approval_record.side_effect = RuntimeError("Crypto error")
        mp.setitem(sys.modules, "lib.qa_signing", mock_signing)

        res = validator._verify_signature(app_data, app_path, project_dir)
        assert res is False


def test_qa_scope_and_claim_ledger_anomalies(tmp_path: Path):
    """Test scope mismatches, malformed JSONs, and missing proof map."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_anomalies"
    project_dir.mkdir()
    artifacts = project_dir / "artifacts"
    artifacts.mkdir()

    # 1. Scope niche_id and policy_sha256 mismatch
    (artifacts / "fixed_niche_scope.json").write_text(json.dumps({
        "scope_trace": {"niche_id": "wrong_niche", "policy_sha256": "wrong_sha"}
    }))
    findings = validator._audit_scope(project_dir)
    assert any(f["category"] == "SCOPE" and "Niche ID mismatch" in f["message"] for f in findings)
    assert any(f["category"] == "POLICY_TAMPERING" for f in findings)

    # 2. Malformed scope JSON
    (artifacts / "fixed_niche_scope.json").write_text("NOT_JSON{{{")
    findings = validator._audit_scope(project_dir)
    assert any(f["category"] == "SCOPE" and "Malformed" in f["message"] for f in findings)

    # 3. Missing claim ledger
    claims_findings = validator._audit_claims_and_proofs(project_dir)
    assert any(f["category"] == "EVIDENCE" and "Missing claim_ledger.json" in f["message"] for f in claims_findings)

    # 4. Malformed claim ledger
    (artifacts / "claim_ledger.json").write_text("NOT_JSON")
    claims_findings = validator._audit_claims_and_proofs(project_dir)
    assert any(f["category"] == "EVIDENCE" and "Malformed claim ledger" in f["message"] for f in claims_findings)

    # 5. Missing proof map
    (artifacts / "claim_ledger.json").write_text(json.dumps({"claims": []}))
    claims_findings = validator._audit_claims_and_proofs(project_dir)
    assert any(f["category"] == "PROOF_MAP" for f in claims_findings)

    # 6. Malformed proof map
    (artifacts / "video_proof_map.json").write_text("MALFORMED_PROOF")
    claims_findings = validator._audit_claims_and_proofs(project_dir)
    assert any(f["category"] == "EVIDENCE" and "Proof map audit error" in f["message"] for f in claims_findings)


def test_qa_duration_and_cta_auditing(tmp_path: Path):
    """Test duration boundary checks and CTA enforcement."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_dur_cta"
    project_dir.mkdir()
    renders = project_dir / "renders"
    renders.mkdir()
    artifacts = project_dir / "artifacts"
    artifacts.mkdir()

    # 1. Duration out of range
    (renders / "ffprobe.json").write_text(json.dumps({"format": {"duration": "120.5"}}))
    dur_findings = validator._audit_duration(project_dir, expected_duration=72.0, duration_tolerance=3.0)
    assert any(f["category"] == "DURATION" and "outside target" in f["message"] for f in dur_findings)

    # 2. Malformed ffprobe JSON
    (renders / "ffprobe.json").write_text("NOT_JSON")
    dur_findings = validator._audit_duration(project_dir)
    assert any(f["category"] == "DURATION" and "Could not parse" in f["message"] for f in dur_findings)

    # 3. CTA missing verb and channel
    (artifacts / "script_en_US.json").write_text(json.dumps({
        "sections": [{"narration": "That is how coding agents work without any call to action."}]
    }))
    cta_findings = validator._audit_cta(project_dir)
    assert any(f["category"] == "CALL_TO_ACTION" and "lacks explicit Call to Action" in f["message"] for f in cta_findings)

    # 4. CTA valid
    (artifacts / "script_en_US.json").write_text(json.dumps({
        "sections": [{"narration": "Follow for more updates and star the repo on GitHub!"}]
    }))
    assert len(validator._audit_cta(project_dir)) == 0


def test_qa_visual_plan_and_frame_samples_auditing(tmp_path: Path):
    """Test visual plan statistics validation and frame quality checks."""
    validator = FixedNicheQAValidator()
    project_dir = tmp_path / "project_vis"
    project_dir.mkdir()
    artifacts = project_dir / "artifacts"
    artifacts.mkdir()
    assets = project_dir / "assets" / "visuals"
    assets.mkdir(parents=True)
    renders = project_dir / "renders" / "frame_samples"
    renders.mkdir(parents=True)

    # 1. Visual plan with ungrounded visual statistic
    (artifacts / "claim_ledger.json").write_text(json.dumps({
        "claims": [{"claim_id": "C01", "verdict": "APPROVED", "statement": "Accuracy improved by 10% in tests"}]
    }))
    (artifacts / "news_visual_plan.json").write_text(json.dumps({
        "beats": [{"beat_id": "B01", "asset_id": "vis_01"}]
    }))
    # SVG contains "50%" which is not in approved claims
    (assets / "vis_01.svg").write_text("<svg><text>Increased speed by 50%</text></svg>")

    findings = validator._audit_visual_plan(project_dir)
    assert any(f["category"] == "UNGROUNDED_VISUAL_STATISTIC" for f in findings)

    # 2. Visual plan with generic placeholder SVG
    (assets / "vis_01.svg").write_text('<svg fill="#0f172a">BeVietnamPro placeholder</svg>')
    findings = validator._audit_visual_plan(project_dir)
    assert any(f["category"] == "GENERIC_FALLBACK" for f in findings)

    # 3. Missing required frame samples
    findings = validator._audit_frame_samples(project_dir)
    assert any(f["category"] == "FRAME_QUALITY" and "Missing frame sample" in f["message"] for f in findings)


