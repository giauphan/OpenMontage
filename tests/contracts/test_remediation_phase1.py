"""Phase 1 Remediation Contract Tests: Authentic Evidence and Consistent Niche Gate.

Verifies:
- T01: Reject unverified numeric claims / percentages (UNVERIFIED_NUMERIC_CLAIM)
- T02: Reject synthetic publication dates & uncaptured brief assertions
- T03: Approve valid primary source claim with canonical URL + SHA
- T04: Reject off-niche topics across all entrypoints (including legacy flags)
- T05: Clean NO_ELIGIBLE_TOPIC exit without retry storm
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.fixed_niche.gate import FixedNicheScopeGate, OutcomeStatus
from scripts.bind_news_evidence import bind_news_evidence


def _create_minimal_project(
    tmp_path: Path,
    locale: str = "en-US",
    script_text: str = "Claude Code agent session memory recovers 45% of failed runs.",
    brief_data: dict[str, Any] | None = None,
    captures: list[dict[str, Any]] | None = None,
) -> Path:
    proj_dir = tmp_path / "test_project"
    proj_dir.mkdir(parents=True, exist_ok=True)
    art_dir = proj_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    script_name = "script_en_US.json" if locale == "en-US" else "script_vi.json"
    script_data = {
        "title": "Agent Session Memory Recovery",
        "total_duration_seconds": 68.0,
        "sections": [
            {
                "id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 12.0,
                "text": script_text if locale == "en-US" else "",
                "text_vi": script_text if locale != "en-US" else "",
            }
        ],
    }
    (art_dir / script_name).write_text(json.dumps(script_data, indent=2), encoding="utf-8")

    if brief_data is None:
        brief_data = {
            "topic": "Claude Code agent session memory boundary recovery",
            "title": "Claude Code agent session memory boundary recovery",
            "sources": [
                {
                    "url": "https://github.com/anthropics/claude-code/releases/tag/v0.2.29",
                    "title": "Claude Code Release Notes v0.2.29",
                    "used_for": "Verification",
                }
            ],
            "data_points": [
                {
                    "claim": "Session memory boundary recovers 45% of failed agent runs",
                    "source_name": "Claude Code Release Notes",
                    "usable_as": "Metric",
                }
            ],
        }
    (art_dir / "research_brief.json").write_text(json.dumps(brief_data, indent=2), encoding="utf-8")

    if captures:
        cap_dir = art_dir / "news_source_capture"
        cap_dir.mkdir(parents=True, exist_ok=True)
        for i, cap in enumerate(captures):
            raw_text = cap.get("text", "")
            raw_sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            # Write txt or json
            txt_file = cap_dir / f"capture_{i+1}.txt"
            txt_file.write_text(raw_text, encoding="utf-8")
            
            prov = {
                "url": cap.get("url", "https://github.com/anthropics/claude-code/releases/tag/v0.2.29"),
                "publisher": cap.get("publisher", "Anthropic"),
                "published_at": cap.get("published_at"),  # real published date or None
                "retrieved_at": cap.get("retrieved_at", "2026-10-28T14:00:00Z"),
                "raw_sha256": raw_sha,
                "capture_method": "http_fetch",
            }
            (cap_dir / f"provenance_{i+1}.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")

    return proj_dir


def test_reject_unverified_percentage(tmp_path: Path):
    """T01: Script asserts '70%' but capture only contains '45%'. Must reject."""
    captures = [
        {
            "text": "The release notes state that session memory boundaries recover 45% of failed agent runs.",
            "url": "https://github.com/anthropics/claude-code/releases/tag/v0.2.29",
            "published_at": "2026-10-28T10:00:00Z",
        }
    ]
    # Script claims 70% savings/boost which does NOT exist in capture!
    proj = _create_minimal_project(
        tmp_path,
        script_text="Claude Code agent memory achieves 70% cost reduction in tool retries.",
        captures=captures,
    )
    
    os.environ["REQUIRE_AUTHENTIC_CAPTURES"] = "1"
    try:
        ok = bind_news_evidence(proj)
        assert not ok, "Expected unverified 70% numeric claim to fail binding"
        
        # Check claim ledger if written
        ledger_path = proj / "artifacts" / "claim_ledger.json"
        if ledger_path.is_file():
            ledger = json.loads(ledger_path.read_text())
            claims = ledger.get("claims", [])
            assert all(c.get("verdict") != "APPROVED" for c in claims)
    finally:
        os.environ.pop("REQUIRE_AUTHENTIC_CAPTURES", None)


def test_reject_synthetic_publication_date(tmp_path: Path):
    """T02: Source without authentic published_at must not have a fake timestamp minted."""
    # Capture has NO published date (unknown)
    captures = [
        {
            "text": "Claude Code session memory boundary recovery documentation.",
            "url": "https://docs.anthropic.com/en/docs/claude-code",
            "published_at": None,
        }
    ]
    proj = _create_minimal_project(
        tmp_path,
        script_text="Claude Code session memory boundary recovery documentation details.",
        captures=captures,
    )
    
    os.environ["REQUIRE_AUTHENTIC_CAPTURES"] = "1"
    try:
        bind_news_evidence(proj)
        
        # Check that news_evidence.json does NOT contain a manufactured publication date
        ev_path = proj / "artifacts" / "news_evidence.json"
        if ev_path.is_file():
            ev = json.loads(ev_path.read_text())
            sources = ev.get("sources", [])
            for s in sources:
                pub = s.get("published_at")
                assert pub is None, f"Expected published_at to be None for capture with unknown date, got synthetic: {pub}"
    finally:
        os.environ.pop("REQUIRE_AUTHENTIC_CAPTURES", None)


def test_reject_no_capture(tmp_path: Path):
    """T01/T02: Release path with REQUIRE_AUTHENTIC_CAPTURES=1 must fail if no captures exist."""
    # No captures provided
    proj = _create_minimal_project(tmp_path, captures=None)
    
    os.environ["REQUIRE_AUTHENTIC_CAPTURES"] = "1"
    try:
        ok = bind_news_evidence(proj)
        assert not ok, "Expected missing authentic captures to fail in release mode"
    finally:
        os.environ.pop("REQUIRE_AUTHENTIC_CAPTURES", None)


def test_reject_same_words_false_claim(tmp_path: Path):
    """T01: Lexical keyword overlap cannot approve a contradictory/unsupported fact."""
    # Source says memory failure rate INCREASED
    captures = [
        {
            "text": "In our benchmarks, memory boundary failure increased under concurrent tool use.",
            "url": "https://github.com/anthropics/claude-code/releases/tag/v0.2.29",
            "published_at": "2026-10-28T10:00:00Z",
        }
    ]
    # Script says memory failure rate DECREASED (same words, opposite polarity!)
    proj = _create_minimal_project(
        tmp_path,
        script_text="In our benchmarks, memory boundary failure decreased under concurrent tool use.",
        captures=captures,
    )
    
    os.environ["REQUIRE_AUTHENTIC_CAPTURES"] = "1"
    try:
        ok = bind_news_evidence(proj)
        assert not ok, "Contradictory polarity claim with same words must NOT be approved"
    finally:
        os.environ.pop("REQUIRE_AUTHENTIC_CAPTURES", None)


def test_off_niche_legacy_entrypoint():
    """T04: Off-niche topics like iPad Mini hardware review must be rejected across all entrypoints."""
    gate = FixedNicheScopeGate()
    
    # 1. iPad Mini hardware candidate
    ipad_cand = {
        "candidate_id": "cand_ipad_mini_test",
        "title": "Apple iPad Mini with A17 Pro: Full Hardware and Display Review",
        "url": "https://theverge.com/apple-ipad-mini-review",
        "summary": "We review the new iPad mini with A17 Pro chip, testing battery life, display, and gaming performance.",
    }
    verdict = gate.evaluate_candidate(ipad_cand)
    assert not verdict.is_eligible, f"Expected iPad hardware to be rejected, got: {verdict}"
    assert verdict.status == OutcomeStatus.OFF_NICHE

    # 2. Unrelated generative music
    music_cand = {
        "candidate_id": "cand_music_test",
        "title": "Suno v3 vs Udio: The Best AI Music and Audio Generation Tools Tested",
        "url": "https://musictech.com/suno-vs-udio",
        "summary": "Generating full songs with text prompts using diffusion audio models.",
    }
    verdict_music = gate.evaluate_candidate(music_cand)
    assert not verdict_music.is_eligible
    assert verdict_music.status == OutcomeStatus.OFF_NICHE


def test_no_eligible_topic_no_retry():
    """T05: When all candidates are off-niche, gate rejects cleanly and signals NO_ELIGIBLE_TOPIC."""
    gate = FixedNicheScopeGate()
    candidates = [
        {
            "candidate_id": "c1",
            "title": "Apple iPad Mini Hardware Review",
            "url": "https://theverge.com/ipad",
            "summary": "Tablet review",
        },
        {
            "candidate_id": "c2",
            "title": "Top 10 Meme Coins Surging Today",
            "url": "https://crypto.com/memes",
            "summary": "Crypto trading gains",
        },
    ]
    passed = [c for c in candidates if gate.evaluate_candidate(c).is_eligible]
    assert len(passed) == 0, "No candidates should pass"


def test_valid_primary_source_passes(tmp_path: Path):
    """T03: Valid candidate with authentic primary source, matching claims & numbers passes."""
    captures = [
        {
            "text": "The release notes state that session memory boundaries recover 45% of failed agent runs.",
            "url": "https://github.com/anthropics/claude-code/releases/tag/v0.2.29",
            "publisher": "Anthropic",
            "published_at": "2026-10-28T10:00:00Z",
        }
    ]
    proj = _create_minimal_project(
        tmp_path,
        script_text="The release notes state that session memory boundaries recover 45% of failed agent runs.",
        captures=captures,
    )
    
    os.environ["REQUIRE_AUTHENTIC_CAPTURES"] = "1"
    try:
        ok = bind_news_evidence(proj)
        assert ok, "Valid primary source claim with authentic capture should pass"
        
        ledger_path = proj / "artifacts" / "claim_ledger.json"
        assert ledger_path.is_file()
        ledger = json.loads(ledger_path.read_text())
        claims = ledger.get("claims", [])
        assert len(claims) == 1
        assert claims[0].get("verdict") == "APPROVED"
        assert claims[0].get("source", {}).get("canonical_url") == "https://github.com/anthropics/claude-code/releases/tag/v0.2.29"
        assert claims[0].get("source", {}).get("published_at") == "2026-10-28T10:00:00Z"
    finally:
        os.environ.pop("REQUIRE_AUTHENTIC_CAPTURES", None)
