"""Proof binding and authentic evidence verification for Animated Agent Diagram.

Enforces:
1. Every claim referenced by beats or events must exist in the approved claim ledger.
2. Source evidence must originate from authentic retrieved source bytes (not synthetic brief echoes).
3. Cryptographic integrity: SHA256 hashes for script, visual plan, claim ledger, and policy.

Target module size: < 450 lines.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ProofVerificationError(ValueError):
    """Raised when an unverified claim, fabricated screenshot, or fake source is detected."""
    pass


def compute_sha256_bytes(content: bytes) -> str:
    """Compute standard hex-encoded SHA-256 digest."""
    return hashlib.sha256(content).hexdigest()


def compute_sha256_file(path: Path) -> str:
    """Compute standard hex-encoded SHA-256 digest of a file."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found for hash calculation: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_authentic_source_bytes(
    source_record: Dict[str, Any],
    project_dir: Optional[Path] = None,
    allow_unverified_bytes: bool = False,
) -> Tuple[bool, str]:
    """Verify that a source evidence entry originates from genuine primary source capture."""
    url = str(source_record.get("url", ""))
    content_sha = str(source_record.get("content_sha256", "")).strip().lower()
    excerpt = str(source_record.get("excerpt", ""))

    if not url.startswith(("http://", "https://")):
        return False, f"Source missing valid HTTP/HTTPS URL: {url}"

    if not re.fullmatch(r"[0-9a-f]{64}", content_sha):
        return False, f"Source has malformed SHA256 hash: {content_sha!r}"

    if content_sha == "0" * 64:
        return False, "Source has placeholder all-zero SHA256 hash"

    # Reject derivative / synthetic brief echoes
    if "Frozen Research Grounding" in excerpt:
        return False, "Source is a synthetic brief echo ('Frozen Research Grounding')"

    if source_record.get("is_synthetic_brief_echo") is True:
        return False, "Source explicitly marked as synthetic brief echo"

    # Verify byte-level SHA matches captured content
    content_path_str = source_record.get("content_path")
    if not content_path_str or project_dir is None:
        if allow_unverified_bytes:
            return True, "Authentic source record metadata valid (unverified bytes)"
        return False, "Source has no captured content bytes to verify"

    root = project_dir.resolve()
    content_path = (root / content_path_str).resolve()
    if not content_path.is_relative_to(root):
        return False, f"Source content path escapes project directory: {content_path_str}"
    if not content_path.is_file():
        return False, f"Source content file does not exist at {content_path}"

    actual_sha = hashlib.sha256(content_path.read_bytes()).hexdigest()
    if actual_sha != content_sha:
        return False, f"Content SHA mismatch for {content_path}: got {actual_sha}, expected {content_sha}"

    return True, "Authentic source verified"


def verify_proof_coverage(
    plan_beats: List[Dict[str, Any]],
    plan_events: List[Dict[str, Any]],
    approved_claims: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Verify that all claims referenced in beats and events exist in approved claim ledger."""
    errors: List[str] = []
    approved_ids: Set[str] = set(approved_claims.keys())

    # Check beats claim IDs
    for b_idx, beat in enumerate(plan_beats):
        cids = beat.get("claim_ids", [])
        for cid in cids:
            if str(cid) not in approved_ids:
                errors.append(f"beats[{b_idx}].claim_ids: claim '{cid}' is not in approved claims ledger")

    # Check events claim IDs
    for e_idx, ev in enumerate(plan_events):
        cids = ev.get("claim_ids", [])
        for cid in cids:
            if str(cid) not in approved_ids:
                errors.append(f"events[{e_idx}].claim_ids: claim '{cid}' is not in approved claims ledger")

    return errors


def build_immutable_proof_bundle(
    project_dir: Path,
    script_path: Path,
    claim_ledger_path: Path,
    policy_path: Path,
) -> Dict[str, str]:
    """Compute and return immutable SHA-256 digests for all governance inputs."""
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing script at {script_path}")
    if not claim_ledger_path.is_file():
        raise FileNotFoundError(f"Missing claim ledger at {claim_ledger_path}")
    if not policy_path.is_file():
        raise FileNotFoundError(f"Missing policy at {policy_path}")

    return {
        "script_sha256": compute_sha256_file(script_path),
        "source_claim_ledger_sha256": compute_sha256_file(claim_ledger_path),
        "policy_sha256": compute_sha256_file(policy_path),
    }
