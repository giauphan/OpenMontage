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
    assert "Cinematic conceptual illustration" in prompt
    assert "swarm of autonomous glowing digital AI robotic agents" in prompt
    assert "vertical 9:16" in prompt
    assert "Pure visual imagery" in prompt
    assert "blurry" in neg
    assert "illegible gibberish text" in neg


def test_extract_visual_subject_matches_topic():
    # 1. iPad / tablet topic
    s_ipad = ThumbnailPlanner.extract_visual_subject("iPad mini 8: Apple's Smallest AI Machine #ai #tech")
    assert "Apple iPad mini tablet" in s_ipad or "tablet" in s_ipad

    # 2. Figma / design tool topic
    s_figma = ThumbnailPlanner.extract_visual_subject("desigma: The Rust-Powered Local Alternative to Figma #ai #tech")
    assert "UI/UX design canvas" in s_figma

    # 3. Off-Grid AI / edge compute topic
    s_offgrid = ThumbnailPlanner.extract_visual_subject("The Rise of Off-Grid AI #ai #tech")
    assert "offline edge AI computing hardware" in s_offgrid

    # 4. Web browser topic
    s_opera = ThumbnailPlanner.extract_visual_subject("WebAI by Opera: Running Local LLMs in the Browser #ai #tech")
    assert "web browser interface" in s_opera

    # 5. Voice AI topic
    s_voice = ThumbnailPlanner.extract_visual_subject("TheySaid 4.0 #ai #tech", context_text="emotional voice storytelling")
    assert "soundwave visualizer" in s_voice



def test_plan_thumbnail_shorts():
    plan = ThumbnailPlanner.plan_thumbnail(
        title="DeepSeek R1 Architecture Revolution #ai",
        format_type="short",
    )
    assert isinstance(plan, ThumbnailPlan)
    assert plan.aspect_ratio == "9:16"
    assert plan.target_dimensions == (1080, 1920)
    assert plan.headline_position == "body_center"
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
    assert plan.headline_position == "body_center"
