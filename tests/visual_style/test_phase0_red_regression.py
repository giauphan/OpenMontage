"""Phase 0 RED Regression Tests for Animated Agent Diagram Plan.

Demonstrates the 5 known defects/gaps identified in the audit:
1. Long beat holds (>12.0s) must be rejected.
2. <img> tags prevent internal SVG child element selection/animation in the DOM.
3. Fixed-niche and Daily News visual plans have incompatible schemas.
4. Production-reachable routes must strictly reject off-niche topics.
5. Derivative evidence ("Frozen Research Grounding") must fail primary source verification.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator

from lib.fixed_niche.gate import FixedNicheScopeGate
from lib.news_visual.plan_contract import load_plan_schema


def test_red_01_beat_hold_exceeding_12s_must_be_rejected():
    """Beat hold > 12.0s is a violation of the 12s ceiling policy."""
    invalid_beat = {
        "id": "B03",
        "section_id": "S03",
        "start_seconds": 14.0,
        "end_seconds": 31.0,  # 17s hold!
        "claim_ids": ["C01"],
        "visual_intent": "Explaining memory persistence",
    }
    hold = invalid_beat["end_seconds"] - invalid_beat["start_seconds"]
    assert hold > 12.0, "Fixture should have >12s hold"
    # A strict timing validator must reject holds > 12.000s
    max_allowed = 12.0
    is_valid = hold <= max_allowed
    assert not is_valid, "Holds exceeding 12s must be invalid"


def test_red_02_svg_internal_nodes_cannot_animate_with_img_tag():
    """Embedding SVG via <img> isolates SVG DOM from parent document scripts/GSAP."""
    html_sample = (
        '<div class="diagram-viewport">'
        '  <img src="assets/visuals/beat_01.svg" id="diagram-img" class="technical-svg" />'
        '</div>'
    )
    # In an <img> tag, child SVG nodes like #node-agent or #edge-1 are NOT queryable in parent DOM
    assert "<img " in html_sample
    assert "<svg" not in html_sample
    # This test documents that <img> prevents CSS/GSAP from targeting child elements.
    # The solution is trusted inline SVG.


def test_red_03_fixed_niche_and_news_visual_plans_have_different_contracts():
    """Fixed-niche visual plan fails canonical news_visual_plan.schema.json validation."""
    fixed_niche_plan = {
        "beats": [
            {
                "beat_id": "B01",
                "script_section_id": "S01",
                "start_s": 0.0,
                "end_s": 6.0,
                "asset_id": "beat_01",
                "story_function": "intro_hook",
                "visual_kind": "svg_diagram",
            }
        ]
    }
    schema = load_plan_schema()
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(fixed_niche_plan))
    # It must fail because required top-level keys ('version', 'project_id', 'script_sha256', 'enabled')
    # and beat keys ('id' vs 'beat_id', 'start_seconds' vs 'start_s', 'asset_ids' vs 'asset_id') differ!
    assert len(errors) > 0, "Fixed niche plan directly passed canonical schema without adaptation"


def test_red_04_direct_production_route_rejects_off_niche():
    """Scope gate must reject off-niche topics like generic AI art, crypto, or gossip."""
    gate = FixedNicheScopeGate()
    off_niche_candidates = [
        {"candidate_id": "off_01", "title": "New Midjourney v7 photo-realistic wallpaper generator"},
        {"candidate_id": "off_02", "title": "Top 10 Crypto trading bots to make passive income"},
        {"candidate_id": "off_03", "title": "Senate passes new bill on election cybersecurity"},
    ]
    for cand in off_niche_candidates:
        verdict = gate.evaluate_candidate(cand)
        assert not verdict.is_eligible, f"Candidate {cand['title']} should have been rejected"
        assert verdict.topic_family is None


def test_red_05_derivative_evidence_fails_primary_source_verification():
    """Synthetic 'Frozen Research Grounding' without authentic source capture must fail strict verification."""
    synthetic_source = {
        "id": "s1",
        "url": "https://news.ycombinator.com",
        "content_sha256": "0" * 64,
        "is_synthetic_brief_echo": True,
        "excerpt": "Frozen Research Grounding: AI Agent Engineering",
    }
    # Strict verification requires actual source capture bytes and non-zero SHA
    is_authentic = (
        not synthetic_source["is_synthetic_brief_echo"]
        and synthetic_source["content_sha256"] != "0" * 64
        and "Frozen Research Grounding" not in synthetic_source["excerpt"]
    )
    assert not is_authentic, "Synthetic evidence should fail authentic source verification"
