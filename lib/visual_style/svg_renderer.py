"""Trusted inline SVG DOM generator for Animated Agent Diagram visual style.

Renders an original, clean, mobile-optimized technical flowchart directly into the page DOM:
- 1080x1920 portrait canvas with high-contrast developer theme (#080b11)
- Crisp vector iconography for agent, tools, memory, tests, decisions
- Pre-computed stroke lengths for GSAP stroke-dashoffset draw-on animations
- Escaped XML labels; strictly no scripts or external URLs

Target module size: < 450 lines.
"""
from __future__ import annotations

import html
import math
from typing import Dict, List, Optional, Tuple

from lib.visual_style.layouts import node_to_pixels, VIEWPORT_WIDTH, VIEWPORT_HEIGHT
from lib.visual_style.spec import DiagramGraph, DiagramNode, DiagramEdge, NodeKind
from lib.visual_style.validation import validate_security_string

# Chalkboard palette sampled from the supplied vertical reference.
THEME_BG = "#090A0C"
THEME_CARD_BG = "#101114"
THEME_BORDER = "#55545A"
THEME_TEXT = "#F1EEE8"
THEME_TEXT_MUTED = "#C7C2D5"

KIND_COLORS: Dict[NodeKind, Dict[str, str]] = {
    NodeKind.AGENT: {"stroke": "#F28C7A", "fill": "#151110", "glow": "#F28C7A", "badge": "CORE"},
    NodeKind.TOOL: {"stroke": "#F1EEE8", "fill": "#111214", "glow": "#F1EEE8", "badge": "TOOL"},
    NodeKind.STORE: {"stroke": "#B7A0F5", "fill": "#121116", "glow": "#B7A0F5", "badge": "STORE"},
    NodeKind.DECISION: {"stroke": "#F0D94E", "fill": "#15140E", "glow": "#F0D94E", "badge": "GATE"},
    NodeKind.DEVELOPER: {"stroke": "#F1EEE8", "fill": "#111214", "glow": "#F1EEE8", "badge": "USER"},
    NodeKind.WARNING: {"stroke": "#B7A0F5", "fill": "#121116", "glow": "#B7A0F5", "badge": "NOTE"},
    NodeKind.RESULT: {"stroke": "#46D9D1", "fill": "#0D1515", "glow": "#46D9D1", "badge": "RESULT"},
    NodeKind.CONCEPT: {"stroke": "#46D9D1", "fill": "#0D1515", "glow": "#46D9D1", "badge": "MOD"},
}


def _get_node_glyph(kind: NodeKind) -> str:
    """Return inline SVG vector path icon for each semantic node kind."""
    if kind == NodeKind.AGENT:
        # Microchip / CPU brain icon
        return (
            '<rect x="-10" y="-10" width="20" height="20" rx="3" fill="none" stroke="currentColor" stroke-width="2"/>'
            '<path d="M-6 -10 V-13 M0 -10 V-13 M6 -10 V-13 M-6 10 V13 M0 10 V13 M6 10 V13 '
            'M-10 -6 H-13 M-10 0 H-13 M-10 6 H-13 M10 -6 H13 M10 0 H13 M10 6 H13" stroke="currentColor" stroke-width="2"/>'
        )
    elif kind == NodeKind.TOOL:
        # Terminal / CLI prompt icon
        return (
            '<path d="M-10 -7 L-4 0 L-10 7 M-1 6 H10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>'
        )
    elif kind == NodeKind.STORE:
        # Database cylinder
        return (
            '<path d="M-10 -5 C-10 -8 10 -8 10 -5 C10 -2 -10 -2 -10 -5 Z '
            'M-10 -5 V5 C-10 8 10 8 10 5 V-5 M-10 0 C-10 3 10 3 10 0" fill="none" stroke="currentColor" stroke-width="2"/>'
        )
    elif kind == NodeKind.WARNING:
        # Alert triangle
        return (
            '<path d="M0 -9 L10 8 H-10 Z M0 -3 V1 M0 4.5 V5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
        )
    elif kind == NodeKind.RESULT:
        # Checkmark in circle
        return (
            '<circle cx="0" cy="0" r="9" fill="none" stroke="currentColor" stroke-width="2"/>'
            '<path d="M-4.5 0 L-1.5 3.5 L5 -4" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    elif kind == NodeKind.DECISION:
        # Branch / filter diamond
        return (
            '<path d="M0 -9 L9 0 L0 9 L-9 0 Z M0 -4 V4" fill="none" stroke="currentColor" stroke-width="2"/>'
        )
    elif kind == NodeKind.DEVELOPER:
        # User / avatar silhouette
        return (
            '<circle cx="0" cy="-4" r="5" fill="none" stroke="currentColor" stroke-width="2"/>'
            '<path d="M-9 9 C-9 4 9 4 9 9" fill="none" stroke="currentColor" stroke-width="2"/>'
        )
    else:
        # Network node
        return '<circle cx="0" cy="0" r="6" fill="none" stroke="currentColor" stroke-width="2"/>'


def calculate_edge_geometry(
    src_node: DiagramNode,
    tgt_node: DiagramNode,
) -> Tuple[float, float, float, float, float]:
    """Calculate start/end coordinates avoiding node bounding boxes, and total line length."""
    src_px = node_to_pixels(src_node)
    tgt_px = node_to_pixels(tgt_node)

    dx = tgt_px["cx"] - src_px["cx"]
    dy = tgt_px["cy"] - src_px["cy"]
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return src_px["cx"], src_px["cy"], tgt_px["cx"], tgt_px["cy"], 1.0

    # Normalized direction vector
    ux = dx / dist
    uy = dy / dist

    # Offset by half-width or half-height to start at boundary
    src_pad = min(src_px["width"], src_px["height"]) * 0.45
    tgt_pad = min(tgt_px["width"], tgt_px["height"]) * 0.45

    x1 = src_px["cx"] + (ux * src_pad)
    y1 = src_px["cy"] + (uy * src_pad)
    x2 = tgt_px["cx"] - (ux * tgt_pad)
    y2 = tgt_px["cy"] - (uy * tgt_pad)

    edge_len = math.hypot(x2 - x1, y2 - y1)
    return round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2), round(edge_len, 2)


