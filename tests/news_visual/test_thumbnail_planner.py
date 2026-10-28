"""Unit tests for ThumbnailPlanner domain logic."""

from __future__ import annotations

from lib.news_visual.thumbnail_planner import ThumbnailPlan, ThumbnailPlanner


def test_clean_title_for_headline():
    title = "Anthropic Releases Claude 3.7 Sonnet #ai #tech [Breaking]"
    headline = ThumbnailPlanner.clean_title_for_headline(title, max_words=4)
    assert headline == "ANTHROPIC RELEASES CLAUDE 3.7"
    assert "#ai" not in headline
    assert "[Breaking]" not in headline


def test_clean_title_fallback_when_empty():
    assert ThumbnailPlanner.clean_title_for_headline("") == "HOT UPDATE"
    assert ThumbnailPlanner.clean_title_for_headline("###") == "BREAKING NEWS"


def test_resolve_aspect_ratio():
    ratio_short, dims_short = ThumbnailPlanner.resolve_aspect_ratio("short")
    assert ratio_short == "9:16"
    assert dims_short == (1080, 1920)

    ratio_reels, dims_reels = ThumbnailPlanner.resolve_aspect_ratio("reels")
    assert ratio_reels == "9:16"
    assert dims_reels == (1080, 1920)

    ratio_long, dims_long = ThumbnailPlanner.resolve_aspect_ratio("longform")
    assert ratio_long == "16:9"
    assert dims_long == (1920, 1080)

    ratio_16x9, dims_16x9 = ThumbnailPlanner.resolve_aspect_ratio("16:9")
    assert ratio_16x9 == "16:9"
    assert dims_16x9 == (1920, 1080)


def test_build_muse_thumbnail_prompt():
    prompt, neg = ThumbnailPlanner.build_muse_thumbnail_prompt(
        title="OpenAI Agent Architecture",
        topic="Multi-agent swarm coordination",
        format_type="short",
    )
    assert "YouTube thumbnail" in prompt
    assert "Multi-agent swarm coordination" in prompt
    assert "vertical 9:16" in prompt
    assert "Pure visual illustration" in prompt
    assert "blurry" in neg
    assert "illegible gibberish text" in neg


def test_plan_thumbnail_shorts():
    plan = ThumbnailPlanner.plan_thumbnail(
        title="DeepSeek R1 Architecture Revolution #ai",
        format_type="short",
    )
    assert isinstance(plan, ThumbnailPlan)
    assert plan.aspect_ratio == "9:16"
    assert plan.target_dimensions == (1080, 1920)
    assert plan.headline_position == "upper_third"
    assert "DEEPSEEK" in plan.headline
    assert "9:16" in plan.prompt


def test_plan_thumbnail_longform():
    plan = ThumbnailPlanner.plan_thumbnail(
        title="Building Autonomous AI Coding Agents From Scratch",
        format_type="longform",
        custom_headline="AUTONOMOUS AGENTS",
    )
    assert plan.aspect_ratio == "16:9"
    assert plan.target_dimensions == (1920, 1080)
    assert plan.headline == "AUTONOMOUS AGENTS"
    assert plan.headline_position == "top"
