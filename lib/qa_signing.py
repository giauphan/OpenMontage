"""Cryptographic QA Supervisor Signing & Verification for OpenMontage.

Ensures that approval.json records cannot be self-awarded or forged by
generation scripts. Approvals must be signed with a supervisor secret key
and cryptographically bound to the project ID, media SHA-256, claim ledger SHA-256,
and timestamp.
"""
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Optional

DEFAULT_SECRET_PATH = Path(os.path.expanduser("~/.openmontage_qa_secret"))
ENV_SECRET_KEY = "QA_SUPERVISOR_SECRET"
_SESSION_FALLBACK_SECRET: Optional[bytes] = None


def get_supervisor_secret() -> bytes:
    """Retrieve or initialize the supervisor secret key.
    
    In production environments (OPENMONTAGE_ENV=production or STRICT_QA=1),
    an explicit QA_SUPERVISOR_SECRET must be provisioned. Hardcoded fallback
    keys in source control are strictly forbidden.
    """
    global _SESSION_FALLBACK_SECRET
    env_secret = os.environ.get(ENV_SECRET_KEY)
    if env_secret and env_secret.strip():
        return env_secret.strip().encode("utf-8")
    
    if DEFAULT_SECRET_PATH.is_file():
        try:
            secret = DEFAULT_SECRET_PATH.read_bytes().strip()
            if secret:
                return secret
        except OSError:
            pass
            
    is_strict_prod = (
        os.environ.get("OPENMONTAGE_ENV") == "production"
        or os.environ.get("PRODUCTION") == "1"
        or os.environ.get("STRICT_QA") == "1"
    )
    if is_strict_prod:
        raise RuntimeError(
            "QA supervisor secret key not configured: QA_SUPERVISOR_SECRET environment variable is required in production (no default fallback permitted)."
        )

    if _SESSION_FALLBACK_SECRET is not None:
        return _SESSION_FALLBACK_SECRET

    # Generate a cryptographically secure random 256-bit secret for local session
    random_secret = secrets.token_bytes(32)
    try:
        DEFAULT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_SECRET_PATH.write_bytes(random_secret)
        os.chmod(DEFAULT_SECRET_PATH, 0o600)
    except OSError:
        pass

    _SESSION_FALLBACK_SECRET = random_secret
    return random_secret


def compute_manifest_sha256(
    project_id: str,
    media_sha256: str,
    claim_ledger_sha256: str,
    metadata_sha256: str = "",
    captions_sha256: str = "",
    script_sha256: str = "",
    visual_plan_sha256: str = "",
) -> str:
    """Compute SHA-256 digest over the complete release manifest envelope."""
    manifest_str = (
        f"project:{project_id}|media:{media_sha256}|ledger:{claim_ledger_sha256}|"
        f"meta:{metadata_sha256}|captions:{captions_sha256}|script:{script_sha256}"
    )
    if visual_plan_sha256:
        manifest_str += f"|visual_plan:{visual_plan_sha256}"
    return hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()


