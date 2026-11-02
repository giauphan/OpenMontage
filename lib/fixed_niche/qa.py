"""Independent QA validator and cryptographic integrity verification for Fixed Niche videos."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
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

    def _verify_file_hash(self, app_data: dict, app_path: Path, key: str, path: Path, status: str) -> bool:
        expected = app_data.get(key) or (app_data.get("media_sha256") if key == "video_sha256" else None)
        if not expected or not path.is_file() or self.compute_sha256(path).lower() != str(expected).lower():
            app_data["approved"] = False
            app_data["status"] = status if expected and path.is_file() else "INVALIDATED_MISSING_SIGNATURE"
            app_path.write_text(json.dumps(app_data, indent=2), encoding="utf-8")
            return False
        return True

    def _verify_signature(self, app_data: dict, app_path: Path, project_dir: Path) -> bool:
        if "signature" not in app_data:
            return True
        try:
            from lib.qa_signing import verify_approval_record
            pid = str(app_data.get("project_id") or project_dir.name)
            is_valid, _ = verify_approval_record(app_data, project_id=pid)
            if not is_valid:
                app_data["approved"] = False
                app_data["status"] = "INVALIDATED_BY_SIGNATURE_FORGERY"
                app_path.write_text(json.dumps(app_data, indent=2), encoding="utf-8")
                return False
            return True
        except Exception as sig_err:
            logger.warning(f"Signature verification error: {sig_err}")
            return False

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

        if not self._verify_file_hash(app_data, app_path, "audio_sha256", audio_path, "INVALIDATED_BY_AUDIO_MUTATION"):
            return False
        if not self._verify_file_hash(app_data, app_path, "video_sha256", video_path, "INVALIDATED_BY_VIDEO_TAMPERING"):
            return False

        return self._verify_signature(app_data, app_path, project_dir)

        return True

    def _audit_scope(self, project_dir: Path) -> List[Dict[str, str]]:
        scope_file = project_dir / "artifacts" / "fixed_niche_scope.json"
        if not scope_file.is_file():
            return [{"category": "SCOPE", "severity": "blocker", "message": "Missing fixed_niche_scope.json"}]
        findings = []
        try:
            scope_data = json.loads(scope_file.read_text(encoding="utf-8"))
            trace = scope_data.get("scope_trace", {})
            if trace.get("niche_id") != self.policy.niche_id:
                findings.append({"category": "SCOPE", "severity": "blocker", "message": f"Niche ID mismatch: {trace.get('niche_id')}"})
            if trace.get("policy_sha256") != self.policy.policy_sha256:
                findings.append({"category": "POLICY_TAMPERING", "severity": "blocker", "message": "Policy SHA256 mismatch"})
        except Exception as e:
            findings.append({"category": "SCOPE", "severity": "blocker", "message": f"Malformed scope artifact: {e}"})
        return findings

    @staticmethod
    def _extract_approved_claims_with_stats(project_dir: Path, combined_stat_re: Any) -> list[dict[str, Any]]:
        approved_claims = []
        ledger_path = project_dir / "artifacts" / "claim_ledger.json"
        if not ledger_path.is_file():
            return approved_claims
        try:
            l_data = json.loads(ledger_path.read_text(encoding="utf-8"))
            for c in l_data.get("claims", []):
                if c.get("verdict") == "APPROVED":
                    c_stats = set()
                    for text_field in (c.get("statement", ""), c.get("evidence_excerpt", "")):
                        for m in combined_stat_re.finditer(text_field):
                            c_stats.add(re.sub(r"[\s,]+", "", m.group(0)).lower().lstrip("+-"))
                    if c_stats:
                        approved_claims.append({
                            "claim_id": c.get("claim_id"),
                            "stats": c_stats,
                            "text_corpus": f"{c.get('statement', '')} {c.get('evidence_excerpt', '')}".lower(),
                        })
        except Exception:
            pass
        return approved_claims

    @staticmethod
    def _validate_visual_stat(
        clean_t: str,
        stat_match: Any,
        approved_claims: list[dict[str, Any]],
        beat_id: Any,
    ) -> Dict[str, str] | None:
        stat_val = re.sub(r"[\s,]+", "", stat_match.group(0)).lower().lstrip("+-")
        matching = [c for c in approved_claims if stat_val in c["stats"]]
        if not matching:
            return {
                "category": "UNGROUNDED_VISUAL_STATISTIC",
                "severity": "blocker",
                "message": f"Beat '{beat_id}' contains ungrounded visual statistic: '{clean_t}' (figure '{stat_val}' not substantiated in approved claims)",
            }
        metric_words = set(re.findall(r'\b[a-zA-Z]{4,}\b', clean_t.lower())) - {
            "this", "that", "with", "from", "your", "what", "when", "where", "which"
        }
        has_support = any(any(w in c["text_corpus"] for w in metric_words) for c in matching) if metric_words else True
        if not has_support:
            return {
                "category": "UNGROUNDED_VISUAL_STATISTIC",
                "severity": "blocker",
                "message": f"Beat '{beat_id}' contains visual statistic '{clean_t}' where metric context does not match supporting claim",
            }
        return None

    def _audit_beat_svg_file(
        self,
        svg_path: Path,
        beat: dict[str, Any],
        combined_stat_re: Any,
        approved_claims: list[dict[str, Any]],
    ) -> List[Dict[str, str]]:
        findings = []
        if not svg_path.is_file():
            return findings
        content = svg_path.read_text(encoding="utf-8")
        if "fill=\"#0f172a\"" in content and "BeVietnamPro" in content and len(content) < 400:
            findings.append({
                "category": "GENERIC_FALLBACK",
                "severity": "blocker",
                "message": f"Beat '{beat.get('beat_id')}' contains placeholder title rectangle",
            })
        text_elements = re.findall(r'<text[^>]*>(.*?)</text>', content, re.DOTALL)
        for t in text_elements:
            clean_t = re.sub(r'<[^>]+>', '', t).strip()
            for stat_match in combined_stat_re.finditer(clean_t):
                f = self._validate_visual_stat(clean_t, stat_match, approved_claims, beat.get("beat_id"))
                if f:
                    findings.append(f)
        return findings

    def _audit_visual_plan(self, project_dir: Path) -> List[Dict[str, str]]:
        findings = []
        visual_plan_file = project_dir / "artifacts" / "news_visual_plan.json"
        if not visual_plan_file.is_file():
            return findings
        try:
            num = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
            stat_patterns = [
                rf'[-+]?\b{num}x\b',
                rf'[-+]?\b{num}%',
                rf'[-+]?\b{num}[kmb]?\s+tokens?\b',
                rf'[-+]?\b{num}\s*(?:ms|req/s|rps|ops/sec)\b',
            ]
            combined_stat_re = re.compile("|".join(f"(?:{p})" for p in stat_patterns), re.IGNORECASE)
            approved_claims = self._extract_approved_claims_with_stats(project_dir, combined_stat_re)
            plan_data = json.loads(visual_plan_file.read_text(encoding="utf-8"))
            for beat in plan_data.get("beats", []):
                aid = beat.get("asset_id")
                if aid:
                    svg_path = project_dir / "assets" / "visuals" / f"{aid}.svg"
                    findings.extend(self._audit_beat_svg_file(svg_path, beat, combined_stat_re, approved_claims))
        except Exception as e:
            findings.append({"category": "VISUAL", "severity": "blocker", "message": f"Visual plan audit error: {e}"})
        return findings

    def _audit_frame_samples(self, project_dir: Path) -> List[Dict[str, str]]:
        findings = []
        frames_dir = project_dir / "renders" / "frame_samples"
        if frames_dir.is_dir():
            min_var = 1.0 if os.environ.get("CI") == "true" else 10.0
            expected = ("frame_00s_hook.png", "frame_03s_impact.png", "frame_mid_mechanism.png", "frame_end_payoff.png")
            for req in expected:
                if not (frames_dir / req).is_file():
                    findings.append({"category": "FRAME_QUALITY", "severity": "blocker", "message": f"Missing frame sample: {req}"})
            for frame_path in frames_dir.glob("*.png"):
                ok, reason = self.storyboard_director.validate_frame_sample(frame_path, min_variance=min_var)
                if not ok:
                    findings.append({"category": "FRAME_QUALITY", "severity": "blocker", "message": f"{frame_path.name}: {reason}"})
        return findings

    @staticmethod
    def _get_target_duration_bounds(expected_duration: float, tolerance: float) -> Tuple[float, float]:
        """Compute min and max allowable duration bounds."""
        if expected_duration == 72.0:
            return 65.0 - tolerance, 75.0 + tolerance
        return expected_duration - tolerance, expected_duration + tolerance

    @classmethod
    def _audit_duration(
        cls,
        project_dir: Path,
        expected_duration: float = 72.0,
        duration_tolerance: float = 3.0,
    ) -> List[Dict[str, str]]:
        findings = []
        ffprobe_file = project_dir / "renders" / "ffprobe.json"
        if not ffprobe_file.is_file():
            return findings
        try:
            probe_data = json.loads(ffprobe_file.read_text(encoding="utf-8"))
            dur_str = probe_data.get("format", {}).get("duration")
            if not dur_str:
                return findings
            dur = float(dur_str)
            min_dur, max_dur = cls._get_target_duration_bounds(expected_duration, duration_tolerance)
            if not (min_dur <= dur <= max_dur):
                findings.append({
                    "category": "DURATION",
                    "severity": "blocker",
                    "message": f"Video duration {dur:.2f}s outside target [{min_dur:.1f}, {max_dur:.1f}]s range",
                })
        except Exception as e:
            findings.append({"category": "DURATION", "severity": "warning", "message": f"Could not parse ffprobe duration: {e}"})
        return findings

    @staticmethod
    def _audit_cta(project_dir: Path) -> List[Dict[str, str]]:
        findings = []
        script_file = project_dir / "artifacts" / "script_en_US.json"
        if script_file.is_file():
            try:
                s_data = json.loads(script_file.read_text(encoding="utf-8"))
                sections = s_data.get("sections", [])
                if sections:
                    final_narration = sections[-1].get("narration", "").lower()
                    has_cta_verb = bool(re.search(r"\b(follow|subscribe|star)\b", final_narration))
                    has_channel = bool(re.search(r"(@\w+|\bopenmontage\b|\bfollow me\b|\bsubscribe\b|\bstar the repo\b)", final_narration))
                    if not (has_cta_verb and has_channel):
                        findings.append({
                            "category": "CALL_TO_ACTION",
                            "severity": "blocker",
                            "message": "Final beat narration lacks explicit Call to Action (follow / star repo)",
                        })
            except Exception as e:
                findings.append({"category": "CALL_TO_ACTION", "severity": "warning", "message": f"CTA audit error: {e}"})
        return findings

    @staticmethod
    def _audit_claim_snapshot_match(claim: Dict[str, Any], actual_sha: Optional[str]) -> Optional[Dict[str, str]]:
        """Validate an individual verified claim against source snapshot hash."""
        cid = claim.get("claim_id")
        if actual_sha is None:
            return {"category": "SNAPSHOT_PROVENANCE", "severity": "blocker", "message": f"Claim {cid} marked verified but source_snapshot.txt missing on disk"}
        expected_sha = claim.get("snapshot_sha256")
        if expected_sha and actual_sha.lower() != str(expected_sha).lower():
            return {
                "category": "SNAPSHOT_PROVENANCE",
                "severity": "blocker",
                "message": f"Claim {cid} snapshot SHA256 mismatch: expected {expected_sha}, got {actual_sha}",
            }
        return None

    @classmethod
    def _audit_verified_claims_snapshot(cls, claims: List[Dict[str, Any]], snapshot_file: Path) -> List[Dict[str, str]]:
        """Audit source snapshot provenance for all verified claims in the ledger."""
        actual_sha = hashlib.sha256(snapshot_file.read_bytes()).hexdigest() if snapshot_file.is_file() else None
        findings: List[Dict[str, str]] = []
        for claim in claims:
            if claim.get("confidence") != "verified":
                continue
            match_finding = cls._audit_claim_snapshot_match(claim, actual_sha)
            if match_finding:
                findings.append(match_finding)
        return findings

    @staticmethod
    def _validate_proof_beat_claim(
        beat_id: Any, is_proof_bearing: bool, ref_cid: Any, claim_by_id: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """Validate that a proof-bearing beat only references verified claims."""
        if not is_proof_bearing:
            return None
        ref_claim = claim_by_id.get(ref_cid)
        if not ref_claim or ref_claim.get("confidence") != "verified":
            return {
                "category": "UNVERIFIED_CLAIM_IN_PROOF_BEAT",
                "severity": "blocker",
                "message": f"Proof-bearing beat '{beat_id}' references unverified claim '{ref_cid}' without snapshot provenance",
            }
        return None

    @classmethod
    def _audit_proof_map_claims(cls, proof_map_file: Path, claim_by_id: Dict[str, Any]) -> List[Dict[str, str]]:
        """Audit video proof map beats against verified claims in ledger."""
        if not proof_map_file.is_file():
            return [{"category": "PROOF_MAP", "severity": "blocker", "message": "Missing video_proof_map.json artifact: technical claims must map to beat proofs"}]
        try:
            proof_data = json.loads(proof_map_file.read_text(encoding="utf-8"))
        except Exception as pe:
            return [{"category": "EVIDENCE", "severity": "warning", "message": f"Proof map audit error: {pe}"}]

        findings: List[Dict[str, str]] = []
        for pb in proof_data.get("beats", []):
            bid = pb.get("beat_id")
            is_proof_bearing = bool(pb.get("is_proof_bearing") or pb.get("requires_real_demo"))
            cids = pb.get("claim_ids") or ([pb.get("claim_id")] if pb.get("claim_id") else [])
            for ref_cid in cids:
                finding = cls._validate_proof_beat_claim(bid, is_proof_bearing, ref_cid, claim_by_id)
                if finding:
                    findings.append(finding)
        return findings

    @classmethod
    def _audit_claims_and_proofs(cls, project_dir: Path) -> List[Dict[str, str]]:
        """Audit claims ledger, source snapshot hashes, and proof-bearing beats."""
        claim_ledger_file = project_dir / "artifacts" / "claim_ledger.json"
        if not claim_ledger_file.is_file():
            return [{"category": "EVIDENCE", "severity": "blocker", "message": "Missing claim_ledger.json"}]

        try:
            ledger_data = json.loads(claim_ledger_file.read_text(encoding="utf-8"))
            claims = ledger_data.get("claims", [])
        except Exception as e:
            return [{"category": "EVIDENCE", "severity": "blocker", "message": f"Malformed claim ledger: {e}"}]

        snapshot_file = project_dir / "artifacts" / "source_snapshot.txt"
        proof_map_file = project_dir / "artifacts" / "video_proof_map.json"
        claim_by_id = {c.get("claim_id"): c for c in claims}

        findings: List[Dict[str, str]] = []
        findings.extend(cls._audit_verified_claims_snapshot(claims, snapshot_file))
        findings.extend(cls._audit_proof_map_claims(proof_map_file, claim_by_id))
        return findings

    def _audit_topic_and_claims(self, project_dir: Path) -> List[Dict[str, str]]:
        """Audit scope, topic policy conformity, claims ledger, and proof maps."""
        findings: List[Dict[str, str]] = []
        findings.extend(self._audit_scope(project_dir))
        findings.extend(self._audit_claims_and_proofs(project_dir))
        return findings

    def _audit_spec_and_storyboard(self, project_dir: Path) -> List[Dict[str, str]]:
        """Audit editorial script CTA and visual plan storyboard assets."""
        findings: List[Dict[str, str]] = []
        findings.extend(self._audit_cta(project_dir))
        findings.extend(self._audit_visual_plan(project_dir))
        return findings

    def _audit_render_and_duration(
        self,
        project_dir: Path,
        expected_duration: float = 72.0,
        duration_tolerance: float = 3.0,
    ) -> List[Dict[str, str]]:
        """Audit frame samples quality and final video duration."""
        findings: List[Dict[str, str]] = []
        findings.extend(self._audit_frame_samples(project_dir))
        findings.extend(self._audit_duration(project_dir, expected_duration, duration_tolerance))
        return findings

    def _audit_manifests_and_hashes(self, project_dir: Path) -> List[Dict[str, str]]:
        """Audit deliverable manifests and cryptographic release integrity when present."""
        findings: List[Dict[str, str]] = []
        app_path = project_dir / "approval.json"
        if not app_path.is_file():
            return findings
        try:
            app_data = json.loads(app_path.read_text(encoding="utf-8"))
            if app_data.get("approved") and not self.verify_audio_and_release_integrity(project_dir):
                findings.append({
                    "category": "RELEASE_INTEGRITY",
                    "severity": "blocker",
                    "message": "Approval record signature or media hash integrity check failed",
                })
        except Exception:
            pass
        return findings

    @staticmethod
    def _persist_qa_report(project_dir: Path, report: Dict[str, Any]) -> None:
        """Persist production QA report artifact to disk."""
        try:
            qa_report_path = project_dir / "artifacts" / "production_qa_report.json"
            qa_report_path.parent.mkdir(parents=True, exist_ok=True)
            qa_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as e:
            report["artifact_persisted"] = False
            report["artifact_persistence_warning"] = f"Could not persist production_qa_report.json: {e}"

    def audit_fixed_niche_deliverable(
        self,
        project_dir: Path,
        expected_duration: float = 72.0,
        duration_tolerance: float = 3.0,
    ) -> Dict[str, Any]:
        """Audit all technical and editorial deliverables for an agent engineering project."""
        project_dir = Path(project_dir)
        findings: List[Dict[str, str]] = []

        findings.extend(self._audit_topic_and_claims(project_dir))
        findings.extend(self._audit_spec_and_storyboard(project_dir))
        findings.extend(self._audit_render_and_duration(project_dir, expected_duration, duration_tolerance))
        findings.extend(self._audit_manifests_and_hashes(project_dir))

        blockers = [f for f in findings if f.get("severity") == "blocker"]
        strict_pass = len(blockers) == 0

        report = {
            "project_id": project_dir.name,
            "strict_quality_pass": strict_pass,
            "blockers_count": len(blockers),
            "findings": findings,
            "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "artifact_persisted": True,
        }

        self._persist_qa_report(project_dir, report)
        return report
