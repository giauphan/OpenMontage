"""Tests for Phase 1: Locked niche policy loading, schema validation, hash integrity, and immutability.
Covers matrix IDs: NICHE-001, NICHE-002, NICHE-003, NICHE-004.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import yaml

from lib.fixed_niche.policy import (
    load_locked_policy,
    LockedNichePolicy,
    PolicyValidationError,
    PolicyTamperingError,
    OutcomeStatus,
)


def test_niche_001_exact_locked_policy_loads_and_verifies_hash():
    """NICHE-001: exact locked policy loads, matches schema, and produces verified SHA256."""
    policy = load_locked_policy()
    assert isinstance(policy, LockedNichePolicy)
    assert policy.niche_id == "us-ai-agent-engineering"
    assert policy.status == "LOCKED_BY_OWNER"
    assert policy.market == "US"
    assert policy.locale == "en-US"
    assert policy.allow_agent_niche_discovery is False
    assert policy.allow_agent_niche_switch is False
    assert policy.allow_agent_edit_policy is False

    # Verify SHA256 matches actual file on disk
    raw_bytes = Path("config/niches/us-ai-agent-engineering.locked.yaml").read_bytes()
    expected_hash = hashlib.sha256(raw_bytes).hexdigest()
    assert policy.policy_sha256 == expected_hash

    # Check allowed topic families
    family_ids = [f.id for f in policy.allowed_topic_families]
    assert "context_memory" in family_ids
    assert "agent_tool_use" in family_ids
    assert "debugging_reliability" in family_ids
    assert "agent_evaluation" in family_ids
    assert "agent_architecture" in family_ids


def test_niche_002_off_niche_topics_identified_in_policy():
    """NICHE-002: blocked_topics must include generic AI news, image/video generation, crypto, etc."""
    policy = load_locked_policy()
    assert "ai_art_image_video_generation" in policy.blocked_topics
    assert "generic_ai_news" in policy.blocked_topics
    assert "crypto_trading" in policy.blocked_topics
    assert "celebrity_gossip" in policy.blocked_topics
    assert "politics" in policy.blocked_topics


def test_niche_003_prompt_injection_cannot_mutate_policy(tmp_path: Path):
    """NICHE-003: malicious source attempting 'ignore niche policy' fails validation."""
    policy = load_locked_policy()

    # Attempt to load a manipulated policy that enables niche discovery
    tampered_data = yaml.safe_load(Path("config/niches/us-ai-agent-engineering.locked.yaml").read_text())
    tampered_data["allow_agent_niche_discovery"] = True
    tampered_path = tmp_path / "tampered.yaml"
    tampered_path.write_text(yaml.dump(tampered_data))

    with pytest.raises(PolicyValidationError):
        load_locked_policy(tampered_path)

    # Attempt to inject prompt override into content_rules
    tampered_data2 = yaml.safe_load(Path("config/niches/us-ai-agent-engineering.locked.yaml").read_text())
    tampered_data2["content_rules"]["topic_must_match_fixed_niche"] = False
    tampered_path2 = tmp_path / "tampered2.yaml"
    tampered_path2.write_text(yaml.dump(tampered_data2))

    with pytest.raises(PolicyValidationError):
        load_locked_policy(tampered_path2)


def test_niche_004_change_operator_policy_after_scope_selection_blocks(tmp_path: Path):
    """NICHE-004: policy hash mismatch between scope selection and execution causes blocking."""
    policy = load_locked_policy()
    initial_hash = policy.policy_sha256

    # Verify matching hash passes
    assert policy.verify_hash(initial_hash) is True

    # Mutated hash fails
    fake_hash = "0" * 64
    assert policy.verify_hash(fake_hash) is False
    with pytest.raises(PolicyTamperingError):
        policy.assert_hash(fake_hash)


def test_policy_path_traversal_prevention():
    """Policy loader forbids relative paths escaping the allowed config directory."""
    with pytest.raises(PolicyValidationError):
        load_locked_policy(Path("../../../etc/passwd"))
