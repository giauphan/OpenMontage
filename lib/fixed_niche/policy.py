"""Owner-locked niche policy loader, schema validation, and immutability controls."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, List, Optional
import yaml
import jsonschema


class OutcomeStatus(str, Enum):
    """Suggested outcome enums for fixed niche topic pipeline."""
    ELIGIBLE = "ELIGIBLE"
    OFF_NICHE = "OFF_NICHE"
    NO_ELIGIBLE_TOPIC = "NO_ELIGIBLE_TOPIC"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DUPLICATE_ANGLE = "DUPLICATE_ANGLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class PolicyValidationError(ValueError):
    """Raised when the locked niche policy violates schema or security constraints."""
    pass


class PolicyTamperingError(SecurityError if "SecurityError" in dir(__builtins__) else ValueError):
    """Raised when policy hash mismatch or unauthorized modification attempt is detected."""
    pass


@dataclass(frozen=True)
class TopicFamily:
    """An authorized topic family within the locked niche."""
    id: str
    tags: List[str]


@dataclass(frozen=True)
class LockedNichePolicy:
    """Immutable representation of the owner-locked channel niche policy."""
    schema_version: str
    niche_id: str
    status: str
    owner_change_required: bool
    allow_agent_niche_discovery: bool
    allow_agent_niche_switch: bool
    allow_agent_edit_policy: bool
    market: str
    locale: str
    channel_positioning: dict[str, Any]
    allowed_topic_families: List[TopicFamily]
    allowed_formats: List[str]
    blocked_topics: List[str]
    content_rules: dict[str, Any]
    source_policy: dict[str, Any]
    video_contract: dict[str, Any]
    production: dict[str, Any]
    policy_sha256: str
    source_path: str

    def verify_hash(self, expected_sha256: str) -> bool:
        """Verify whether the policy matches the expected SHA256 checksum."""
        return self.policy_sha256.lower() == str(expected_sha256).strip().lower()

    def assert_hash(self, expected_sha256: str) -> None:
        """Raise PolicyTamperingError if policy SHA256 checksum does not match expected."""
        if not self.verify_hash(expected_sha256):
            raise PolicyTamperingError(
                f"Policy tampering detected! Expected SHA256 {expected_sha256}, got {self.policy_sha256}"
            )


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = _REPO_ROOT / "config/niches/us-ai-agent-engineering.locked.yaml"
DEFAULT_SCHEMA_PATH = _REPO_ROOT / "schemas/niches/locked_niche.schema.json"


def load_locked_policy(
    policy_path: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> LockedNichePolicy:
    """Load and validate the locked niche policy.

    Guarantees:
    - Path safety: prohibits directory traversal attacks.
    - Schema validation against draft-2020-12 locked_niche schema.
    - Exact constants: niche_id, status, allow flags must match owner lock.
    - SHA256 checksum computed on exact bytes loaded from disk.
    """
    env_path = os.environ.get("FIXED_NICHE_CONFIG_PATH")
    path = Path(policy_path or (Path(env_path) if env_path else DEFAULT_POLICY_PATH))
    schema_file = Path(schema_path or DEFAULT_SCHEMA_PATH)

    # Security: Path traversal protection
    repo_root = Path(__file__).resolve().parents[2]
    try:
        if any(part == ".." for part in path.parts):
            raise PolicyValidationError(f"Path traversal detected in policy path: {path}")
        resolved_path = path.resolve()
        # Allow paths within repo or test fixtures in temp directory owned by the current user
        is_in_repo = resolved_path.is_relative_to(repo_root)
        tmp_dir = Path(tempfile.gettempdir()).resolve()
        is_in_tmp = (
            resolved_path.is_relative_to(tmp_dir)
            and not path.is_symlink()
            and (
                bool(os.environ.get("PYTEST_CURRENT_TEST"))
                or bool(os.environ.get("OPENMONTAGE_REHEARSAL"))
                or (resolved_path.exists() and resolved_path.stat().st_uid == os.getuid())
            )
        )
        if not (is_in_repo or is_in_tmp):
            raise PolicyValidationError(f"Policy path outside allowed directory: {path}")
    except (ValueError, RuntimeError) as e:
        raise PolicyValidationError(f"Invalid policy path traversal: {e}")

    if not path.is_file():
        raise PolicyValidationError(f"Locked niche policy file not found: {path}")

    raw_bytes = path.read_bytes()
    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()

    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise PolicyValidationError(f"Failed to parse policy YAML: {e}")

    if not isinstance(data, dict):
        raise PolicyValidationError(f"Policy data must be a YAML dictionary, got {type(data).__name__}")

    # Schema validation
    if schema_file.is_file():
        try:
            schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
            jsonschema.validate(instance=data, schema=schema_data)
        except jsonschema.ValidationError as e:
            raise PolicyValidationError(f"Locked policy failed schema validation: {e.message}")
        except Exception as e:
            raise PolicyValidationError(f"Failed to validate schema: {e}")
    else:
        # Fallback inline assertions if schema file not present
        if data.get("niche_id") != "us-ai-agent-engineering":
            raise PolicyValidationError("niche_id must be 'us-ai-agent-engineering'")
        if data.get("status") != "LOCKED_BY_OWNER":
            raise PolicyValidationError("status must be 'LOCKED_BY_OWNER'")

    # Extra immutable assertions
    if data.get("allow_agent_niche_discovery") is not False:
        raise PolicyValidationError("allow_agent_niche_discovery must be false")
    if data.get("allow_agent_niche_switch") is not False:
        raise PolicyValidationError("allow_agent_niche_switch must be false")
    if data.get("allow_agent_edit_policy") is not False:
        raise PolicyValidationError("allow_agent_edit_policy must be false")

    families = [
        TopicFamily(id=f["id"], tags=list(f.get("tags", [])))
        for f in data.get("allowed_topic_families", [])
    ]

    return LockedNichePolicy(
        schema_version=data["schema_version"],
        niche_id=data["niche_id"],
        status=data["status"],
        owner_change_required=bool(data["owner_change_required"]),
        allow_agent_niche_discovery=bool(data["allow_agent_niche_discovery"]),
        allow_agent_niche_switch=bool(data["allow_agent_niche_switch"]),
        allow_agent_edit_policy=bool(data["allow_agent_edit_policy"]),
        market=data["market"],
        locale=data["locale"],
        channel_positioning=dict(data["channel_positioning"]),
        allowed_topic_families=families,
        allowed_formats=list(data.get("allowed_formats", [])),
        blocked_topics=list(data.get("blocked_topics", [])),
        content_rules=dict(data.get("content_rules", {})),
        source_policy=dict(data.get("source_policy", {})),
        video_contract=dict(data.get("video_contract", {})),
        production=dict(data.get("production", {})),
        policy_sha256=sha256_hash,
        source_path=str(path),
    )
