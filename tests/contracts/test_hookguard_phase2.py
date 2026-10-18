"""Tests for HookGuard Phase 2: HookAnalyzer, Grounded Writing, and Factuality Checks."""

from __future__ import annotations

import pytest

from tools.analysis.hook_analyzer import HookAnalyzer
from tools.analysis.hook_guard import HookGuard
from tools.tool_registry import ToolRegistry
from lib.hook_guard.config import HookPolicy
from lib.hook_guard.grounding import verify_hook_grounding
from lib.hook_guard.ranking import rank_candidates, score_candidate


def test_hook_analyzer_discovery():
    registry = ToolRegistry()
    registry.discover()
    analyzer = registry.get("hook_analyzer")
    assert analyzer is not None
    assert analyzer.name == "hook_analyzer"
    assert analyzer.tier.value == "core"


def test_hook_analyzer_generates_grounded_candidates():
    analyzer = HookAnalyzer()
    inputs = {
        "project_id": "proj-explainer",
        "platform": "youtube_shorts",
        "target_runtime": "remotion",
        "policy": {"enabled": True, "mode": "auto"},
        "source": {
            "kind": "script",
            "source_video_id": "video-1",
            "baseline_body_edl_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "transcript_text": "One major mistake beginners make is cutting clips too quickly, which ruins video pacing.",
            "brief": {"topic": "video editing pacing", "title": "Mastering Cut Pacing"},
            "data_points": [
                {
                    "claim": "73% of viewers swipe away when video pacing is uneven",
                    "source_url": "https://example.com/pacing-study",
                }
            ],
            "external_news": [
                {
                    "claim": "Major Editing Software Updates Auto-Pacing Feature",
                    "source_url": "https://news.example.com/editor-update",
                    "publication_date": "2026-10-15",
                    "event_date": "2026-10-15",
                }
            ],
        },
    }

    res = analyzer.execute(inputs)
    assert res.success is True
    plan = res.data["hook_plan"]
    assert plan["version"] == "1.0"
    assert plan["status"] in ("SELECTED", "PASS")
    assert len(plan["candidates"]) >= 3

    # Check intents generated
    intents = {c["intent"] for c in plan["candidates"]}
    assert "topic_question" in intents
    assert "problem_first" in intents
    assert "solution_first" in intents
    assert "surprise_fact" in intents
    assert "news_first" in intents

    # Selected candidate must trace to evidence
    sel_id = plan["selected_candidate_id"]
    assert sel_id is not None
    selected_cand = next(c for c in plan["candidates"] if c["id"] == sel_id)
    assert len(selected_cand["evidence"]) > 0
    assert selected_cand["score"] > 0.0


def test_hook_analyzer_off_mode_skips():
    analyzer = HookAnalyzer()
    inputs = {
        "project_id": "proj-off",
        "policy": {"enabled": False, "mode": "off"},
        "source": {
            "kind": "existing_video",
            "source_video_id": "v1",
        },
    }
    res = analyzer.execute(inputs)
    assert res.success is True
    plan = res.data["hook_plan"]
    assert plan["status"] == "SKIPPED"
    assert plan["selected_candidate_id"] is None
    assert "SKIPPED_POLICY_OFF" in plan["guard_result"]["reason_codes"]


# --- Grounding and Factuality Tests ---

def test_grounding_rejects_numerical_mismatch():
    candidate = {
        "text": "Over 95% of editors make this mistake",
        "evidence": [
            {
                "kind": "transcript",
                "claim": "Around 73% of editors struggle with audio levels",
            }
        ],
    }
    is_grounded, reason, diag = verify_hook_grounding(candidate)
    assert is_grounded is False
    assert reason == "REJECTED_NUMERICAL_MISMATCH"
    assert "95%" in diag["error"]


def test_grounding_accepts_accurate_numbers():
    candidate = {
        "text": "73% of editors make this mistake",
        "evidence": [
            {
                "kind": "transcript",
                "claim": "73% of editors make this common mistake in their workflow",
            }
        ],
    }
    is_grounded, reason, _ = verify_hook_grounding(candidate)
    assert is_grounded is True
    assert reason is None


def test_grounding_rejects_unsupported_date():
    candidate = {
        "text": "In 2030, video editing will be completely autonomous",
        "evidence": [
            {
                "kind": "script",
                "claim": "Recent industry benchmarks from 2025 show strong adoption",
            }
        ],
    }
    is_grounded, reason, diag = verify_hook_grounding(candidate)
    assert is_grounded is False
    assert reason == "REJECTED_DATE_MISMATCH"
    assert "2030" in diag["error"]


def test_grounding_rejects_unsupported_absolute_negation():
    candidate = {
        "text": "Why this technique never works for anyone",
        "evidence": [
            {
                "kind": "transcript",
                "claim": "This technique requires practice and may sometimes fail without proper setup",
            }
        ],
    }
    is_grounded, reason, diag = verify_hook_grounding(candidate)
    assert is_grounded is False
    assert reason == "REJECTED_NEGATION_MISMATCH"


def test_grounding_rejects_unverified_news():
    candidate = {
        "intent": "news_first",
        "text": "Breaking news: New studio acquisition announced today",
        "evidence": [
            {
                "kind": "script",
                "claim": "I heard rumors that a studio was acquired",
                # missing source_url and publication_date
            }
        ],
    }
    is_grounded, reason, diag = verify_hook_grounding(candidate)
    assert is_grounded is False
    assert reason == "REJECTED_UNVERIFIED_NEWS"


def test_grounding_accepts_verified_news():
    candidate = {
        "intent": "news_first",
        "text": "Breaking news: OpenAI announces GPT-5 release details",
        "evidence": [
            {
                "kind": "external_source",
                "claim": "OpenAI announces GPT-5 release details",
                "source_url": "https://openai.com/blog/gpt-5-announcement",
                "publication_date": "2026-10-18",
                "event_date": "2026-10-18",
            }
        ],
    }
    is_grounded, reason, _ = verify_hook_grounding(candidate)
    assert is_grounded is True
    assert reason is None


# --- Ranking Tests ---

def test_ranking_penalizes_repetition_and_occlusion():
    cand_high = {
        "id": "c1",
        "rank_features": {
            "relevance": 0.9,
            "coherence": 0.9,
            "viewer_promise": 0.9,
            "continuity_penalty": 0.0,
            "repetition_penalty": 0.0,
            "occlusion_risk": 0.0,
        },
    }
    cand_penalized = {
        "id": "c2",
        "rank_features": {
            "relevance": 0.9,
            "coherence": 0.9,
            "viewer_promise": 0.9,
            "continuity_penalty": 0.8,
            "repetition_penalty": 0.8,
            "occlusion_risk": 0.7,
        },
    }

    score_high = score_candidate(cand_high)
    score_pen = score_candidate(cand_penalized)
    assert score_high > score_pen

    ranked = rank_candidates([cand_penalized, cand_high])
    assert ranked[0]["id"] == "c1"
    assert ranked[1]["id"] == "c2"
