"""Tests for chalkboard diagram template generator and layout presets."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.visual_style.layouts import build_preset_graph, get_layout_preset
from scripts.create_diagram_template import (
    BUILTIN_TEMPLATES,
    build_and_render_diagram_template,
)


def test_agent_harness_mods_preset_layout():
    """Verify agent_harness_mods graph topology matches reference explainer."""
    preset = get_layout_preset("claude_code_mods")
    assert preset == "agent_harness_mods"

    graph = build_preset_graph("agent_harness_mods", topic_title="Claude Code Mods")
    node_ids = {node.id for node in graph.nodes}
    assert "prompt" in node_ids
    assert "model" in node_ids
    assert "mod" in node_ids
    assert "tool_call" in node_ids
    assert "screen" in node_ids
    assert "skills" in node_ids
    assert "hooks" in node_ids
    assert "mcp" in node_ids

    mod_node = next(n for n in graph.nodes if n.id == "mod")
    assert mod_node.group_id == "internal"
    skills_node = next(n for n in graph.nodes if n.id == "skills")
    assert skills_node.group_id == "external"

    edge_sources = {e.source for e in graph.edges}
    assert "prompt" in edge_sources
    assert "model" in edge_sources
    assert "mod" in edge_sources
    assert "tool_call" in edge_sources


def test_build_and_stage_claude_code_mods_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify deterministic end-to-end staging of the reference diagram template."""
    monkeypatch.setenv("OPENMONTAGE_VISUAL_STYLE", "animated_agent_diagram_v1")
    monkeypatch.setenv("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "1")
    topic_def = BUILTIN_TEMPLATES["claude_code_mods"]
    proj_dir = tmp_path / "test_template_claude_code_mods"

    res = build_and_render_diagram_template(
        topic_def=topic_def,
        project_dir=proj_dir,
        render_video=False,
    )

    assert res["status"] == "STAGED_READY"
    assert res["template_id"] == "chalkboard_agent_harness_mods"

    plan_file = proj_dir / "artifacts" / "diagram_animation_plan.json"
    assert plan_file.exists()

    with open(plan_file, "r", encoding="utf-8") as f:
        plan = json.load(f)

    assert plan["version"] == "1.0"
    assert plan["style"] == "animated_agent_diagram_v1"
    assert plan["template_id"] == "chalkboard_agent_harness_mods"
    assert len(plan["graph"]["nodes"]) == 8
    assert len(plan["graph"]["edges"]) == 7
    assert len(plan["beats"]) > 0
