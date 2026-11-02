"""Vector SVG pipeline diagram generator for Practical AI Agent Engineering.

Draws high-contrast, beautiful architectural flowcharts of the AI Agent Execution Pipeline,
directly synchronizing each beat's visual with the spoken narration and topic family.
Features visual vector icons, architectural nodes, glowing signal pulses, and progressive reveals.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from lib.fixed_niche.svg_beats import (
    build_vertical_beat as _build_vertical_beat,
    generate_horizontal_svg as _generate_horizontal_svg,
)
from lib.fixed_niche.svg_configs import FAMILY_CONFIGS, STEP_COUNTS
from lib.fixed_niche.voice_timing_aligner import (
    compute_step_timings_for_beat,
    generate_progressive_svg_style,
)

__all__ = [
    "FAMILY_CONFIGS",
    "STEP_COUNTS",
    "generate_pipeline_svg",
    "_build_vertical_beat",
    "_generate_horizontal_svg",
]


def _resolve_progressive_style(
    progressive: bool,
    step_timings: Optional[List[float]],
    num_steps: int,
    narration: str,
    duration: float,
    word_timestamps: Optional[List[Dict[str, Any]]],
    beat_start_s: float,
    is_final_beat: bool = False,
) -> str:
    """Resolve progressive CSS timing animations for SVG reveals."""
    if not progressive:
        return ""
    if step_timings is None or len(step_timings) != num_steps:
        step_timings = compute_step_timings_for_beat(
            narration=narration,
            duration=duration,
            num_steps=num_steps,
            word_timestamps=word_timestamps,
            beat_start_s=beat_start_s,
            is_final_beat=is_final_beat,
        )
    return generate_progressive_svg_style(step_timings)


def generate_pipeline_svg(
    asset_id: str,
    topic_family: str,
    title: str,
    beat_num: int,
    total_beats: int = 6,
    is_vertical: bool = True,
    step_timings: Optional[List[float]] = None,
    progressive: bool = True,
    duration: float = 11.0,
    narration: str = "",
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    beat_start_s: float = 0.0,
    prefix: str = "",
) -> str:
    """Generate high-contrast, informative vector geometry showing the AI Agent Pipeline flow.

    When `progressive=True`, steps display sequentially in order of the voice narration.
    """
    fam = topic_family.lower().strip()
    cfg = FAMILY_CONFIGS.get(fam, FAMILY_CONFIGS["context_memory"])
    fam_label = (
        fam.replace("_", " ")
        .upper()
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_title = html.escape(title[:60], quote=True)

    w = 980 if is_vertical else 960
    h = 1100 if is_vertical else 540
    vb = f"0 0 {w} {h}"

    num_steps = STEP_COUNTS.get(beat_num, 4)
    is_final_beat = (beat_num == total_beats)
    style_block = _resolve_progressive_style(
        progressive=progressive,
        step_timings=step_timings,
        num_steps=num_steps,
        narration=narration,
        duration=duration,
        word_timestamps=word_timestamps,
        beat_start_s=beat_start_s,
        is_final_beat=is_final_beat,
    )

    if not is_vertical:
        return _generate_horizontal_svg(fam_label, safe_title, beat_num, total_beats, style_block, prefix=prefix)

    import os
    show_stage_num = os.environ.get("OPENMONTAGE_SHOW_STAGE_NUMBER", "0") in ("1", "true", "True")
    stage_text_node = f'\n  <text x="930" y="61" fill="#64748b" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="end">STAGE {beat_num} OF {total_beats}</text>' if show_stage_num else ""
    accent, badge, body = _build_vertical_beat(beat_num, total_beats, fam_label, cfg, prefix=prefix)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w}" height="{h}">
  <defs>
    <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#38bdf8" flood-opacity="0.5"/>
    </filter>
    <filter id="glow-gold" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#fbbf24" flood-opacity="0.5"/>
    </filter>
    <linearGradient id="cta-bg-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e1b4b" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#0f172a" stop-opacity="0.98"/>
    </linearGradient>
    <linearGradient id="star-btn-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="50%" stop-color="#1e293b"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </linearGradient>
{style_block}
  </defs>
  <rect width="{w}" height="{h}" fill="#0b1120"/>
  <rect x="50" y="35" width="380" height="40" rx="10" fill="#1e293b" stroke="{accent}" stroke-width="2"/>
  <text x="240" y="61" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{badge}</text>{stage_text_node}
{body}
  <rect x="50" y="1005" width="880" height="55" rx="10" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="490" y="1038" fill="#e2e8f0" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">Practical AI Agent Engineering — Hermetic Verification Pipeline</text>
</svg>"""
