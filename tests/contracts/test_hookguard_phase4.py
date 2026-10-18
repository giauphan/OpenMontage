"""Tests for HookGuard Phase 4: Script-native hook for newly generated videos."""

from __future__ import annotations

import pytest
from schemas.artifacts import validate_artifact
from tools.analysis.hook_analyzer import HookAnalyzer


def test_brief_schema_supports_optional_hook_intent():
    brief = {
        "version": "1.0",
        "title": "Why Fast Edits Fail",
        "hook": "Ever wonder why some videos instantly feel chaotic?",
        "hook_intent": "topic_question",
        "key_points": ["Fast cutting destroys pacing", "Breath beats matter"],
        "tone": "educational",
        "style": "clean-professional",
        "target_platform": "youtube",
        "target_duration_seconds": 60,
    }
    validate_artifact("brief", brief)


def test_script_schema_supports_optional_hook_intent():
    script = {
        "version": "1.0",
        "title": "Why Fast Edits Fail",
        "total_duration_seconds": 60,
        "hook_intent": "problem_first",
        "sections": [
            {
                "id": "s1",
                "label": "Hook",
                "text": "The one mistake that ruins your video edit is cutting before the idea lands.",
                "start_seconds": 0.0,
                "end_seconds": 4.5,
            },
            {
                "id": "s2",
                "label": "Explanation",
                "text": "When pacing is too fast, viewers swipe away.",
                "start_seconds": 4.5,
                "end_seconds": 12.0,
            },
        ],
    }
    validate_artifact("script", script)


def test_script_native_candidate_generation():
    analyzer = HookAnalyzer()
    res = analyzer.execute({
        "project_id": "native-script-run",
        "policy": {"enabled": True, "mode": "auto"},
        "source": {
            "kind": "brief",
            "brief": {
                "title": "The Science of Sound in Film",
                "topic": "sound design",
                "hook": "Close your eyes and listen to this.",
            },
            "data_points": [
                {
                    "claim": "80% of perceived quality comes from audio clarity",
                    "source_url": "https://example.com/audio-study",
                }
            ],
        },
    })

    assert res.success is True
    plan = res.data["hook_plan"]
    assert plan["status"] in ("SELECTED", "PASS")
    assert len(plan["candidates"]) >= 3

    # All candidates must have explicit intent
    for c in plan["candidates"]:
        assert c["intent"] in [
            "problem_first",
            "solution_first",
            "news_first",
            "topic_question",
            "surprise_fact",
            "visual_payoff",
            "story_tension",
        ]
        assert c["window"]["start_seconds"] == 0.0
