"""Shared fixtures for contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from tools.tool_registry import ToolRegistry


def sample_artifact(name: str) -> dict:
    """Return a minimal schema-valid artifact for tests."""
    if name == "research_brief":
        return {
            "version": "1.0",
            "topic": "Test Topic",
            "research_date": "2026-03-27",
            "landscape": {
                "existing_content": [
                    {"title": "Existing Video 1", "source": "youtube", "angle": "tutorial", "what_it_covers": "basics"},
                    {"title": "Existing Video 2", "source": "blog", "angle": "deep dive", "what_it_covers": "advanced"},
                    {"title": "Existing Video 3", "source": "youtube", "angle": "comparison", "what_it_covers": "alternatives"},
                ],
                "saturated_angles": ["basic tutorial"],
                "underserved_gaps": ["misconceptions about topic"],
            },
            "data_points": [
                {"claim": "73% of users prefer X", "source_url": "https://example.com/study", "credibility": "primary_source"},
                {"claim": "Market grew 40% in 2025", "source_url": "https://example.com/report", "credibility": "secondary_source"},
                {"claim": "Most experts agree on Y", "source_url": "https://example.com/survey", "credibility": "primary_source"},
            ],
            "audience_insights": {
                "common_questions": ["What is X?", "How does X work?", "Why is X important?"],
                "misconceptions": [{"myth": "X is slow", "reality": "X is fast"}],
                "knowledge_level": "Beginner to intermediate",
            },
            "angles_discovered": [
                {"name": "The Surprising Truth", "hook": "You think X is slow. It's not.", "type": "contrarian", "why_now": "New benchmark data", "grounded_in": ["data_point_1"]},
                {"name": "X From Scratch", "hook": "Build X in 5 minutes.", "type": "evergreen", "why_now": "Audience demand", "grounded_in": ["audience_q1"]},
                {"name": "Why X Matters Now", "hook": "X just changed everything.", "type": "trending", "why_now": "Recent announcement", "grounded_in": ["trending_1"]},
            ],
            "sources": [
                {"url": "https://example.com/study", "title": "Study on X", "used_for": "data_points"},
                {"url": "https://example.com/report", "title": "Market Report", "used_for": "data_points"},
                {"url": "https://example.com/survey", "title": "Expert Survey", "used_for": "data_points"},
                {"url": "https://example.com/reddit", "title": "Reddit Discussion", "used_for": "audience_insights"},
                {"url": "https://example.com/blog", "title": "Tech Blog", "used_for": "landscape"},
            ],
        }
    if name == "proposal_packet":
        return {
            "version": "1.0",
            "concept_options": [
                {
                    "id": "c1", "title": "The Surprising Truth About X", "hook": "You think X is slow.",
                    "narrative_structure": "myth_busting", "visual_approach": "animated diagrams",
                    "target_duration_seconds": 60, "why_this_works": "Strong misconception found in research",
                },
                {
                    "id": "c2", "title": "X From Scratch", "hook": "Build X in 5 minutes.",
                    "narrative_structure": "tutorial", "visual_approach": "code walkthrough",
                    "target_duration_seconds": 90, "why_this_works": "High demand in audience questions",
                },
                {
                    "id": "c3", "title": "Why X Matters Now", "hook": "X just changed everything.",
                    "narrative_structure": "timeline", "visual_approach": "motion graphics",
                    "target_duration_seconds": 75, "why_this_works": "Recent announcement creates timeliness",
                },
            ],
            "selected_concept": {"concept_id": "c1", "rationale": "Strongest research backing"},
            "production_plan": {
                "pipeline": "animated-explainer",
                "render_runtime": "remotion",
                "stages": [
                    {"stage": "script", "tools": [], "approach": "Write from research"},
                    {"stage": "assets", "tools": [{"tool_name": "tts_selector", "role": "narration", "available": True}], "approach": "Generate assets"},
                ],
            },
            "cost_estimate": {
                "total_estimated_usd": 0.52,
                "line_items": [{"tool": "elevenlabs_tts", "operation": "narration", "estimated_usd": 0.18}],
                "budget_verdict": "within_budget",
            },
            "approval": {"status": "approved"},
        }
    if name == "brief":
        return {
            "version": "1.0",
            "title": "Test Brief",
            "hook": "Did you know?",
            "key_points": ["point 1"],
            "tone": "casual",
            "style": "clean-professional",
            "target_platform": "youtube",
            "target_duration_seconds": 60,
        }
    if name == "script":
        return {
            "version": "1.0",
            "title": "Test Script",
            "total_duration_seconds": 60,
            "sections": [
                {
                    "id": "s1",
                    "text": "Hello world",
                    "start_seconds": 0,
                    "end_seconds": 10,
                }
            ],
        }
    if name == "scene_plan":
        return {
            "version": "1.0",
            "scenes": [
                {
                    "id": "scene-1",
                    "type": "talking_head",
                    "description": "Host on camera",
                    "start_seconds": 0,
                    "end_seconds": 10,
                }
            ],
        }
    if name == "asset_manifest":
        return {
            "version": "1.0",
            "assets": [
                {
                    "id": "asset-1",
                    "type": "video",
                    "path": "assets/clip.mp4",
                    "source_tool": "ffmpeg",
                    "scene_id": "scene-1",
                }
            ],
        }
    if name == "edit_decisions":
        return {
            "version": "1.0",
            "cuts": [
                {
                    "id": "cut-1",
                    "source": "asset-1",
                    "in_seconds": 0,
                    "out_seconds": 10,
                }
            ],
        }
    if name == "render_report":
        return {
            "version": "1.0",
            "outputs": [
                {
                    "path": "renders/output.mp4",
                    "format": "mp4",
                    "resolution": "1920x1080",
                    "duration_seconds": 60,
                }
            ],
        }
    if name == "publish_log":
        return {
            "version": "1.0",
            "entries": [
                {
                    "platform": "youtube",
                    "status": "draft",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
    if name == "video_analysis_brief":
        return {
            "version": "1.0",
            "source": {
                "url": "https://example.com/video.mp4",
                "duration_seconds": 45.0,
                "resolution": "1080x1920",
            },
            "pacing": {"cuts_per_minute": 12},
            "structure": {"sections": [{"type": "hook", "duration": 5}]},
            "style": {"energy": "high"},
            "insights": ["Fast hook in first 3 seconds"],
        }
    return {"version": "1.0"}


@pytest.fixture()
def isolated_tool_registry(monkeypatch) -> ToolRegistry:
    """Provide a registry singleton replacement scoped to one test."""
    test_registry = ToolRegistry()
    monkeypatch.setattr("tools.tool_registry.registry", test_registry)
    return test_registry