def render_inline_svg_dom(graph: DiagramGraph, title: str = "") -> str:
    """Render the trusted inline SVG markup directly into the HyperFrames composition."""
    nodes_by_id = {n.id: n for n in graph.nodes}

    # Definitions for gradient backgrounds and arrowhead markers
    defs_snippets: List[str] = [
        '<defs>',
        '  <filter id="node-glow" x="-30%" y="-30%" width="160%" height="160%">',
        '    <feGaussianBlur stdDeviation="6" result="blur" />',
        '    <feComposite in="SourceGraphic" in2="blur" operator="over" />',
        '  </filter>',
        '  <pattern id="diag-grid" width="40" height="40" patternUnits="userSpaceOnUse">',
        '    <circle cx="2" cy="2" r="1.5" fill="#1e293b" opacity="0.6"/>',
        '  </pattern>',
    ]

    # Arrow markers per color
    for kind, colors in KIND_COLORS.items():
        mid = f"arrow-{kind.value}"
        defs_snippets.append(
            f'  <marker id="{mid}" markerWidth="10" markerHeight="10" refX="7" refY="3.5" orient="auto">'
            f'    <polygon points="0 0, 8 3.5, 0 7" fill="{colors["stroke"]}" />'
            f'  </marker>'
        )
    defs_snippets.append('</defs>')

    # Background grid
    bg_snippets = [
        f'<rect width="{VIEWPORT_WIDTH}" height="{VIEWPORT_HEIGHT}" fill="{THEME_BG}" />',
        f'<rect width="{VIEWPORT_WIDTH}" height="{VIEWPORT_HEIGHT}" fill="url(#diag-grid)" />',
    ]

    # Draw persistent chalk enclosures for graph groups before their contents.
    groups: Dict[str, List[DiagramNode]] = {}
    for node in graph.nodes:
        if node.group_id:
            groups.setdefault(node.group_id, []).append(node)
    group_snippets: List[str] = ['<g id="diagram-groups-layer">']
    group_tokens = {
        "internal": ("#F28C7A", "inside the agent"),
        "external": ("#B7A0F5", "outside"),
    }
    for group_id, group_nodes in groups.items():
        color, label = group_tokens.get(group_id, ("#C7C2D5", group_id.replace("_", " ")))
        pixel_nodes = [node_to_pixels(node) for node in group_nodes]
        pad_x = 34
        pad_y = 28
        left = max(48, min(item["x"] for item in pixel_nodes) - pad_x)
        top = min(item["y"] for item in pixel_nodes) - pad_y
        right = min(VIEWPORT_WIDTH - 48, max(item["x"] + item["width"] for item in pixel_nodes) + pad_x)
        bottom = max(item["y"] + item["height"] for item in pixel_nodes) + pad_y
        safe_label = html.escape(label, quote=True)
        group_snippets.append(
            f'<g id="group-{html.escape(group_id, quote=True)}" class="diagram-group">'
            f'<rect x="{left:.1f}" y="{top:.1f}" width="{right-left:.1f}" height="{bottom-top:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" />'
            f'<text x="{left+12:.1f}" y="{top-9:.1f}" font-family="Comic Sans MS, Segoe Print, cursive" '
            f'font-size="25" fill="{color}">{safe_label}</text></g>'
        )
    group_snippets.append('</g>')

    title_text = html.escape((title or "").strip(), quote=True)
    title_markup = ""
    if title_text:
        title_markup = (
            f'<text id="diagram-title" x="{VIEWPORT_WIDTH/2:.0f}" y="132" text-anchor="middle" '
            f'font-family="Comic Sans MS, Segoe Print, cursive" font-size="34" font-weight="600" '
            f'fill="#F28C7A">{title_text}</text>'
        )

    # Render Edges layer (drawn behind nodes)
    edges_snippets: List[str] = ['<g id="diagram-edges-layer">']
    for edge in graph.edges:
        if edge.source not in nodes_by_id or edge.target not in nodes_by_id:
            continue
        src = nodes_by_id[edge.source]
        tgt = nodes_by_id[edge.target]
        x1, y1, x2, y2, edge_len = calculate_edge_geometry(src, tgt)
        colors = KIND_COLORS.get(tgt.kind, KIND_COLORS[NodeKind.CONCEPT])
        marker_id = f"arrow-{tgt.kind.value}"

        if edge.label:
            validate_security_string(edge.label)
        escaped_label = html.escape(edge.label or "", quote=True)
        label_pill = ""
        if edge.label:
            mx = round((x1 + x2) / 2.0, 2)
            my = round((y1 + y2) / 2.0, 2)
            lbl_w = max(80, len(edge.label) * 11 + 20)
            label_pill = (
                f'<g class="edge-label-group" transform="translate({mx}, {my})">'
                f'  <rect x="{-lbl_w/2}" y="-13" width="{lbl_w}" height="26" rx="6" '
                f'fill="{THEME_CARD_BG}" stroke="{THEME_BORDER}" stroke-width="1.5"/>'
                f'  <text text-anchor="middle" y="5" font-family="Inter, system-ui, sans-serif" '
                f'font-size="16" font-weight="600" fill="{THEME_TEXT_MUTED}">{escaped_label}</text>'
                f'</g>'
            )

        edges_snippets.append(
            f'<g id="edge-{edge.id}" class="diagram-edge" data-edge-id="{edge.id}" '
            f'data-length="{edge_len}" opacity="0">\n'
            f'  <path id="edge-path-{edge.id}" class="edge-line" d="M {x1} {y1} L {x2} {y2}" '
            f'stroke="{colors["stroke"]}" stroke-width="3.5" stroke-dasharray="{edge_len}" '
            f'stroke-dashoffset="{edge_len}" marker-end="url(#{marker_id})" />\n'
            f'  {label_pill}\n'
            f'</g>'
        )
    edges_snippets.append('</g>')

    # Render Nodes layer
    nodes_snippets: List[str] = ['<g id="diagram-nodes-layer">']
    for node in graph.nodes:
        px = node_to_pixels(node)
        colors = KIND_COLORS.get(node.kind, KIND_COLORS[NodeKind.CONCEPT])
        escaped_label = html.escape(node.label, quote=True)
        validate_security_string(escaped_label, f"node {node.id}")
        glyph = _get_node_glyph(node.kind)

        half_w = round(px["width"] / 2.0, 2)
        half_h = round(px["height"] / 2.0, 2)
        badge_text = colors["badge"]

        escaped_group = html.escape(node.group_id or "", quote=True)
        nodes_snippets.append(
            f'<g id="node-{node.id}" class="diagram-node node-{node.kind.value}" '
            f'data-node-id="{node.id}" data-group="{escaped_group}" opacity="0" '
            f'transform="translate({px["cx"]}, {px["cy"]}) scale(0.85)">\n'
            f'  <rect class="node-box" x="{-half_w}" y="{-half_h}" width="{px["width"]}" height="{px["height"]}" '
            f'rx="3" fill="{colors["fill"]}" stroke="{colors["stroke"]}" stroke-width="2.5" />\n'
            # Node Kind Chip / Badge at top-left
            f'  <rect display="none" x="{-half_w + 14}" y="{-half_h - 10}" width="68" height="20" rx="4" '
            f'fill="{colors["stroke"]}" />\n'
            f'  <text display="none" x="{-half_w + 48}" y="{-half_h + 4}" text-anchor="middle" font-family="Inter, system-ui, sans-serif" '
            f'font-size="11" font-weight="800" fill="#000000">{badge_text}</text>\n'
            # Icon Glyph
            f'  <g class="node-glyph" display="none" transform="translate({-half_w + 32}, 0)" color="{colors["stroke"]}">\n'
            f'    {glyph}\n'
            f'  </g>\n'
            # Label
            f'  <text class="node-label" text-anchor="middle" x="0" y="8" '
            f'font-family="Comic Sans MS, Segoe Print, cursive" font-size="24" font-weight="500" '
            f'fill="{THEME_TEXT}">{escaped_label}</text>\n'
            f'</g>'
        )
    nodes_snippets.append('</g>')

    svg_content = (
        f'<svg id="technical-diagram-svg" viewBox="0 0 {VIEWPORT_WIDTH} {VIEWPORT_HEIGHT}" '
        f'width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">\n'
        + "\n".join(defs_snippets) + "\n"
        + "\n".join(bg_snippets) + "\n"
        + title_markup + "\n"
        + "\n".join(group_snippets) + "\n"
        + "\n".join(edges_snippets) + "\n"
        + "\n".join(nodes_snippets) + "\n"
        + '</svg>'
    )
    return svg_content
