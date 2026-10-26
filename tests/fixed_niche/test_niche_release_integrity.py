"""Tests for Phase 0: Niche release integrity and genuine evidence source binding.

Reproduces:
(a) Daily cron producer / CLI bypasses niche gate when ingest/produce is called.
(b) Evidence binder self-certifying claims from brief text without authentic captured sources.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from lib.fixed_niche.gate import FixedNicheScopeGate, OutcomeStatus
from scripts.bind_news_evidence import bind_news_evidence


def test_scope_gate_rejects_off_niche_topics():
    """Verify FixedNicheScopeGate rejects off-niche items."""
    gate = FixedNicheScopeGate()
    off_niche = {
        "title": "Crypto trading bot yields 300% passive income on Solana",
        "body": "Buy bitcoin and memecoins with our new trading bot algorithm.",
    }
    verdict = gate.evaluate_candidate(off_niche)
    assert not verdict.is_eligible
    assert verdict.status == OutcomeStatus.OFF_NICHE


def test_bind_news_evidence_requires_authentic_captures_for_en_us(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Evidence binder must refuse to synthesize source_evidence_s*.txt for en-US if no captures exist under strict mode."""
    monkeypatch.setenv("REQUIRE_AUTHENTIC_CAPTURES", "1")
    project_dir = tmp_path / "proj_no_captures"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    # Valid en-US script
    script = {
        "version": "1.0",
        "sections": [
            {
                "id": "sec_0",
                "text": "Context window limits cause coding agents to lose memory between sessions.",
            }
        ],
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script))

    # Brief without any actual capture files in artifacts/news_source_capture/
    brief = {
        "topic": "Why coding agents lose memory",
        "sources": [
            {
                "url": "https://example.com/source",
                "title": "Agent Memory Paper",
                "used_for": "Core claim verification",
            }
        ],
        "data_points": [
            {
                "claim": "Context window limits cause coding agents to lose memory between sessions.",
                "source_name": "Agent Memory Paper",
            }
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief))

    # No artifacts/news_source_capture directory exists!
    success = bind_news_evidence(project_dir)
    assert not success, "bind_news_evidence must fail closed when authentic capture files are absent"


def test_news_pipeline_produce_rejects_off_niche_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Under locked niche or FIXED_NICHE_MODE=1, produce must filter out off-niche candidates."""
    from tools.news.news_pipeline_cli import main
    from datetime import datetime, timezone
    import sys

    raw_items = [
        {
            "id": "cand_crypto_01",
            "title": "Crypto trading bot yields 300% passive income on Solana",
            "url": "https://crypto.example.com/item1",
            "publisher": "CryptoNews",
            "description": "Trading bots for altcoins.",
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": "cand_celeb_02",
            "title": "Celebrity tech billionaire luxury vacation photos",
            "url": "https://gossip.example.com/item2",
            "publisher": "CelebrityGossip",
            "description": "Yachts and parties.",
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    raw_file = tmp_path / "raw.json"
    raw_file.write_text(json.dumps(raw_items))

    monkeypatch.setenv("FIXED_NICHE_MODE", "1")
    monkeypatch.setenv("MIN_PRODUCE_COUNT", "1")

    # When all candidates are off-niche, main(["produce", ...]) must fail closed (exit != 0 or NO_ELIGIBLE_TOPIC)
    with pytest.raises(SystemExit) as exc_info:
        main(["produce", "--input", str(raw_file), "--count", "1", "--dry-run"])

    assert exc_info.value.code != 0, "CLI must reject off-niche candidates when fixed niche mode is active"


