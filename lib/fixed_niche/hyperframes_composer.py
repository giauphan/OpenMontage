"""HyperFrames HTML and GSAP timeline composer for Fixed Niche videos.

Enforces strict compliance with HyperFrames Core composition contracts:
- Explicitly sized #root with data-composition-id="main", data-width, data-height, data-duration
- Full-bleed background child layer
- Top-level audio element for deterministic framework playback
- Distinct clip sections with data-start, data-duration, data-track-index
- Synchronous GSAP timeline registered on window.__timelines["main"]
"""
from __future__ import annotations

import html as html_mod
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional


GSAP_CDN_URL = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"


def _fmt_time(t: float) -> str:
    """Format duration or timestamp cleanly for HyperFrames data attributes."""
    val = round(float(t), 3)
    if val == int(val):
        return str(int(val))
    return f"{val:.3f}".rstrip("0").rstrip(".")


def compose_hyperframes_html(
    title: str,
    duration: float,
    beats: List[Dict[str, Any]],
    *,
    is_vertical: bool = True,
    audio_src: str = "assets/narration.mp3",
) -> str:
    """Compose production HyperFrames HTML composition matching hyperframes-core contract."""
    width = 1080 if is_vertical else 1920
    height = 1920 if is_vertical else 1080
    escaped_title = html_mod.escape(title, quote=True)

    # Build clip sections and GSAP timeline tweens
    sections_html: List[str] = []
    tweens_js: List[str] = []

    for i, beat in enumerate(beats):
        bid = str(beat.get("beat_id", f"B{i+1:02d}")).lower()
        start_s = float(beat.get("start_s", 0.0))
        end_s = float(beat.get("end_s", duration))
        beat_dur = max(0.5, end_s - start_s)
        aid = beat.get("asset_id") or f"beat_{i+1}"
        s_func = str(beat.get("story_function", "scene")).replace("_", " ").upper()
        scr_state = html_mod.escape(str(beat.get("expected_screen_state", s_func)), quote=True)
        track_idx = i + 1

        sec_id = f"scene-{bid}"
        sections_html.append(
            f'    <section id="{sec_id}" class="clip" '
            f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
            f'      <div class="stage-card">\n'
            f'        <div class="stage-header">\n'
            f'          <span class="stage-badge">Stage {i+1} of {len(beats)} // {html_mod.escape(s_func, quote=True)}</span>\n'
            f'        </div>\n'
            f'        <div class="diagram-viewport">\n'
            f'          <img src="assets/visuals/{aid}.svg" alt="{scr_state}" class="technical-svg" />\n'
            f'        </div>\n'
            f'      </div>\n'
            f'    </section>'
        )

        # GSAP animation per beat: smooth fade and subtle rise on entry
        entry_t = _fmt_time(max(0.0, start_s))
        tweens_js.append(
            f'  tl.fromTo("#{sec_id} .stage-card", '
            f'{{ opacity: 0, y: 30, scale: 0.98 }}, '
            f'{{ opacity: 1, y: 0, scale: 1.0, duration: 0.45, ease: "power2.out" }}, '
            f'{entry_t});'
        )
        if i < len(beats) - 1:
            exit_start_t = _fmt_time(max(0.0, end_s - 0.25))
            exit_end_t = _fmt_time(max(0.0, end_s))
            tweens_js.append(
                f'  tl.to("#{sec_id} .stage-card", '
                f'{{ opacity: 0, duration: 0.25, ease: "power2.in" }}, '
                f'{exit_start_t});'
            )
            tweens_js.append(
                f'  tl.set("#{sec_id} .stage-card", {{ opacity: 0 }}, {exit_end_t});'
            )

    clips_block = "\n".join(sections_html)
    tweens_block = "\n".join(tweens_js)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <title>{escaped_title} — Practical AI Agent Engineering</title>
  <script src="{GSAP_CDN_URL}"></script>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      background: #0b1120;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    #root {{
      position: relative;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      margin: 0 auto;
    }}
    .bg-fill {{
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at 50% 25%, #1e293b 0%, #0b1120 85%);
      z-index: 0;
    }}
    .clip {{
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px;
      z-index: 1;
    }}
    .stage-card {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      width: 100%;
      max-width: 980px;
      opacity: 1;
    }}
    .stage-header {{
      margin-bottom: 24px;
      text-align: center;
    }}
    .stage-badge {{
      display: inline-block;
      padding: 8px 20px;
      background: rgba(30, 41, 59, 0.85);
      border: 1.5px solid #38bdf8;
      border-radius: 9999px;
      color: #38bdf8;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      box-shadow: 0 4px 14px rgba(56, 189, 248, 0.2);
    }}
    .diagram-viewport {{
      width: 960px;
      height: 540px;
      border-radius: 16px;
      overflow: hidden;
      border: 1.5px solid #334155;
      background: #0f172a;
      box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.65);
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .technical-svg {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-width="{width}" data-height="{height}" data-duration="{_fmt_time(duration)}">
    <div class="bg-fill"></div>
    <audio id="narration" class="clip" data-start="0" data-duration="{_fmt_time(duration)}" data-track-index="0" src="{audio_src}"></audio>
{clips_block}
  </div>
  <script>
  (function() {{
    window.__timelines = window.__timelines || {{}};
    const tl = gsap.timeline({{ paused: true }});
{tweens_block}
    window.__timelines["main"] = tl;
  }})();
  </script>
</body>
</html>
"""


def materialize_hyperframes_project(
    project_dir: Path,
    topic: Dict[str, Any],
    visual_plan: Dict[str, Any],
    duration: float,
    composition_names: tuple[str, ...] = ("hyperframes", "hyperframes_reels"),
) -> Dict[str, Path]:
    """Materialize HyperFrames composition directories and valid index.html entrypoints."""
    project_dir = Path(project_dir).resolve()
    visuals_src = project_dir / "assets" / "visuals"
    audio_src = project_dir / "assets" / "narration.mp3"
    beats = visual_plan.get("beats", [])
    title = topic.get("title", "Practical AI Agent Engineering")

    result_paths: Dict[str, Path] = {}

    for comp_name in composition_names:
        comp_dir = project_dir / comp_name
        comp_dir.mkdir(parents=True, exist_ok=True)

        # Copy visual SVG assets
        comp_vis = comp_dir / "assets" / "visuals"
        comp_vis.mkdir(parents=True, exist_ok=True)
        if visuals_src.is_dir():
            for svg_file in visuals_src.glob("*.svg"):
                shutil.copy2(svg_file, comp_vis / svg_file.name)

        # Copy or reference narration audio
        comp_assets = comp_dir / "assets"
        comp_assets.mkdir(parents=True, exist_ok=True)
        if audio_src.is_file():
            shutil.copy2(audio_src, comp_assets / "narration.mp3")

        is_vertical = "reels" in comp_name or "short" in comp_name
        html_content = compose_hyperframes_html(
            title=title,
            duration=duration,
            beats=beats,
            is_vertical=is_vertical,
            audio_src="assets/narration.mp3",
        )

        index_file = comp_dir / "index.html"
        index_file.write_text(html_content, encoding="utf-8")
        result_paths[comp_name] = index_file

    return result_paths
