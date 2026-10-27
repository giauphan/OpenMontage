"""Tests for deterministic GSAP compilation and seek safety.

Covers AC-013.
"""
from __future__ import annotations

import re
import pytest

from lib.visual_style.diagram_director import AnimatedDiagramDirector
from lib.visual_style.gsap_compiler import compile_gsap_timeline_script


def test_compiled_gsap_has_no_stateful_callbacks():
    """Compiled GSAP script must contain NO tl.call() callbacks that break on seek()."""
    director = AnimatedDiagramDirector()
    topic = {
        "candidate_id": "test_seek",
        "title": "Why coding agents forget context",
        "topic_family": "context_memory",
    }
    claims = [{"claim_id": "C001", "statement": "Test claim"}]
    plan = director.plan_diagram_animation("test_seek", topic, claims, target_duration=72.0)

    script = compile_gsap_timeline_script(plan)

    # Invariants for seek safety:
    # 1. No tl.call()
    assert "tl.call(" not in script, "tl.call() detected! Callbacks break direct/reverse seek consistency."
    # 2. Timeline must be paused
    assert "paused: true" in script
    # 3. window.__timelines['main'] registration
    assert "window.__timelines['main'] = tl;" in script
    # 4. Total duration set
    assert "tl.totalDuration(72" in script


def test_compiled_gsap_deterministic_event_timestamps():
    """All tweens have monotonic or valid positive timestamps within plan duration."""
    director = AnimatedDiagramDirector()
    topic = {
        "candidate_id": "test_timing",
        "title": "MCP Tool Calling Flow",
        "topic_family": "agent_tool_use",
    }
    claims = [{"claim_id": "C001", "statement": "MCP claim"}]
    plan = director.plan_diagram_animation("test_tool", topic, claims, target_duration=70.0)

    script = compile_gsap_timeline_script(plan)

    # Extract all absolute position arguments from tl.fromTo / tl.to / tl.set
    # Regex looks for trailing , <number>);
    matches = re.findall(r",\s*(\d+(?:\.\d+)?)\s*\);", script)
    assert len(matches) >= len(plan.events)

    for m in matches:
        t = float(m)
        assert 0.0 <= t <= 70.0, f"Timestamp {t} is outside timeline duration"
