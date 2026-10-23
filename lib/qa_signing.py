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


def compute_signature(project_id: str, media_sha256: str, claim_ledger_sha256: str, timestamp_iso: str, reviewer: str) -> str:
    """Compute HMAC-SHA256 signature over critical verification attributes."""
    secret = get_supervisor_secret()
    payload = f"{project_id}:{media_sha256}:{claim_ledger_sha256}:{timestamp_iso}:{reviewer}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def sign_approval_record(
    project_id: str,
    media_sha256: str,
    claim_ledger_sha256: str,
    timestamp_iso: str,
    reviewer: str = "independent_qa_supervisor"
) -> dict:
    """Generate a cryptographically signed approval record."""
    sig = compute_signature(project_id, media_sha256, claim_ledger_sha256, timestamp_iso, reviewer)
    return {
        "approved": True,
        "status": "approved",
        "approved_by": reviewer,
        "reviewer_id": "qa-supervisor-us-migration",
        "approved_media_sha256": media_sha256,
        "media_sha256": media_sha256,
        "claim_ledger_sha256": claim_ledger_sha256,
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
    
    expected_sig = compute_signature(project_id, media_sha, claim_sha, timestamp, reviewer)
    if not hmac.compare_digest(sig, expected_sig):
        return False, "Cryptographic signature mismatch — approval record forged or tampered"
        
    return True, "Valid supervisor signature"
