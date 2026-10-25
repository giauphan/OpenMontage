"""Independent QA validator and cryptographic integrity verification for Fixed Niche videos."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from lib.fixed_niche.policy import load_locked_policy, LockedNichePolicy
from lib.fixed_niche.storyboard import FixedNicheStoryboardDirector

logger = logging.getLogger(__name__)


class FixedNicheQAValidator:
    """Rigorous independent QA validator for Practical AI Agent Engineering deliverables."""

    def __init__(self, policy: Optional[LockedNichePolicy] = None):
        self.policy = policy or load_locked_policy()
        self.storyboard_director = FixedNicheStoryboardDirector(self.policy.policy_sha256)

    @staticmethod
    def compute_sha256(path: Path) -> str:
        """Compute SHA256 checksum of a file."""
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def verify_audio_and_release_integrity(self, project_dir: Path) -> bool:
        """Verify that audio and video files on disk match the signed approval records.

        If any byte-level mutation is detected, the approval is immediately invalidated.
        """
        project_dir = Path(project_dir)
        app_path = project_dir / "approval.json"
        if not app_path.is_file():
            return False

        try:
            app_data = json.loads(app_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        if not app_data.get("approved"):
            return False

        audio_path = project_dir / "assets" / "narration.mp3"
        video_path = project_dir / "renders" / "final_short_en_US_9x16.mp4"

        for key, path, status in (
            ("audio_sha256", audio_path, "INVALIDATED_BY_AUDIO_MUTATION"),
            ("video_sha256", video_path, "INVALIDATED_BY_VIDEO_TAMPERING"),
        ):
            expected = app_data.get(key) or (app_data.get("media_sha256") if key == "video_sha256" else None)
            if not expected or not path.is_file() or self.compute_sha256(path).lower() != str(expected).lower():
                app_data["approved"] = False
                app_data["status"] = status if expected and path.is_file() else "INVALIDATED_MISSING_SIGNATURE"
                app_path.write_text(json.dumps(app_data, indent=2), encoding="utf-8")
                return False

        if "signature" in app_data:
            try:
                from lib.qa_signing import verify_approval_record
                pid = str(app_data.get("project_id") or project_dir.name)
                is_valid, reason = verify_approval_record(app_data, project_id=pid)
                if not is_valid:
                    app_data["approved"] = False
                    app_data["status"] = "INVALIDATED_BY_SIGNATURE_FORGERY"
                    app_path.write_text(json.dumps(app_data, indent=2), encoding="utf-8")
                    return False
            except Exception as sig_err:
                logger.warning(f"Signature verification error: {sig_err}")
                return False

        return True

    def audit_fixed_niche_deliverable(
        self,
        project_dir: Path,
        expected_duration: float = 72.0,
        duration_tolerance: float = 3.0,
    ) -> Dict[str, Any]:
        """Audit all technical and editorial deliverables for an agent engineering project."""
        project_dir = Path(project_dir)
        findings: List[Dict[str, str]] = []

        # 1. Scope & Policy hash audit
        scope_file = project_dir / "artifacts" / "fixed_niche_scope.json"
        if not scope_file.is_file():
            findings.append({"category": "SCOPE", "severity": "blocker", "message": "Missing fixed_niche_scope.json"})
        else:
            try:
                scope_data = json.loads(scope_file.read_text(encoding="utf-8"))
                trace = scope_data.get("scope_trace", {})
                if trace.get("niche_id") != self.policy.niche_id:
                    findings.append({"category": "SCOPE", "severity": "blocker", "message": f"Niche ID mismatch: {trace.get('niche_id')}"})
                if trace.get("policy_sha256") != self.policy.policy_sha256:
                    findings.append({"category": "POLICY_TAMPERING", "severity": "blocker", "message": "Policy SHA256 mismatch"})
            except Exception as e:
                findings.append({"category": "SCOPE", "severity": "blocker", "message": f"Malformed scope artifact: {e}"})

        # 2. Meaningful visual audit
        visual_plan_file = project_dir / "artifacts" / "news_visual_plan.json"
        if visual_plan_file.is_file():
            try:
                plan_data = json.loads(visual_plan_file.read_text(encoding="utf-8"))
                for beat in plan_data.get("beats", []):
                    aid = beat.get("asset_id")
                    if aid:
                        svg_path = project_dir / "assets" / "visuals" / f"{aid}.svg"
                        if svg_path.is_file():
                            content = svg_path.read_text(encoding="utf-8")
                            # Detect placeholder SVG fallback
                            if "fill=\"#0f172a\"" in content and "BeVietnamPro" in content and len(content) < 400:
                                findings.append({
                                    "category": "GENERIC_FALLBACK",
                                    "severity": "blocker",
                                    "message": f"Beat '{beat.get('beat_id')}' contains placeholder title rectangle",
                                })
            except Exception as e:
                findings.append({"category": "VISUAL", "severity": "blocker", "message": f"Visual plan audit error: {e}"})

        # 3. Frame samples audit
        frames_dir = project_dir / "renders" / "frame_samples"
        if frames_dir.is_dir():
            for frame_path in frames_dir.glob("*.png"):
                ok, reason = self.storyboard_director.validate_frame_sample(frame_path)
                if not ok:
                    findings.append({"category": "FRAME_QUALITY", "severity": "blocker", "message": f"{frame_path.name}: {reason}"})

        # 4. Duration compliance check
        ffprobe_file = project_dir / "renders" / "ffprobe.json"
        if ffprobe_file.is_file():
            try:
                probe_data = json.loads(ffprobe_file.read_text(encoding="utf-8"))
                fmt = probe_data.get("format", {})
                dur_str = fmt.get("duration")
                if dur_str:
                    dur = float(dur_str)
                    if not (65.0 - duration_tolerance <= dur <= 75.0 + duration_tolerance):
                        findings.append({
                            "category": "DURATION",
                            "severity": "blocker",
                            "message": f"Video duration {dur:.2f}s outside target [65.0, 75.0]s range",
                        })
            except Exception as e:
                findings.append({"category": "DURATION", "severity": "warning", "message": f"Could not parse ffprobe duration: {e}"})

        # 5. Claim ledger & Source snapshot provenance audit
        claim_ledger_file = project_dir / "artifacts" / "claim_ledger.json"
        snapshot_file = project_dir / "artifacts" / "source_snapshot.txt"
        proof_map_file = project_dir / "artifacts" / "video_proof_map.json"

        if not claim_ledger_file.is_file():
            findings.append({"category": "EVIDENCE", "severity": "blocker", "message": "Missing claim_ledger.json"})
        else:
            try:
                ledger_data = json.loads(claim_ledger_file.read_text(encoding="utf-8"))
                claims = ledger_data.get("claims", [])
                claim_by_id = {c.get("claim_id"): c for c in claims}

                for c in claims:
                    cid = c.get("claim_id")
                    if c.get("confidence") == "verified":
                        if not snapshot_file.is_file():
                            findings.append({
                                "category": "SNAPSHOT_PROVENANCE",
                                "severity": "blocker",
                                "message": f"Claim {cid} marked verified but source_snapshot.txt missing on disk",
                            })
                        else:
                            actual_sha = hashlib.sha256(snapshot_file.read_bytes()).hexdigest()
                            expected_sha = c.get("snapshot_sha256")
                            if expected_sha and actual_sha.lower() != str(expected_sha).lower():
                                findings.append({
                                    "category": "SNAPSHOT_PROVENANCE",
                                    "severity": "blocker",
                                    "message": f"Claim {cid} snapshot SHA256 mismatch: expected {expected_sha}, got {actual_sha}",
                                })

                # Audit proof-bearing beats against verified claims
                if not proof_map_file.is_file():
                    findings.append({
                        "category": "PROOF_MAP",
                        "severity": "blocker",
                        "message": "Missing video_proof_map.json artifact: technical claims must map to beat proofs",
                    })
                else:
                    try:
                        proof_data = json.loads(proof_map_file.read_text(encoding="utf-8"))
                        for pb in proof_data.get("beats", []):
                            bid = pb.get("beat_id")
                            is_proof_bearing = pb.get("is_proof_bearing", False) or pb.get("requires_real_demo", False)
                            cids = pb.get("claim_ids") or ([pb.get("claim_id")] if pb.get("claim_id") else [])
                            for ref_cid in cids:
                                ref_claim = claim_by_id.get(ref_cid)
                                if is_proof_bearing and (not ref_claim or ref_claim.get("confidence") != "verified"):
                                    findings.append({
                                        "category": "UNVERIFIED_CLAIM_IN_PROOF_BEAT",
                                        "severity": "blocker",
                                        "message": f"Proof-bearing beat '{bid}' references unverified claim '{ref_cid}' without snapshot provenance",
                                    })
                    except Exception as pe:
                        findings.append({"category": "EVIDENCE", "severity": "warning", "message": f"Proof map audit error: {pe}"})
            except Exception as e:
                findings.append({"category": "EVIDENCE", "severity": "blocker", "message": f"Malformed claim ledger: {e}"})

        blockers = [f for f in findings if f.get("severity") == "blocker"]
        strict_pass = len(blockers) == 0

        report = {
            "project_id": project_dir.name,
            "strict_quality_pass": strict_pass,
            "blockers_count": len(blockers),
            "findings": findings,
            "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # Write production_qa_report.json
        qa_report_path = project_dir / "artifacts" / "production_qa_report.json"
        qa_report_path.parent.mkdir(parents=True, exist_ok=True)
        qa_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        return report
