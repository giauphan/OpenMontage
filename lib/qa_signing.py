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
) -> str:
    """Compute SHA-256 digest over the complete release manifest envelope."""
    manifest_str = (
        f"project:{project_id}|media:{media_sha256}|ledger:{claim_ledger_sha256}|"
        f"meta:{metadata_sha256}|captions:{captions_sha256}|script:{script_sha256}"
    )
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
    timestamp_iso: str,
    reviewer: str = "independent_qa_supervisor",
    metadata_sha256: str = "",
    captions_sha256: str = "",
    script_sha256: str = "",
    format_type: str = "short",
) -> dict:
    """Generate a cryptographically signed approval record bound to release manifest."""
    manifest_sha = compute_manifest_sha256(
        project_id=project_id,
        media_sha256=media_sha256,
        claim_ledger_sha256=claim_ledger_sha256,
        metadata_sha256=metadata_sha256,
        captions_sha256=captions_sha256,
        script_sha256=script_sha256,
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
        },
        "approved_media_sha256": media_sha256,
        "media_sha256": media_sha256,
        "claim_ledger_sha256": claim_ledger_sha256,
        "metadata_sha256": metadata_sha256,
        "captions_sha256": captions_sha256,
        "script_sha256": script_sha256,
        "signature": sig,
        "signature_algorithm": "HMAC-SHA256",
        "approved_media_hashes": [media_sha256],
        "media_sha256_by_platform": {
            "youtube": media_sha256
        },
        "timestamp": timestamp_iso
    }


def verify_approval_record(approval_data: dict, project_id: str) -> tuple[bool, str]:
    """Verify that an approval record was authentically signed and matches attributes."""
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

    # 1. Verify manifest signature if manifest present
    if manifest_sha:
        expected_sig = compute_signature(project_id, media_sha, claim_sha, timestamp, reviewer, manifest_sha256=manifest_sha)
        if hmac.compare_digest(sig, expected_sig):
            # Verify manifest integrity against individual hashes
            calc_manifest = compute_manifest_sha256(
                project_id=project_id,
                media_sha256=media_sha,
                claim_ledger_sha256=claim_sha,
                metadata_sha256=approval_data.get("metadata_sha256", ""),
                captions_sha256=approval_data.get("captions_sha256", ""),
                script_sha256=approval_data.get("script_sha256", ""),
            )
            if calc_manifest != manifest_sha:
                return False, f"Release manifest hash mismatch ({calc_manifest[:16]} != {manifest_sha[:16]})"
            return True, "Valid supervisor signature (release manifest)"

    # 2. Fallback to legacy signature for backward compatibility
    expected_legacy_sig = compute_signature(project_id, media_sha, claim_sha, timestamp, reviewer)
    if hmac.compare_digest(sig, expected_legacy_sig):
        return True, "Valid supervisor signature"
        
    return False, "Cryptographic signature mismatch — approval record forged or tampered"
