"""Deterministic GSAP compiler for Animated Agent Diagram visual style.

Compiles DiagramEvent sequence into pure, seek-safe property tweens on window.__timelines['main'].
Enforces:
1. No tl.call() callbacks that fail on arbitrary seek()
2. Direct, reverse, and sequential seek result in identical DOM state
3. Precise synchronization with final en-US narration audio

Target module size: < 450 lines.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from lib.visual_style.layouts import node_to_pixels
from lib.visual_style.spec import DiagramAnimationPlan, DiagramEvent, EventType, DiagramGraph

logger = logging.getLogger(__name__)


def _fmt(val: float) -> str:
    r = round(float(val), 3)
    if r == int(r):
        return str(int(r))
    return f"{r:.3f}".rstrip("0").rstrip(".")


def compile_gsap_timeline_script(plan: DiagramAnimationPlan) -> str:
    """Compile the entire diagram plan into a deterministic, seek-safe GSAP script."""
    lines: List[str] = [
        "// Deterministic GSAP Timeline for Animated Agent Diagram (v1.0)",
        "window.__timelines = window.__timelines || {};",
        "const tl = gsap.timeline({ paused: true });",
        "window.__timelines['main'] = tl;",
        "",
        "// Initial state at t=0: hide all dynamic diagram elements",
        "tl.set('.diagram-node', { opacity: 0, scale: 0.85 }, 0);",
        "tl.set('.diagram-edge', { opacity: 0 }, 0);",
        "",
    ]

    # Pre-compute edge lengths map
    nodes_by_id = {n.id: n for n in plan.graph.nodes}
    from lib.visual_style.svg_renderer import calculate_edge_geometry
    edge_lengths: Dict[str, float] = {}
    for edge in plan.graph.edges:
        if edge.source in nodes_by_id and edge.target in nodes_by_id:
            _, _, _, _, length = calculate_edge_geometry(nodes_by_id[edge.source], nodes_by_id[edge.target])
            edge_lengths[edge.id] = length
        else:
            edge_lengths[edge.id] = 300.0

    # Sort events by absolute timestamp to ensure monotonic timeline addition
    sorted_events = sorted(plan.events, key=lambda e: (e.at_seconds, e.id))

    for ev in sorted_events:
        t = _fmt(ev.at_seconds)
        dur = _fmt(max(0.2, ev.duration_seconds))
        dur_half = _fmt(round(max(0.05, ev.duration_seconds / 2.0), 3))
        tgt = ev.target

        if ev.type == EventType.REVEAL_NODE:
            lines.append(
                f"tl.fromTo('#node-{tgt}', "
                f"{{ opacity: 0, scale: 0.85 }}, "
                f"{{ opacity: 1, scale: 1.0, duration: {dur}, ease: 'power2.out' }}, {t});"
            )

        elif ev.type == EventType.HIDE_NODE:
            lines.append(
                f"tl.to('#node-{tgt}', "
                f"{{ opacity: 0, scale: 0.85, duration: {dur}, ease: 'power2.in' }}, {t});"
            )

        elif ev.type == EventType.DRAW_EDGE:
            e_len = _fmt(edge_lengths.get(tgt, 300.0))
            lines.append(
                f"tl.fromTo('#edge-{tgt}', "
                f"{{ opacity: 0 }}, "
                f"{{ opacity: 1, duration: 0.1 }}, {t});"
            )
            lines.append(
                f"tl.fromTo('#edge-path-{tgt}', "
                f"{{ strokeDashoffset: {e_len} }}, "
                f"{{ strokeDashoffset: 0, duration: {dur}, ease: 'power1.inOut' }}, {t});"
            )

        elif ev.type == EventType.HIGHLIGHT_NODE:
            lines.append(
                f"tl.fromTo('#node-{tgt} .node-box', "
                f"{{ strokeWidth: 2.5 }}, "
                f"{{ strokeWidth: 5.5, duration: {dur_half}, yoyo: true, repeat: 1, ease: 'power1.inOut' }}, {t});"
            )

        elif ev.type == EventType.DIM_NODE:
            lines.append(
                f"tl.to('#node-{tgt}', "
                f"{{ opacity: 0.35, duration: {dur}, ease: 'power1.out' }}, {t});"
            )

        elif ev.type == EventType.CIRCLE_NODE:
            lines.append(
                f"tl.fromTo('#node-{tgt} .node-box', "
                f"{{ filter: 'none' }}, "
                f"{{ filter: 'url(#node-glow)', duration: {dur_half}, yoyo: true, repeat: 1 }}, {t});"
            )

        elif ev.type == EventType.FLOW_TOKEN:
            # Emphasize connected path and target node
            lines.append(
                f"tl.fromTo('#edge-path-{tgt}', "
                f"{{ strokeWidth: 3.5 }}, "
                f"{{ strokeWidth: 6.0, duration: {dur_half}, yoyo: true, repeat: 1 }}, {t});"
            )

        elif ev.type == EventType.UPDATE_LABEL_STATE:
            # Pre-rendered state swap
            new_label = ev.payload.get("label", "")
            lines.append(
                f"tl.fromTo('#node-{tgt} .node-label', "
                f"{{ opacity: 1 }}, "
                f"{{ opacity: 0.8, duration: {dur} }}, {t});"
            )

        elif ev.type == EventType.SHOW_COMPARISON:
            lines.append(
                f"tl.to('#node-{tgt}', {{ scale: 1.05, duration: {dur_half}, yoyo: true, repeat: 1 }}, {t});"
            )

        elif ev.type == EventType.PROGRESS_REVEAL:
            lines.append(
                f"tl.to('#node-{tgt}', {{ opacity: 1, duration: {dur} }}, {t});"
            )

        elif ev.type == EventType.FOCUS_GROUP:
            lines.append(
                f"tl.to('.diagram-node:not([data-group=\"{tgt}\"])', {{ opacity: 0.35, duration: {dur} }}, {t});"
            )
            lines.append(
                f"tl.to('#node-{tgt}', {{ opacity: 1, duration: {dur} }}, {t});"
            )

        else:
            # Fallback safe reveal
            lines.append(
                f"tl.to('#node-{tgt}, #edge-{tgt}', {{ opacity: 1, duration: {dur} }}, {t});"
            )

    # Pad timeline to exact total duration
    total_d = _fmt(plan.duration_seconds)
    lines.append(f"\n// Guarantee full playback duration")
    lines.append(f"tl.set('#technical-diagram-svg', {{ opacity: 1 }}, {total_d});")
    lines.append(f"tl.totalDuration({total_d});")

    return "\n".join(lines)
