"""HyperFrames HTML adapter for Animated Agent Diagram visual style.

Renders trusted inline SVG DOM and deterministic GSAP timeline script into
a valid HyperFrames Core composition HTML file.

Target module size: < 450 lines.
"""
from __future__ import annotations

import html as html_mod
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.visual_style.diagram_director import AnimatedDiagramDirector
from lib.visual_style.gsap_compiler import compile_gsap_timeline_script
from lib.visual_style.layouts import VIEWPORT_WIDTH, VIEWPORT_HEIGHT
from lib.visual_style.spec import DiagramAnimationPlan
from lib.visual_style.svg_renderer import render_inline_svg_dom

logger = logging.getLogger(__name__)

GSAP_CDN_URL = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"


def _fmt_time(t: float) -> str:
    val = round(float(t), 3)
    if val == int(val):
        return str(int(val))
    return f"{val:.3f}".rstrip("0").rstrip(".")


def compose_animated_diagram_html(
    title: str,
    duration: float,
    beats: List[Dict[str, Any]],
    *,
    is_vertical: bool = True,
    audio_src: str = "assets/narration.mp3",
    visuals_src: Optional[Path] = None,
    diagram_plan: Optional[DiagramAnimationPlan] = None,
) -> str:
    """Compose production HyperFrames HTML for animated_agent_diagram_v1 style."""
    width = VIEWPORT_WIDTH if is_vertical else VIEWPORT_HEIGHT
    height = VIEWPORT_HEIGHT if is_vertical else VIEWPORT_WIDTH
    escaped_title = html_mod.escape(title, quote=True)

    # 1. Resolve or generate DiagramAnimationPlan
    if diagram_plan is None:
        director = AnimatedDiagramDirector()
        # Derive topic family and claims from beats or title
        first_beat = beats[0] if beats else {}
        topic_family = str(first_beat.get("topic_family") or "context_memory")
        claims = []
        for b in beats:
            for cid in b.get("claim_ids", []):
                claims.append({"claim_id": cid, "statement": b.get("visual_intent", title)})
        if not claims:
            claims = [{"claim_id": "C001", "statement": title}]

        topic = {
            "title": title,
            "topic_family": topic_family,
            "viewer_question": title,
        }
        diagram_plan = director.plan_diagram_animation(
            project_id="comp",
            topic=topic,
            claims=claims,
            target_duration=duration,
        )

    # 2. Render trusted inline SVG DOM
    svg_markup = render_inline_svg_dom(diagram_plan.graph, title=title)

    # 3. Compile deterministic GSAP script
    gsap_script = compile_gsap_timeline_script(diagram_plan)

    # 4. Build clip sections and overlays for each beat
    sections_html: List[str] = []
    overlay_tweens: List[str] = []

    for i, beat in enumerate(beats):
        bid = str(beat.get("beat_id") or beat.get("id") or f"B{i+1:02d}").lower()
        start_s = float(beat.get("start_s") if beat.get("start_s") is not None else beat.get("start_seconds", 0.0))
        end_s = float(beat.get("end_s") if beat.get("end_s") is not None else beat.get("end_seconds", duration))
        beat_dur = max(0.5, end_s - start_s)
        s_func = str(beat.get("story_function", "scene")).replace("_", " ").upper()
        escaped_s_func = html_mod.escape(s_func, quote=True)
        track_idx = i + 1

        sec_id = f"badge-{bid}"
        sections_html.append(
            f'    <section id="{sec_id}" class="clip scene badge-overlay" '
            f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
            f'      <div class="stage-header stage-header-overlay">\n'
            f'        <span class="stage-badge">Stage {i+1} of {len(beats)} // {escaped_s_func}</span>\n'
            f'      </div>\n'
            f'    </section>'
        )

        entry_t = _fmt_time(max(0.0, start_s))
        overlay_tweens.append(
            f'  tl.fromTo("#{sec_id}", '
            f'{{ opacity: 0, y: -10 }}, '
            f'{{ opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }}, '
            f'{entry_t});'
        )
        if i < len(beats) - 1:
            exit_t = _fmt_time(max(0.0, end_s - 0.2))
            overlay_tweens.append(
                f'  tl.to("#{sec_id}", {{ opacity: 0, duration: 0.2, ease: "power2.in" }}, {exit_t});'
            )

    clips_block = "\n".join(sections_html)
    overlay_script = "\n".join(overlay_tweens)
    starts_js = ", ".join(
        _fmt_time(float(b.get("start_s") if b.get("start_s") is not None else b.get("start_seconds", 0.0)))
        for b in beats
    )

    html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <title>{escaped_title} — Practical AI Agent Engineering</title>
  <!-- Pinned local GSAP with CDN fallback for network-blocked/offline rendering -->
  <script src="assets/vendor/gsap.min.js"></script>
  <script>
    if (typeof gsap === "undefined") {{
      document.write('<script src="{GSAP_CDN_URL}"><\\/script>');
    }}
  </script>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      background: #080b11;
      overflow: hidden;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
    }}
    #root {{
      position: relative;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      margin: 0 auto;
      background: #080b11;
    }}
    .bg-canvas {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      z-index: 1;
    }}
    .clip.badge-overlay {{
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 180px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-start;
      padding-top: 60px;
      z-index: 10;
      pointer-events: none;
    }}
    .stage-header-overlay {{
      text-align: center;
    }}
    .stage-badge {{
      display: inline-block;
      padding: 8px 22px;
      background: rgba(15, 23, 42, 0.90);
      border: 1.5px solid #38bdf8;
      border-radius: 9999px;
      color: #38bdf8;
      font-size: 15px;
      font-weight: 800;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      box-shadow: 0 4px 18px rgba(56, 189, 248, 0.25);
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-width="{width}" data-height="{height}" data-duration="{_fmt_time(duration)}">
    <audio id="narration" class="clip" data-start="0" data-duration="{_fmt_time(duration)}" data-track-index="0" src="{audio_src}"></audio>
    <div class="bg-canvas">
{svg_markup}
    </div>
{clips_block}
  </div>
  <script>
  (function() {{
    const starts = [{starts_js}];
{gsap_script}
{overlay_script}
  }})();
  </script>
</body>
</html>
"""
    return html_content
