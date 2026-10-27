"""Tests for authentic source evidence verification and proof coverage.

Covers AC-002, AC-009, AC-018, AC-023.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from lib.visual_style.proof_binding import (
    verify_authentic_source_bytes,
    verify_proof_coverage,
    build_immutable_proof_bundle,
)


def test_reject_synthetic_brief_echo_source():
    """Source with 'Frozen Research Grounding' must fail authentic source verification."""
    fake_source = {
        "url": "https://news.ycombinator.com/item?id=123",
        "content_sha256": "abcdef" * 10 + "1234",
        "excerpt": "Frozen Research Grounding: Synthetic brief excerpt",
    }
    is_ok, reason = verify_authentic_source_bytes(fake_source)
    assert is_ok is False
    assert "synthetic brief echo" in reason


def test_reject_placeholder_sha_source():
    """Source with placeholder all-zero SHA must fail authentic source verification."""
    placeholder_source = {
        "url": "https://github.com/anthropics/anthropic-tools",
        "content_sha256": "0" * 64,
        "excerpt": "Genuine documentation excerpt",
    }
    is_ok, reason = verify_authentic_source_bytes(placeholder_source)
    assert is_ok is False
    assert "placeholder" in reason


def test_reject_source_missing_captured_content_bytes():
    """Source without captured content bytes must fail closed when allow_unverified_bytes is False."""
    source_no_bytes = {
        "url": "https://github.com/anthropics/anthropic-tools",
        "content_sha256": "a" * 64,
        "excerpt": "Genuine documentation excerpt",
    }
    is_ok, reason = verify_authentic_source_bytes(source_no_bytes)
    assert is_ok is False
    assert "no captured content bytes" in reason.lower()

    # When explicitly opted-in, unverified bytes pass metadata check
    is_ok_opt, reason_opt = verify_authentic_source_bytes(source_no_bytes, allow_unverified_bytes=True)
    assert is_ok_opt is True
    assert "unverified bytes" in reason_opt.lower()


def test_reject_content_path_escaping_project_dir(tmp_path: Path):
    """Content path attempting path traversal outside project directory must be rejected."""
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_bytes(b"forbidden outside bytes")
    source_traversal = {
        "url": "https://example.com/spec",
        "content_sha256": hashlib.sha256(b"forbidden outside bytes").hexdigest(),
        "content_path": "../outside.txt",
        "excerpt": "Traversal attempt",
    }
    is_ok, reason = verify_authentic_source_bytes(source_traversal, project_dir=tmp_path)
    assert is_ok is False
    assert "escapes project directory" in reason


def test_accept_authentic_source_with_verified_bytes(tmp_path: Path):
    """Source with real primary capture bytes and matching SHA passes verification."""
    content_bytes = b"# Anthropic MCP Specification\nMCP defines client-server tool protocols for coding agents."
    expected_sha = hashlib.sha256(content_bytes).hexdigest()
    content_file = tmp_path / "artifacts" / "news_source_capture" / "mcp_spec.txt"
    content_file.parent.mkdir(parents=True)
    content_file.write_bytes(content_bytes)

    valid_source = {
        "url": "https://modelcontextprotocol.io/introduction",
        "content_sha256": expected_sha,
        "content_path": "artifacts/news_source_capture/mcp_spec.txt",
        "excerpt": "MCP defines client-server tool protocols",
    }
    is_ok, reason = verify_authentic_source_bytes(valid_source, project_dir=tmp_path)
    assert is_ok is True
    assert "verified" in reason.lower()


def test_verify_proof_coverage_rejects_unapproved_claim():
    """Claim ID used in beat or event but missing from approved ledger must be flagged."""
    approved_claims = {
        "C001": {"statement": "Context window resets"},
        "C002": {"statement": "Repo instructions persist"},
    }
    plan_beats = [
        {"id": "B01", "claim_ids": ["C001"]},
        {"id": "B02", "claim_ids": ["C999"]},  # unapproved!
    ]
    plan_events = [
        {"id": "ev_01", "claim_ids": ["C001"]},
        {"id": "ev_02", "claim_ids": ["C888"]},  # unapproved!
    ]

    errors = verify_proof_coverage(plan_beats, plan_events, approved_claims)
    assert len(errors) == 2
    assert any("C999" in err for err in errors)
    assert any("C888" in err for err in errors)