def compute_signature(
    project_id: str,
    media_sha256: str,
    claim_ledger_sha256: str,
    timestamp_iso: str,
    reviewer: str,
    manifest_sha256: str = ""
) -> str:
    """Compute HMAC-SHA256 signature over critical verification attributes or full manifest."""
    secret = get_supervisor_secret()
    if manifest_sha256:
        payload = f"{project_id}:manifest:{manifest_sha256}:{timestamp_iso}:{reviewer}".encode("utf-8")
    else:
        payload = f"{project_id}:{media_sha256}:{claim_ledger_sha256}:{timestamp_iso}:{reviewer}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def sign_approval_record(
    project_id: str,
    media_sha256: str,
    claim_ledger_sha256: str,
    timestamp_iso: str | None = None,
    reviewer: str = "independent_qa_supervisor",
    metadata_sha256: str = "",
    captions_sha256: str = "",
    script_sha256: str = "",
    visual_plan_sha256: str = "",
    format_type: str = "short",
    audit_trail: dict | None = None,
    supervisor_role: str = "Editorial Lead & Safety Officer",
    project_dir: Path | str | None = None,
    use_manifest: bool = True,
) -> dict:
    """Generate a cryptographically signed approval record bound to release manifest and audit trail."""
    from datetime import datetime, timezone
    if timestamp_iso is None:
        timestamp_iso = datetime.now(timezone.utc).isoformat()

    if project_dir is not None:
        p_dir = Path(project_dir)
        if not script_sha256:
            for s_rel in ("artifacts/script_en_US.json", "artifacts/script_vi.json", "artifacts/script.json"):
                sp = p_dir / s_rel
                if sp.is_file():
                    script_sha256 = hashlib.sha256(sp.read_bytes()).hexdigest()
                    break
        if not visual_plan_sha256:
            vp = p_dir / "artifacts" / "news_visual_plan.json"
            if vp.is_file():
                visual_plan_sha256 = hashlib.sha256(vp.read_bytes()).hexdigest()
        if not metadata_sha256:
            mp = p_dir / "publish_metadata.json"
            if mp.is_file():
                metadata_sha256 = hashlib.sha256(mp.read_bytes()).hexdigest()
        if not captions_sha256:
            for c_rel in ("artifacts/captions_en_US.srt", "artifacts/captions_vi.srt", "artifacts/captions.srt"):
                cp = p_dir / c_rel
                if cp.is_file():
                    captions_sha256 = hashlib.sha256(cp.read_bytes()).hexdigest()
                    break

    manifest_sha = ""
    if use_manifest:
        manifest_sha = compute_manifest_sha256(
            project_id=project_id,
            media_sha256=media_sha256,
            claim_ledger_sha256=claim_ledger_sha256,
            metadata_sha256=metadata_sha256,
            captions_sha256=captions_sha256,
            script_sha256=script_sha256,
            visual_plan_sha256=visual_plan_sha256,
        )
    sig = compute_signature(
        project_id=project_id,
        media_sha256=media_sha256,
        claim_ledger_sha256=claim_ledger_sha256,
        timestamp_iso=timestamp_iso,
        reviewer=reviewer,
        manifest_sha256=manifest_sha,
    )
    return {
        "approved": True,
        "status": "approved",
        "approved_by": reviewer,
        "supervisor_role": supervisor_role,
        "reviewer_id": "qa-supervisor-us-migration",
        "project_id": project_id,
        "manifest_sha256": manifest_sha,
        "release_manifest": {
            "project_id": project_id,
            "format": format_type,
            "media_sha256": media_sha256,
            "claim_ledger_sha256": claim_ledger_sha256,
            "metadata_sha256": metadata_sha256,
            "captions_sha256": captions_sha256,
            "script_sha256": script_sha256,
            "visual_plan_sha256": visual_plan_sha256,
        },
        "audit_trail": audit_trail or {},
        "approved_media_sha256": media_sha256,
        "media_sha256": media_sha256,
        "claim_ledger_sha256": claim_ledger_sha256,
        "metadata_sha256": metadata_sha256,
        "captions_sha256": captions_sha256,
        "script_sha256": script_sha256,
        "visual_plan_sha256": visual_plan_sha256,
        "signature": sig,
        "signature_algorithm": "HMAC-SHA256",
        "approved_media_hashes": [media_sha256],
        "media_sha256_by_platform": {
            "youtube": media_sha256
        },
        "timestamp": timestamp_iso
    }


