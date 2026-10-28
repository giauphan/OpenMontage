"""Deterministic layout generator for 9:16 portrait technical diagrams (1080x1920).

Enforces safe zones to prevent collisions with:
- Top headers / stage badges (y < 0.14)
- Bottom subtitle / caption rail and platform UI (y > 0.72)
- Side margins (x < 0.06 or x > 0.94)

Target module size: < 450 lines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from lib.visual_style.spec import DiagramNode, DiagramEdge, DiagramGraph, NodeKind

VIEWPORT_WIDTH = 1080
VIEWPORT_HEIGHT = 1920

# Safe zone boundaries in normalized coordinates [0, 1]
Y_MIN_SAFE = 0.16
Y_MAX_SAFE = 0.68
X_MIN_SAFE = 0.08
X_MAX_SAFE = 0.92


@dataclass(frozen=True)
class LayoutPresetDefinition:
    """Pre-computed relative node coordinates for standard architectural patterns."""
    name: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


def get_layout_preset(family_or_preset: str) -> str:
    """Map topic family or preset name to canonical layout preset name."""
    mapping = {
        "context_memory": "context_boundary",
        "agent_tool_use": "tool_permission_path",
        "debugging_reliability": "agent_retry_loop",
        "agent_evaluation": "eval_breakdown",
        "agent_architecture": "persistent_agent_flow",
        "agent_harness_mods": "agent_harness_mods",
        "claude_code_mods": "agent_harness_mods",
        "claude_code_mods_harness": "agent_harness_mods",
        "claude_code_mods_lifecycle": "claude_code_mods_lifecycle",
        "claude_code_mods_unlocked": "claude_code_mods_unlocked",
    }
    return mapping.get(family_or_preset, family_or_preset)


def build_preset_graph(preset_name: str, topic_title: str = "") -> DiagramGraph:
    """Generate canonical DiagramGraph for standard Practical AI Agent Engineering topics."""
    canonical_name = get_layout_preset(preset_name)

    if canonical_name == "context_boundary":
        nodes = [
            DiagramNode(id="agent", label="Coding Agent", kind=NodeKind.AGENT, x=0.50, y=0.20, width=0.36, height=0.07),
            DiagramNode(id="context_window", label="Context Window (RAM)", kind=NodeKind.STORE, x=0.26, y=0.36, width=0.36, height=0.07),
            DiagramNode(id="repo_disk", label="Repo Files (Disk)", kind=NodeKind.STORE, x=0.74, y=0.36, width=0.36, height=0.07),
            DiagramNode(id="session_boundary", label="New Session Reset", kind=NodeKind.WARNING, x=0.26, y=0.52, width=0.36, height=0.07),
            DiagramNode(id="durable_instructions", label="AGENTS.md Contract", kind=NodeKind.RESULT, x=0.74, y=0.52, width=0.36, height=0.07),
            DiagramNode(id="verified_memory", label="Persistent Agent Memory", kind=NodeKind.CONCEPT, x=0.50, y=0.64, width=0.44, height=0.07),
        ]
        edges = [
            DiagramEdge(id="e_read_context", source="agent", target="context_window", label="Active Chat"),
            DiagramEdge(id="e_read_repo", source="agent", target="repo_disk", label="File Read"),
            DiagramEdge(id="e_reset_wipe", source="context_window", target="session_boundary", label="Context Evaporates"),
            DiagramEdge(id="e_persist_rule", source="repo_disk", target="durable_instructions", label="Durable State"),
            DiagramEdge(id="e_solution_bridge", source="durable_instructions", target="verified_memory", label="Automated Boot"),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    elif canonical_name == "tool_permission_path":
        nodes = [
            DiagramNode(id="user_prompt", label="User Command", kind=NodeKind.DEVELOPER, x=0.50, y=0.19, width=0.36, height=0.07),
            DiagramNode(id="agent_planner", label="Agent Tool Planner", kind=NodeKind.AGENT, x=0.50, y=0.31, width=0.38, height=0.07),
            DiagramNode(id="mcp_contract", label="MCP Schema & Auth", kind=NodeKind.DECISION, x=0.26, y=0.45, width=0.36, height=0.07),
            DiagramNode(id="sandbox_guard", label="Security Boundary", kind=NodeKind.WARNING, x=0.74, y=0.45, width=0.36, height=0.07),
            DiagramNode(id="tool_execution", label="Sandbox Execution", kind=NodeKind.TOOL, x=0.50, y=0.57, width=0.38, height=0.07),
            DiagramNode(id="structured_result", label="Verified Tool Result", kind=NodeKind.RESULT, x=0.50, y=0.68, width=0.38, height=0.06),
        ]
        edges = [
            DiagramEdge(id="e_plan_tool", source="user_prompt", target="agent_planner", label="Parse Intent"),
            DiagramEdge(id="e_validate_mcp", source="agent_planner", target="mcp_contract", label="Schema Check"),
            DiagramEdge(id="e_enforce_sandbox", source="agent_planner", target="sandbox_guard", label="Scope Policy"),
            DiagramEdge(id="e_execute_call", source="mcp_contract", target="tool_execution", label="Authorized Call"),
            DiagramEdge(id="e_guard_execution", source="sandbox_guard", target="tool_execution", label="Isolation"),
            DiagramEdge(id="e_return_data", source="tool_execution", target="structured_result", label="Typed Return"),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    elif canonical_name == "agent_retry_loop":
        nodes = [
            DiagramNode(id="failing_test", label="Failing Pytest / CI", kind=NodeKind.WARNING, x=0.50, y=0.19, width=0.38, height=0.07),
            DiagramNode(id="agent_debug", label="Diagnostic Reasoning", kind=NodeKind.AGENT, x=0.50, y=0.31, width=0.40, height=0.07),
            DiagramNode(id="hallucinated_patch", label="Surface / Mock Patch", kind=NodeKind.DECISION, x=0.26, y=0.45, width=0.36, height=0.07),
            DiagramNode(id="rootcause_fix", label="Root Cause Solution", kind=NodeKind.CONCEPT, x=0.74, y=0.45, width=0.36, height=0.07),
            DiagramNode(id="full_suite_run", label="Full Regression Run", kind=NodeKind.TOOL, x=0.50, y=0.57, width=0.40, height=0.07),
            DiagramNode(id="verified_green", label="Verified Production Fix", kind=NodeKind.RESULT, x=0.50, y=0.68, width=0.42, height=0.06),
        ]
        edges = [
            DiagramEdge(id="e_read_error", source="failing_test", target="agent_debug", label="Stack Trace"),
            DiagramEdge(id="e_avoid_surface", source="agent_debug", target="hallucinated_patch", label="Shallow Attempt"),
            DiagramEdge(id="e_apply_rootcause", source="agent_debug", target="rootcause_fix", label="Deep Diagnosis"),
            DiagramEdge(id="e_verify_full", source="rootcause_fix", target="full_suite_run", label="Run All Tests"),
            DiagramEdge(id="e_confirm_pass", source="full_suite_run", target="verified_green", label="100% Green"),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    elif canonical_name == "eval_breakdown":
        nodes = [
            DiagramNode(id="task_set", label="Task Set", kind=NodeKind.STORE, x=0.50, y=0.20, width=0.34, height=0.07),
            DiagramNode(id="agent_run", label="Agent Run", kind=NodeKind.AGENT, x=0.50, y=0.33, width=0.34, height=0.07),
            DiagramNode(id="grader", label="Grader", kind=NodeKind.DECISION, x=0.26, y=0.48, width=0.30, height=0.07),
            DiagramNode(id="trace_review", label="Trace Review", kind=NodeKind.TOOL, x=0.74, y=0.48, width=0.30, height=0.07),
            DiagramNode(id="reliability", label="Reliability Score", kind=NodeKind.RESULT, x=0.50, y=0.63, width=0.38, height=0.07),
        ]
        edges = [
            DiagramEdge(id="e_tasks_to_run", source="task_set", target="agent_run", label="Run Cases"),
            DiagramEdge(id="e_run_to_grade", source="agent_run", target="grader", label="Score Output"),
            DiagramEdge(id="e_run_to_trace", source="agent_run", target="trace_review", label="Inspect Trace"),
            DiagramEdge(id="e_grade_to_score", source="grader", target="reliability", label="Aggregate"),
            DiagramEdge(id="e_trace_to_score", source="trace_review", target="reliability", label="Find Failure Modes"),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    elif canonical_name in ("agent_harness_mods", "claude_code_mods", "claude_code_mods_harness"):
        nodes = [
            DiagramNode(id="prompt", label="prompt", kind=NodeKind.DEVELOPER, x=0.50, y=0.18, width=0.32, height=0.055, group_id="internal"),
            DiagramNode(id="model", label="model", kind=NodeKind.AGENT, x=0.50, y=0.27, width=0.32, height=0.055, group_id="internal"),
            DiagramNode(id="mod", label="mod", kind=NodeKind.CONCEPT, x=0.50, y=0.37, width=0.28, height=0.055, group_id="internal"),
            DiagramNode(id="tool_call", label="tool call", kind=NodeKind.TOOL, x=0.50, y=0.47, width=0.32, height=0.055, group_id="internal"),
            DiagramNode(id="screen", label="screen", kind=NodeKind.RESULT, x=0.50, y=0.56, width=0.32, height=0.05, group_id="internal"),
            DiagramNode(id="skills", label="skills", kind=NodeKind.STORE, x=0.22, y=0.68, width=0.24, height=0.05, group_id="external"),
            DiagramNode(id="hooks", label="hooks", kind=NodeKind.WARNING, x=0.50, y=0.68, width=0.24, height=0.05, group_id="external"),
            DiagramNode(id="mcp", label="MCP", kind=NodeKind.DECISION, x=0.78, y=0.68, width=0.24, height=0.05, group_id="external"),
        ]
        edges = [
            DiagramEdge(id="e_p_to_m", source="prompt", target="model", label=""),
            DiagramEdge(id="e_m_to_mod", source="model", target="mod", label=""),
            DiagramEdge(id="e_mod_to_t", source="mod", target="tool_call", label=""),
            DiagramEdge(id="e_t_to_s", source="tool_call", target="screen", label=""),
            DiagramEdge(id="e_tool_skills", source="tool_call", target="skills", label=""),
            DiagramEdge(id="e_tool_hooks", source="tool_call", target="hooks", label=""),
            DiagramEdge(id="e_tool_mcp", source="tool_call", target="mcp", label=""),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    elif canonical_name in ("claude_code_mods_lifecycle", "claude_code_mods_p2"):
        nodes = [
            DiagramNode(id="session", label="session", kind=NodeKind.DEVELOPER, x=0.16, y=0.23, width=0.20, height=0.05),
            DiagramNode(id="hook_label", label="hook", kind=NodeKind.WARNING, x=0.16, y=0.36, width=0.20, height=0.055),
            DiagramNode(id="hook_exec", label="hook.sh (1x)", kind=NodeKind.TOOL, x=0.48, y=0.36, width=0.32, height=0.06),
            DiagramNode(id="mod_label", label="mod", kind=NodeKind.CONCEPT, x=0.16, y=0.50, width=0.20, height=0.055),
            DiagramNode(id="card_remembers", label="remembers", kind=NodeKind.STORE, x=0.23, y=0.66, width=0.24, height=0.09),
            DiagramNode(id="card_live_panel", label="live panel", kind=NodeKind.RESULT, x=0.50, y=0.66, width=0.24, height=0.09),
            DiagramNode(id="card_asks_first", label="asks first", kind=NodeKind.DECISION, x=0.77, y=0.66, width=0.24, height=0.09),
        ]
        edges = [
            DiagramEdge(id="e_hook_trigger", source="session", target="hook_exec", label="event"),
            DiagramEdge(id="e_mod_lifecycle", source="mod_label", target="card_live_panel", label="persistent"),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    elif canonical_name in ("claude_code_mods_unlocked", "claude_code_mods_p3"):
        nodes = [
            DiagramNode(id="prompt", label="prompt", kind=NodeKind.DEVELOPER, x=0.35, y=0.20, width=0.28, height=0.05, group_id="internal"),
            DiagramNode(id="model", label="model", kind=NodeKind.AGENT, x=0.35, y=0.28, width=0.28, height=0.05, group_id="internal"),
            DiagramNode(id="mod", label="mod", kind=NodeKind.CONCEPT, x=0.35, y=0.36, width=0.26, height=0.05, group_id="internal"),
            DiagramNode(id="tool_call", label="tool call", kind=NodeKind.TOOL, x=0.35, y=0.44, width=0.28, height=0.05, group_id="internal"),
            DiagramNode(id="screen", label="screen", kind=NodeKind.RESULT, x=0.35, y=0.52, width=0.28, height=0.05, group_id="internal"),
            DiagramNode(id="pill_memory", label="memory", kind=NodeKind.STORE, x=0.72, y=0.24, width=0.28, height=0.045, group_id="internal"),
            DiagramNode(id="pill_live_panel", label="live panel", kind=NodeKind.RESULT, x=0.72, y=0.31, width=0.28, height=0.045, group_id="internal"),
            DiagramNode(id="pill_asks_first", label="asks first", kind=NodeKind.DECISION, x=0.72, y=0.38, width=0.28, height=0.045, group_id="internal"),
            DiagramNode(id="pill_guard", label="guard", kind=NodeKind.WARNING, x=0.72, y=0.45, width=0.28, height=0.045, group_id="internal"),
            DiagramNode(id="pill_gauge", label="gauge", kind=NodeKind.CONCEPT, x=0.72, y=0.52, width=0.28, height=0.045, group_id="internal"),
            DiagramNode(id="skills", label="skills", kind=NodeKind.STORE, x=0.22, y=0.66, width=0.24, height=0.05, group_id="external"),
            DiagramNode(id="hooks", label="hooks", kind=NodeKind.WARNING, x=0.50, y=0.66, width=0.24, height=0.05, group_id="external"),
            DiagramNode(id="mcp", label="MCP", kind=NodeKind.DECISION, x=0.78, y=0.66, width=0.24, height=0.05, group_id="external"),
        ]
        edges = [
            DiagramEdge(id="e_p_to_m", source="prompt", target="model", label=""),
            DiagramEdge(id="e_m_to_mod", source="model", target="mod", label=""),
            DiagramEdge(id="e_mod_to_t", source="mod", target="tool_call", label=""),
            DiagramEdge(id="e_t_to_s", source="tool_call", target="screen", label=""),
            DiagramEdge(id="e_tool_skills", source="tool_call", target="skills", label=""),
            DiagramEdge(id="e_tool_hooks", source="tool_call", target="hooks", label=""),
            DiagramEdge(id="e_tool_mcp", source="tool_call", target="mcp", label=""),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)

    else:  # default persistent_agent_flow
        nodes = [
            DiagramNode(id="user_task", label="Engineering Task", kind=NodeKind.DEVELOPER, x=0.50, y=0.20, width=0.36, height=0.07),
            DiagramNode(id="agent_core", label="Autonomous Agent", kind=NodeKind.AGENT, x=0.50, y=0.33, width=0.38, height=0.07),
            DiagramNode(id="tool_catalog", label="Discovered Tools", kind=NodeKind.TOOL, x=0.26, y=0.48, width=0.36, height=0.07),
            DiagramNode(id="checkpoint_state", label="State Checkpoints", kind=NodeKind.STORE, x=0.74, y=0.48, width=0.36, height=0.07),
            DiagramNode(id="verification_gate", label="Self-Review / Gate", kind=NodeKind.DECISION, x=0.50, y=0.62, width=0.40, height=0.07),
        ]
        edges = [
            DiagramEdge(id="e_task_to_agent", source="user_task", target="agent_core", label="Prompt & Policy"),
            DiagramEdge(id="e_agent_tools", source="agent_core", target="tool_catalog", label="Execute"),
            DiagramEdge(id="e_agent_checkpoint", source="agent_core", target="checkpoint_state", label="Save Stage"),
            DiagramEdge(id="e_agent_review", source="tool_catalog", target="verification_gate", label="Audit Result"),
        ]
        return DiagramGraph(nodes=nodes, edges=edges)


def node_to_pixels(node: DiagramNode) -> Dict[str, float]:
    """Convert normalized [0, 1] coordinates to exact 1080x1920 pixel coordinates."""
    w_px = node.width * VIEWPORT_WIDTH
    h_px = node.height * VIEWPORT_HEIGHT
    center_x = node.x * VIEWPORT_WIDTH
    center_y = node.y * VIEWPORT_HEIGHT
    left_x = center_x - (w_px / 2.0)
    top_y = center_y - (h_px / 2.0)
    return {
        "x": round(left_x, 2),
        "y": round(top_y, 2),
        "width": round(w_px, 2),
        "height": round(h_px, 2),
        "cx": round(center_x, 2),
        "cy": round(center_y, 2),
    }
