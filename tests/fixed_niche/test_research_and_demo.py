"""Tests for Phase 3: Evidence verification, truthful research brief, and demo sandboxing.
Covers matrix IDs: CLAIM-001, CLAIM-002, CLAIM-003.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.research import (
    FixedNicheResearcher,
    ResearchValidationError,
    DemoExecutionProtocol,
    ClaimClassification,
)


def test_claim_001_hallucinated_source_or_fake_competitors_blocked():
    """CLAIM-001: hallucinated source URL or invented 5 competitors -> block, no AI source padding."""
    researcher = FixedNicheResearcher()

    # Case A: Invalid / non-existent URL domain
    invalid_brief = {
        "title": "Why coding agents lose context",
        "canonical_url": "https://non-existent-hallucinated-domain-12345.xyz/doc",
        "claims": [{"claim_id": "C01", "statement": "Context window resets"}],
        "sources": [{"url": "https://non-existent-hallucinated-domain-12345.xyz/doc", "title": "Doc"}],
    }
    with pytest.raises(ResearchValidationError) as exc:
        researcher.validate_research_brief(invalid_brief)
    assert "Disallowed or unsafe source URL" in str(exc.value)

    # Case B: AI source padding with fake competitor items to hit arbitrary schema quotas
    brief_with_fake_competitors = {
        "title": "Why coding agents lose context",
        "canonical_url": "https://docs.anthropic.com/claude/context-window",
        "claims": [{"claim_id": "C01", "statement": "Context window resets"}],
        "sources": [{"url": "https://docs.anthropic.com/claude/context-window", "title": "Doc"}],
        "competitors": [
            {"name": "FakeBot 1", "url": "https://fakebot1.invalid"},
            {"name": "FakeBot 2", "url": "https://fakebot2.invalid"},
            {"name": "FakeBot 3", "url": "https://fakebot3.invalid"},
        ],
    }
    with pytest.raises(ResearchValidationError) as exc:
        researcher.validate_research_brief(brief_with_fake_competitors)
    assert "Invalid or unverified competitor source" in str(exc.value)


def test_claim_002_firsthand_test_claim_requires_actual_demo_results():
    """CLAIM-002: text says 'I tested' but no real demo output -> block claim or downgrade."""
    researcher = FixedNicheResearcher()

    script_with_unverified_test_claim = {
        "sections": [
            {
                "section_id": "S01",
                "narration": "We tested three coding agents in our lab and discovered a critical memory bug.",
                "claims": ["C01"],
            }
        ]
    }
    # No demo results artifact provided!
    is_valid, reason = researcher.verify_script_claims(
        script_with_unverified_test_claim,
        claim_ledger=[{"claim_id": "C01", "classification": "DOCUMENTED"}],
        demo_results=None,
    )
    assert is_valid is False
    assert "asserts first-person testing ('We tested') without verified demo_results" in reason


def test_claim_003_claim_or_source_mutation_invalidates_approval(tmp_path: Path):
    """CLAIM-003: claim or source version changes -> approval invalidated."""
    researcher = FixedNicheResearcher()
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir()

    claim_ledger = {
        "schema_version": "1.0",
        "claims": [{"claim_id": "C01", "statement": "Context lost on session restart"}],
    }
    (artifacts_dir / "claim_ledger.json").write_text(json.dumps(claim_ledger))

    approval = {
        "approved": True,
        "status": "APPROVED",
        "claim_ledger_sha256": researcher.compute_file_sha(artifacts_dir / "claim_ledger.json"),
    }
    (project_dir / "approval.json").write_text(json.dumps(approval))

    # Before mutation: approval is valid
    assert researcher.check_approval_validity(project_dir) is True

    # Mutate claim ledger
    claim_ledger["claims"][0]["statement"] = "Context lost on every single restart without exception"
    (artifacts_dir / "claim_ledger.json").write_text(json.dumps(claim_ledger))

    # After mutation: approval MUST be invalidated!
    assert researcher.check_approval_validity(project_dir) is False


def test_demo_protocol_runs_in_isolated_sandbox_with_audit(tmp_path: Path):
    """Demo protocol executes safely under limits and records environment hash."""
    protocol = DemoExecutionProtocol(working_dir=tmp_path)
    result = protocol.run_isolated_command(
        command="python3 -c 'print(\"exit: 0, verified state\")'",
        timeout_seconds=5,
    )
    assert result["exit_code"] == 0
    assert "verified state" in result["stdout"]
    assert result["env_hash"]
    assert result["timestamp"]
