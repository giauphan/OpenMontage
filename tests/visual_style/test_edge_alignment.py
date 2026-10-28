"""Tests for arrow and line alignment, exact box-boundary routing, and SVG markers.

Ensures no arrows or lines penetrate inside node bounding boxes or hide behind card fills.
"""
from __future__ import annotations

import math
from typing import Dict

import pytest

from lib.visual_style.layouts import (
    build_preset_graph,
    node_to_pixels,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
)
from lib.visual_style.spec import DiagramNode, NodeKind
from lib.visual_style.svg_renderer import (
    build_edge_path_d,
    calculate_edge_geometry,
    get_target_port_offset,
    cubic_bezier_length,
    intersect_box,
    render_inline_svg_dom,
)


def test_intersect_box_cardinal_directions():
    """Verify intersect_box lands exactly on rectangle boundaries."""
    cx, cy, w, h = 500.0, 500.0, 200.0, 100.0
    # North (up): should hit top edge at y = 450
    ix, iy = intersect_box(cx, cy, w, h, 500.0, 100.0)
    assert ix == 500.0
    assert iy == 450.0

    # South (down): should hit bottom edge at y = 550
    ix, iy = intersect_box(cx, cy, w, h, 500.0, 900.0)
    assert ix == 500.0
    assert iy == 550.0

    # East (right): should hit right edge at x = 600
    ix, iy = intersect_box(cx, cy, w, h, 900.0, 500.0)
    assert ix == 600.0
    assert iy == 500.0

    # West (left): should hit left edge at x = 400
    ix, iy = intersect_box(cx, cy, w, h, 100.0, 500.0)
    assert ix == 400.0
    assert iy == 500.0


def test_intersect_box_diagonal_aspect_ratio():
    """Verify rectangular aspect ratio correctly identifies top/bottom vs side crossings."""
    cx, cy, w, h = 540.0, 600.0, 400.0, 100.0
    # Ray to (280, 864): dx = -260, dy = +264
    # half_w = 200, half_h = 50
    # scale_x = 200/260 = 0.769, scale_y = 50/264 = 0.189
    # scale_y < scale_x -> exits bottom edge
    ix, iy = intersect_box(cx, cy, w, h, 280.0, 864.0)
    assert iy == 650.0  # Exactly bottom edge (600 + 50)
    assert 300.0 < ix < 540.0


def test_cubic_bezier_arc_length():
    """Verify cubic bezier length accurately measures arc length."""
    # Straight horizontal segment: length must equal Euclidean distance
    straight_len = cubic_bezier_length(0, 0, 100, 0, 200, 0, 300, 0)
    assert pytest.approx(straight_len, rel=1e-3) == 300.0

    # Curved S-bend: arc length must be strictly greater than Euclidean distance
    curved_len = cubic_bezier_length(0, 0, 0, 50, 100, 50, 100, 100)
    euclidean = math.hypot(100, 100)
    assert curved_len > euclidean


def test_calculate_edge_geometry_endpoints_outside_boxes():
    """Verify start and end coordinates stay strictly in canvas space outside node boxes."""
    graph = build_preset_graph("tool_permission_path")
    nodes_by_id: Dict[str, DiagramNode] = {n.id: n for n in graph.nodes}

    for edge in graph.edges:
        src = nodes_by_id[edge.source]
        tgt = nodes_by_id[edge.target]
        src_px = node_to_pixels(src)
        tgt_px = node_to_pixels(tgt)

        x1, y1, x2, y2, length = calculate_edge_geometry(src, tgt)
        assert length > 0

        # Verify y1 is strictly below or on bottom boundary of source box
        src_bottom = src_px["y"] + src_px["height"]
        assert y1 >= src_bottom

        # Verify y2 is strictly above or on top boundary of target box (never inside)
        tgt_top = tgt_px["y"]
        assert y2 <= tgt_top

        # Path string check
        path_d = build_edge_path_d(x1, y1, x2, y2)
        assert path_d.startswith("M ")


def test_render_inline_svg_dom_markers_and_orthogonal_curves():
    """Verify rendered SVG contains userSpaceOnUse markers, refX=14, and orthogonal Q curves."""
    graph = build_preset_graph("tool_permission_path")
    rendered_svg = render_inline_svg_dom(graph, title="Tool Permission Flow")

    # Sleek markers in absolute userSpaceOnUse coordinates
    assert 'markerUnits="userSpaceOnUse"' in rendered_svg
    assert 'refX="14"' in rendered_svg
    assert 'refY="8"' in rendered_svg
    assert 'orient="auto"' in rendered_svg
    assert 'fill="none"' in rendered_svg

    # Must contain straight lines ('L ') and rounded orthogonal corners ('Q ')
    assert " L " in rendered_svg
    assert " Q " in rendered_svg

    # All edge paths must have positive non-zero strokeDasharray
    assert 'stroke-dasharray="0.0"' not in rendered_svg


def test_target_port_offsets_and_orthogonal_geometry():
    """Verify single-input targets land at card center while dual-input targets land at offset ports."""
    graph = build_preset_graph("tool_permission_path")
    nodes_by_id = {n.id: n for n in graph.nodes}

    # e_plan_tool (user_prompt -> agent_planner): single input, should have offset 0.0
    e_plan = next(e for e in graph.edges if e.id == "e_plan_tool")
    assert get_target_port_offset(e_plan, graph) == 0.0

    # e_validate_mcp (agent_planner -> mcp_contract): single input, should have offset 0.0
    e_mcp = next(e for e in graph.edges if e.id == "e_validate_mcp")
    assert get_target_port_offset(e_mcp, graph) == 0.0

    # e_execute_call & e_guard_execution converge on tool_execution
    e_call = next(e for e in graph.edges if e.id == "e_execute_call")
    e_guard = next(e for e in graph.edges if e.id == "e_guard_execution")
    assert get_target_port_offset(e_call, graph) == -65.0
    assert get_target_port_offset(e_guard, graph) == 65.0

    # Test orthogonal path analytical length calculation
    x1, y1, x2, y2, length = calculate_edge_geometry(
        nodes_by_id[e_mcp.source],
        nodes_by_id[e_mcp.target],
        target_offset_x=0.0,
    )
    r = min(16.0, abs(y2 - y1) * 0.45, abs(x2 - x1) * 0.45)
    expected_length = round((y2 - y1) + abs(x2 - x1) + (math.pi - 4.0) * r, 2)
    assert length == expected_length

    # Verify generated path d string
    path_d = build_edge_path_d(x1, y1, x2, y2)
    assert " Q " in path_d
    assert path_d.endswith(f"L {x2} {y2}")