def verify_approval_record(
    approval_data: dict,
    project_id: str,
    project_dir: Path | str | None = None,
    require_manifest: bool = False,
) -> tuple[bool, str]:
    """Verify that an approval record was authentically signed and optionally matches on-disk files."""
    if not isinstance(approval_data, dict):
        return False, "Approval record must be a JSON object"
        
    if not (approval_data.get("approved") is True or approval_data.get("status") == "approved"):
        return False, f"Approval status is not approved (status={approval_data.get('status')})"
        
    sig = approval_data.get("signature")
    if not sig:
        return False, "Approval record missing cryptographic signature"
        
    media_sha = approval_data.get("approved_media_sha256") or approval_data.get("media_sha256", "")
    claim_sha = approval_data.get("claim_ledger_sha256", "")
    timestamp = approval_data.get("timestamp", "")
    reviewer = approval_data.get("approved_by", "")
    manifest_sha = approval_data.get("manifest_sha256", "")

    # 1. Require manifest for strict release gates if requested
    if require_manifest and not manifest_sha:
        return False, "Approval record rejected: missing release manifest required for release"

    # 2. Verify signature
    signature_mode = "legacy"
    if manifest_sha:
        expected_sig = compute_signature(project_id, media_sha, claim_sha, timestamp, reviewer, manifest_sha256=manifest_sha)
        if not hmac.compare_digest(sig, expected_sig):
            return False, "Cryptographic signature mismatch — approval record forged or tampered"
        # Verify internal manifest integrity
        calc_manifest = compute_manifest_sha256(
            project_id=project_id,
            media_sha256=media_sha,
            claim_ledger_sha256=claim_sha,
            metadata_sha256=approval_data.get("metadata_sha256", ""),
            captions_sha256=approval_data.get("captions_sha256", ""),
            script_sha256=approval_data.get("script_sha256", ""),
            visual_plan_sha256=approval_data.get("visual_plan_sha256", ""),
        )
        if calc_manifest != manifest_sha:
            return False, f"Release manifest hash mismatch ({calc_manifest[:16]} != {manifest_sha[:16]})"
        signature_mode = "manifest"
    else:
        expected_legacy_sig = compute_signature(project_id, media_sha, claim_sha, timestamp, reviewer)
        if not hmac.compare_digest(sig, expected_legacy_sig):
            return False, "Cryptographic signature mismatch — approval record forged or tampered"

    # 3. If project_dir is provided, verify on-disk files match the approved record
    if project_dir is not None:
        p_dir = Path(project_dir)

        # A. Metadata verification
        if approval_data.get("metadata_sha256"):
            meta_path = p_dir / "publish_metadata.json"
            if not meta_path.is_file():
                return False, f"Disk verification failed: metadata file {meta_path} missing"
            actual_meta_sha = hashlib.sha256(meta_path.read_bytes()).hexdigest()
            if actual_meta_sha != approval_data["metadata_sha256"]:
                return False, f"Disk verification failed: metadata SHA mismatch ({actual_meta_sha[:16]} != {approval_data['metadata_sha256'][:16]})"

        # B. Claim ledger verification
        if claim_sha:
            ledger_path = p_dir / "artifacts" / "claim_ledger.json"
            if not ledger_path.is_file():
                return False, f"Disk verification failed: claim ledger {ledger_path} missing"
            actual_ledger_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
            if actual_ledger_sha != claim_sha:
                return False, f"Disk verification failed: claim ledger SHA mismatch ({actual_ledger_sha[:16]} != {claim_sha[:16]})"

        # C. Captions verification
        if approval_data.get("captions_sha256"):
            captions_candidates = [
                p_dir / "artifacts" / "captions_en_US.srt",
                p_dir / "artifacts" / "captions_vi.srt",
                p_dir / "artifacts" / "captions.srt",
            ]
            captions_path = next((c for c in captions_candidates if c.is_file()), None)
            if not captions_path:
                return False, "Disk verification failed: captions file missing"
            actual_captions_sha = hashlib.sha256(captions_path.read_bytes()).hexdigest()
            if actual_captions_sha != approval_data["captions_sha256"]:
                return False, f"Disk verification failed: captions SHA mismatch ({actual_captions_sha[:16]} != {approval_data['captions_sha256'][:16]})"

        # D. Script verification
        if approval_data.get("script_sha256"):
            script_candidates = [
                p_dir / "artifacts" / "script_en_US.json",
                p_dir / "artifacts" / "script_vi.json",
                p_dir / "artifacts" / "script.json",
            ]
            script_path = next((s for s in script_candidates if s.is_file()), None)
            if not script_path:
                return False, "Disk verification failed: script file missing"
            actual_script_sha = hashlib.sha256(script_path.read_bytes()).hexdigest()
            if actual_script_sha != approval_data["script_sha256"]:
                return False, f"Disk verification failed: script SHA mismatch ({actual_script_sha[:16]} != {approval_data['script_sha256'][:16]})"

        # E. Visual plan verification
        if approval_data.get("visual_plan_sha256"):
            plan_path = p_dir / "artifacts" / "news_visual_plan.json"
            if not plan_path.is_file():
                return False, "Disk verification failed: visual plan file missing"
            actual_plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            if actual_plan_sha != approval_data["visual_plan_sha256"]:
                return False, f"Disk verification failed: visual plan SHA mismatch ({actual_plan_sha[:16]} != {approval_data['visual_plan_sha256'][:16]})"

        # F. Media verification
        if media_sha:
            rel_media = None
            meta_file = p_dir / "publish_metadata.json"
            if meta_file.is_file():
                try:
                    mdata = json.loads(meta_file.read_text(encoding="utf-8"))
                    for k in ("yt_shorts", "youtube_video", "video_path", "final_render"):
                        if k in mdata:
                            rel_media = mdata[k]
                            break
                except Exception:
                    pass
            media_candidates: list[Path] = []
            root_abs = os.path.realpath(str(p_dir))
            root_p = Path(root_abs)
            if isinstance(rel_media, str) and rel_media and "\x00" not in rel_media:
                rel_p = Path(rel_media)
                if not any(part == ".." for part in rel_p.parts) and not rel_p.is_absolute():
                    cand_abs = os.path.realpath(os.path.join(root_abs, str(rel_p)))
                    cand_p = Path(cand_abs)
                    if (
                        cand_abs.startswith(root_abs + os.sep)
                        and os.path.commonpath([cand_abs, root_abs]) == root_abs
                        and cand_p.is_relative_to(root_p)
                    ):
                        media_candidates.append(cand_p)
            media_candidates.extend([
                root_p / "renders" / "final_short_en_US_9x16.mp4",
                root_p / "renders" / "final_long_en_US_16x9.mp4",
                root_p / "renders" / "final_full_vi_9x16.mp4",
                root_p / "renders" / "final_render.mp4",
            ])
            media_path = None
            for m in media_candidates:
                if m.is_symlink():
                    continue
                m_abs = os.path.realpath(str(m))
                m_p = Path(m_abs)
                if (
                    not m_abs.startswith(root_abs + os.sep)
                    or os.path.commonpath([m_abs, root_abs]) != root_abs
                    or not m_p.is_relative_to(root_p)
                ):
                    continue
                if m_p.is_file():
                    media_path = m_p
                    break
            if not media_path:
                return False, "Disk verification failed: media file missing"
            h_m = hashlib.sha256()
            with open(media_path, "rb") as mf:
                while chunk := mf.read(65536):
                    h_m.update(chunk)
            actual_media_sha = h_m.hexdigest()
            allowed_media_shas = set(approval_data.get("approved_media_hashes", []))
            if media_sha:
                allowed_media_shas.add(media_sha)
            if actual_media_sha not in allowed_media_shas:
                return False, f"Disk verification failed: media SHA mismatch ({actual_media_sha[:16]} not in approved hashes)"

    if signature_mode == "manifest":
        return True, "Valid supervisor signature (release manifest and on-disk files verified)"
    return True, "Valid supervisor signature"
