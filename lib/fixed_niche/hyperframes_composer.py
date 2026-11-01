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
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from lib.fixed_niche.ffmpeg_composer import render_ffmpeg_composition

logger = logging.getLogger(__name__)


GSAP_CDN_URL = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"

EXT_WEBP = ".webp"
EXT_JPEG = ".jpeg"
EXT_JPG = ".jpg"
EXT_PNG = ".png"
EXT_SVG = ".svg"
AI_PREFERRED_EXTS = (EXT_WEBP, EXT_PNG, EXT_JPG, EXT_JPEG, EXT_SVG)
SVG_PREFERRED_EXTS = (EXT_SVG, EXT_WEBP, EXT_PNG, EXT_JPG, EXT_JPEG)
RASTER_EXTENSIONS = (EXT_WEBP, EXT_PNG, EXT_JPG, EXT_JPEG)
ALL_SUPPORTED_MEDIA_EXTS = (EXT_SVG, EXT_PNG, EXT_JPG, EXT_JPEG, EXT_WEBP, ".mp4", ".webm")
NARRATION_MP3_FILENAME = "narration.mp3"
DEFAULT_AUDIO_SRC = f"assets/{NARRATION_MP3_FILENAME}"


def _fmt_time(t: float) -> str:
    """Format duration or timestamp cleanly for HyperFrames data attributes."""
    val = round(float(t), 3)
    if val == int(val):
        return str(int(val))
    return f"{val:.3f}".rstrip("0").rstrip(".")


def _extract_formatted_date(
    topic: Optional[Dict[str, Any]] = None,
    project_dir: Optional[Path] = None,
) -> str:
    """Extract and format publication/coverage date (e.g. 'Nov 1, 2026') from topic or artifacts."""
    date_str = ""
    if topic:
        date_str = (
            topic.get("research_date")
            or topic.get("published_at")
            or topic.get("created_at")
            or topic.get("date")
            or ""
        )
    if not date_str and project_dir:
        rb_file = project_dir / "artifacts" / "research_brief.json"
        if rb_file.is_file():
            try:
                rb_data = json.loads(rb_file.read_text(encoding="utf-8"))
                meta = rb_data.get("metadata") if isinstance(rb_data.get("metadata"), dict) else {}
                date_str = rb_data.get("research_date") or meta.get("published_at") or ""
            except Exception:
                pass
    if not date_str and project_dir:
        tb_file = project_dir / "artifacts" / "topic_brief.json"
        if tb_file.is_file():
            try:
                tb_data = json.loads(tb_file.read_text(encoding="utf-8"))
                date_str = tb_data.get("created_at") or tb_data.get("date") or ""
            except Exception:
                pass

    if not date_str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y")

    try:
        import datetime
        clean_date = str(date_str).split("T")[0]
        dt = datetime.datetime.strptime(clean_date, "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return str(date_str).split("T")[0]


def _find_matching_visual_asset(visuals_src: Path, aid: str, exts: tuple[str, ...]) -> Optional[str]:
    for ext in exts:
        fname = f"{aid}{ext}"
        if (visuals_src / fname).is_file():
            return fname
    return None


def _resolve_beat_visual_file(beat: Dict[str, Any], visuals_src: Optional[Path], default_aid: str) -> str:
    """Resolve the visual asset file name for a beat, prioritizing AI raster formats when appropriate."""
    if not visuals_src or not visuals_src.is_dir():
        return Path(beat["file"]).name if beat.get("file") else f"{default_aid}{EXT_SVG}"

    is_ai_beat = (
        beat.get("visual_kind") == "illustration"
        or beat.get("render_strategy") == "ai_illustration_eligible"
    )
    pref_exts = AI_PREFERRED_EXTS if is_ai_beat else SVG_PREFERRED_EXTS

    match = _find_matching_visual_asset(visuals_src, default_aid, pref_exts)
    if match:
        return match

    for alt_aid in beat.get("asset_ids", []):
        alt_match = _find_matching_visual_asset(visuals_src, alt_aid, pref_exts)
        if alt_match:
            return alt_match

    return f"{default_aid}{EXT_SVG}"


def _inline_svg_file(visuals_src: Optional[Path], vis_file: str) -> str:
    """Inline and clean SVG markup from disk if valid SVG."""
    if not (visuals_src and (visuals_src / vis_file).is_file() and vis_file.lower().endswith(".svg")):
        return ""
    try:
        import re
        raw_svg = (visuals_src / vis_file).read_text(encoding="utf-8")
        clean = re.sub(r"<\?xml.*?\?>", "", raw_svg, flags=re.DOTALL).strip()
        if "<svg" in clean and "</svg>" in clean and len(clean) > 100 and ("<g" in clean or "<path" in clean):
            return clean
        return ""
    except Exception:
        return ""


def _build_illustration_beat(
    i: int,
    beat: Dict[str, Any],
    vis_file: str,
    total_beats: int,
    duration: float,
    formatted_date: str = "",
) -> tuple[str, List[str]]:
    """Build HTML section and GSAP tweens for an illustration scene."""
    bid = str(beat.get("beat_id", f"B{i+1:02d}")).lower()
    start_s = float(beat.get("start_s", 0.0))
    end_s = float(beat.get("end_s", duration))
    beat_dur = max(0.5, end_s - start_s)
    s_func = str(beat.get("story_function", "scene")).replace("_", " ").upper()
    scr_state = html_mod.escape(str(beat.get("expected_screen_state", s_func)), quote=True)
    track_idx = i + 1
    sec_id = f"scene-{bid}"

    date_snippet = f'        <span class="date-badge">{html_mod.escape(formatted_date, quote=True)}</span>\n' if formatted_date else ""
    html = (
        f'    <section id="{sec_id}" class="clip scene illustration-scene" '
        f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
        f'      <div class="illustration-viewport">\n'
        f'        <img src="assets/visuals/{vis_file}" alt="{scr_state}" class="hero-illustration" />\n'
        f'        <div class="vignette-overlay"></div>\n'
        f'      </div>\n'
        f'      <div class="stage-header stage-header-overlay">\n'
        f'{date_snippet}'
        f'        <span class="stage-badge">Stage {i+1} of {total_beats} // {html_mod.escape(s_func, quote=True)}</span>\n'
        f'      </div>\n'
        f'    </section>'
    )
    entry_t = _fmt_time(max(0.0, start_s))
    tweens = [
        f'  tl.fromTo("#{sec_id}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5, ease: "power2.out" }}, {entry_t});',
        f'  tl.fromTo("#{sec_id} .hero-illustration", {{ scale: 1.0 }}, {{ scale: 1.05, duration: {beat_dur:.2f}, ease: "none" }}, {entry_t});',
    ]
    if i < total_beats - 1:
        exit_start_t = _fmt_time(max(0.0, end_s - 0.25))
        exit_end_t = _fmt_time(max(0.0, end_s))
        tweens.extend([
            f'  tl.to("#{sec_id}", {{ opacity: 0, duration: 0.25, ease: "power2.in" }}, {exit_start_t});',
            f'  tl.set("#{sec_id}", {{ opacity: 0 }}, {exit_end_t});',
        ])
    return html, tweens


def _build_svg_beat(
    i: int,
    beat: Dict[str, Any],
    vis_file: str,
    visuals_src: Optional[Path],
    total_beats: int,
    duration: float,
    *,
    title: str = "Practical AI Agent Engineering",
    is_vertical: bool = True,
    formatted_date: str = "",
) -> tuple[str, List[str]]:
    """Build HTML section and GSAP tweens for a technical SVG diagram scene."""
    bid = str(beat.get("beat_id", f"B{i+1:02d}")).lower()
    start_s = float(beat.get("start_s", 0.0))
    end_s = float(beat.get("end_s", duration))
    beat_dur = max(0.5, end_s - start_s)
    s_func = str(beat.get("story_function", "scene")).replace("_", " ").upper()
    scr_state = html_mod.escape(str(beat.get("expected_screen_state", s_func)), quote=True)
    track_idx = i + 1
    sec_id = f"scene-{bid}"

    bg_art = f"bg_{bid}{EXT_WEBP}" if visuals_src and (visuals_src / f"bg_{bid}{EXT_WEBP}").is_file() else ""
    bg_snippet = (
        f'      <div class="illustration-viewport">\n'
        f'        <img src="assets/visuals/{bg_art}" alt="" class="hero-illustration" />\n'
        f'        <div class="vignette-overlay"></div>\n'
        f'      </div>\n'
        if bg_art else ""
    )
    card_cls = "stage-card hybrid-card" if bg_art else "stage-card"

    inline_svg = _inline_svg_file(visuals_src, vis_file)
    is_legacy = os.environ.get("OPENMONTAGE_VISUAL_STYLE") == "legacy"
    if not is_legacy and not inline_svg and vis_file.lower().endswith(".svg"):
        from lib.fixed_niche.svg_pipeline_builder import generate_pipeline_svg
        import re
        topic_family = str(beat.get("topic_family") or "context_memory")
        narration = str(beat.get("narration") or beat.get("visual_intent") or s_func)
        word_ts = beat.get("word_timestamps")
        raw_svg = generate_pipeline_svg(
            asset_id=str(beat.get("asset_id") or f"beat_{i+1}"),
            topic_family=topic_family,
            title=title,
            beat_num=i + 1,
            total_beats=total_beats,
            is_vertical=is_vertical,
            progressive=True,
            duration=beat_dur,
            narration=narration,
            beat_start_s=start_s,
            word_timestamps=word_ts,
        )
        inline_svg = re.sub(r"<\?xml.*?\?>", "", raw_svg, flags=re.DOTALL).strip()
    viewport_content = inline_svg if (inline_svg and not is_legacy) else f'<img src="assets/visuals/{vis_file}" alt="{scr_state}" class="technical-svg" />'

    date_snippet = f'          <span class="date-badge">{html_mod.escape(formatted_date, quote=True)}</span>\n' if formatted_date else ""
    html = (
        f'    <section id="{sec_id}" class="clip scene" '
        f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
        f'{bg_snippet}'
        f'      <div class="{card_cls}">\n'
        f'        <div class="stage-header">\n'
        f'{date_snippet}'
        f'          <span class="stage-badge">Stage {i+1} of {total_beats} // {html_mod.escape(s_func, quote=True)}</span>\n'
        f'        </div>\n'
        f'        <div class="diagram-viewport" data-asset-file="assets/visuals/{vis_file}">\n'
        f'          {viewport_content}\n'
        f'        </div>\n'
        f'      </div>\n'
        f'    </section>'
    )

    entry_t = _fmt_time(max(0.0, start_s))
    tweens: List[str] = []
    if bg_art:
        tweens.append(
            f'  tl.fromTo("#{sec_id} .hero-illustration", '
            f'{{ scale: 1.0 }}, '
            f'{{ scale: 1.05, duration: {beat_dur:.2f}, ease: "none" }}, '
            f'{entry_t});'
        )
    tweens.append(
        f'  tl.fromTo("#{sec_id} .stage-card", '
        f'{{ opacity: 0, y: 30, scale: 0.98 }}, '
        f'{{ opacity: 1, y: 0, scale: 1.0, duration: 0.45, ease: "power2.out" }}, '
        f'{entry_t});'
    )

    progressive_reveal = os.environ.get("OPENMONTAGE_PROGRESSIVE_SVG", "1") not in ("0", "false", "False")
    if progressive_reveal and vis_file.lower().endswith(".svg"):
        from lib.fixed_niche.voice_timing_aligner import compute_step_timings_for_beat
        from lib.fixed_niche.svg_pipeline_builder import STEP_COUNTS
        num_steps = STEP_COUNTS.get(i + 1, 4)
        narration = str(beat.get("narration") or beat.get("visual_intent") or s_func)
        word_ts = beat.get("word_timestamps")
        step_timings = compute_step_timings_for_beat(
            narration=narration,
            duration=beat_dur,
            num_steps=num_steps,
            beat_start_s=start_s,
            word_timestamps=word_ts,
        )
        tweens.extend([
            f'  tl.set("#{sec_id} .flow-step", {{ opacity: 0, y: 16 }}, {entry_t});',
            f'  tl.set("#{sec_id} .flow-arrow", {{ opacity: 0 }}, {entry_t});',
            f'  tl.to("#{sec_id} #flow-header", {{ opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }}, {_fmt_time(start_s + 0.1)});',
        ])
        for s_idx, rel_t in enumerate(step_timings, start=1):
            step_abs_t = _fmt_time(start_s + rel_t)
            tweens.append(
                f'  tl.to("#{sec_id} #flow-step-{s_idx}", '
                f'{{ opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(1.4)" }}, {step_abs_t});'
            )
            if s_idx > 1:
                arrow_abs_t = _fmt_time(max(start_s + 0.1, start_s + rel_t - 0.3))
                tweens.append(
                    f'  tl.to("#{sec_id} #flow-arrow-{s_idx-1}", '
                    f'{{ opacity: 1, duration: 0.3, ease: "power1.inOut" }}, {arrow_abs_t});'
                )
            if s_idx == num_steps:
                tweens.append(
                    f'  tl.to("#{sec_id} #flow-cta-banner", '
                    f'{{ opacity: 1, y: 0, scale: 1, duration: 0.5, ease: "back.out(1.7)" }}, {step_abs_t});'
                )

    if i < total_beats - 1:
        exit_start_t = _fmt_time(max(0.0, end_s - 0.25))
        exit_end_t = _fmt_time(max(0.0, end_s))
        tweens.extend([
            f'  tl.to("#{sec_id} .stage-card", {{ opacity: 0, duration: 0.25, ease: "power2.in" }}, {exit_start_t});',
            f'  tl.set("#{sec_id} .stage-card", {{ opacity: 0 }}, {exit_end_t});',
        ])

    return html, tweens


def compose_hyperframes_html(
    title: str,
    duration: float,
    beats: List[Dict[str, Any]],
    *,
    is_vertical: bool = True,
    audio_src: str = DEFAULT_AUDIO_SRC,
    visuals_src: Optional[Path] = None,
    diagram_plan: Optional[Any] = None,
    topic: Optional[Dict[str, Any]] = None,
    project_dir: Optional[Path] = None,
) -> str:
    """Compose production HyperFrames HTML composition matching hyperframes-core contract."""
    import os
    formatted_date = _extract_formatted_date(topic, project_dir)

    has_beat_visuals = False
    if visuals_src and visuals_src.is_dir():
        for b in beats:
            aid = b.get("asset_id") or ""
            vis_f = _resolve_beat_visual_file(b, visuals_src, aid)
            if (visuals_src / vis_f).is_file():
                has_beat_visuals = True
                break

    visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg")
    flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") not in ("0", "false", "False")
    if (visual_style == "animated_agent_diagram_v1") and flag_enabled and not has_beat_visuals:
        from lib.visual_style.hyperframes_adapter import compose_animated_diagram_html
        return compose_animated_diagram_html(
            title=title,
            duration=duration,
            beats=beats,
            is_vertical=is_vertical,
            audio_src=audio_src,
            visuals_src=visuals_src,
            diagram_plan=diagram_plan,
            topic=topic,
            formatted_date=formatted_date,
        )

    width = 1080 if is_vertical else 1920
    height = 1920 if is_vertical else 1080
    dia_w = 980 if is_vertical else 960
    dia_h = 1100 if is_vertical else 540
    escaped_title = html_mod.escape(title, quote=True)

    sections_html: List[str] = []
    tweens_js: List[str] = []

    for i, beat in enumerate(beats):
        aid = beat.get("asset_id") or f"beat_{i+1}"
        vis_file = _resolve_beat_visual_file(beat, visuals_src, aid)
        is_illustration = vis_file.lower().endswith(RASTER_EXTENSIONS)

        if is_illustration:
            sec_html, sec_tweens = _build_illustration_beat(i, beat, vis_file, len(beats), duration, formatted_date=formatted_date)
            sections_html.append(sec_html)
            tweens_js.extend(sec_tweens)
        else:
            sec_html, sec_tweens = _build_svg_beat(
                i, beat, vis_file, visuals_src, len(beats), duration,
                title=title, is_vertical=is_vertical, formatted_date=formatted_date,
            )
            sections_html.append(sec_html)
            tweens_js.extend(sec_tweens)

    sfx_clips: List[str] = []
    for idx, beat in enumerate(beats):
        b_start = float(beat.get("start_s") if beat.get("start_s") is not None else beat.get("start_seconds", 0.0))
        sfx_clips.append(
            f'    <audio class="clip sfx" data-start="{_fmt_time(b_start)}" data-duration="0.8" data-track-index="{10 + idx}" src="assets/sfx/whoosh-short.mp3" data-volume="0.22"></audio>'
        )
    last_b = beats[-1] if beats else {}
    last_st = float(last_b.get("start_s") if last_b.get("start_s") is not None else 0.0)
    last_end = float(last_b.get("end_s", duration))
    cta_sfx_t = max(last_st + 0.5, last_end - 3.5)
    sfx_clips.append(
        f'    <audio class="clip sfx" data-start="{_fmt_time(cta_sfx_t)}" data-duration="1.2" data-track-index="20" src="assets/sfx/chime.mp3" data-volume="0.28"></audio>'
    )
    sfx_block = "\n".join(sfx_clips)

    clips_block = "\n".join(sections_html)
    tweens_block = "\n".join(tweens_js)
    starts_js = ", ".join(_fmt_time(b.get("start_s") if b.get("start_s") is not None else b.get("start_seconds", 0.0)) for b in beats)
    bgm_fadeout_t = _fmt_time(max(0.0, duration - 1.5))

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
    .date-badge {{
      display: inline-block;
      padding: 8px 18px;
      margin-right: 12px;
      background: rgba(15, 23, 42, 0.9);
      border: 1.5px solid rgba(56, 189, 248, 0.5);
      border-radius: 9999px;
      color: #38bdf8;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      box-shadow: 0 4px 14px rgba(56, 189, 248, 0.2);
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
      width: {dia_w}px;
      height: {dia_h}px;
      border-radius: 20px;
      overflow: hidden;
      border: 1.5px solid #334155;
      background: #0b1120;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.75);
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .hybrid-card {{
      position: relative;
      z-index: 3;
    }}
    .hybrid-card .diagram-viewport {{
      background: rgba(11, 17, 32, 0.88);
      backdrop-filter: blur(16px);
      border: 1.5px solid rgba(56, 189, 248, 0.4);
      box-shadow: 0 30px 60px -12px rgba(0, 0, 0, 0.9), 0 0 40px rgba(56, 189, 248, 0.15);
    }}
    .technical-svg {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }}
    .clip.illustration-scene {{
      padding: 0;
    }}
    .illustration-viewport {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .hero-illustration {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      transform-origin: center center;
    }}
    .vignette-overlay {{
      position: absolute;
      inset: 0;
      background: linear-gradient(
        to bottom,
        rgba(11, 17, 32, 0.78) 0%,
        rgba(11, 17, 32, 0.15) 18%,
        rgba(11, 17, 32, 0.1) 65%,
        rgba(11, 17, 32, 0.88) 100%
      );
      pointer-events: none;
      z-index: 2;
    }}
    .stage-header-overlay {{
      position: absolute;
      top: 100px;
      left: 0;
      right: 0;
      z-index: 3;
      margin-bottom: 0;
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-width="{width}" data-height="{height}" data-duration="{_fmt_time(duration)}">
    <div class="bg-fill"></div>
    <audio id="narration" class="clip" data-start="0" data-duration="{_fmt_time(duration)}" data-track-index="0" src="{audio_src}"></audio>
    <audio id="bgm" class="clip" data-start="0" data-duration="{_fmt_time(duration)}" data-track-index="1" src="assets/music-bg.mp3" data-volume="0.12" loop></audio>
{sfx_block}
{clips_block}
  </div>
  <script>
  (function() {{
    const starts = [{starts_js}];
    window.__timelines = window.__timelines || {{}};
    const tl = gsap.timeline({{ paused: true }});
    tl.fromTo("#bgm", {{ volume: 0 }}, {{ volume: 0.12, duration: 1.5, ease: "power2.out" }}, 0);
    tl.to("#bgm", {{ volume: 0, duration: 1.5, ease: "power2.in" }}, {bgm_fadeout_t});
{tweens_block}
    window.__timelines["main"] = tl;
  }})();
  </script>
</body>
</html>
"""


def _load_diagram_plan(project_dir: Path) -> Optional[Any]:
    sidecar_file = project_dir / "artifacts" / "diagram_animation_plan.json"
    if not sidecar_file.is_file():
        return None
    try:
        from lib.visual_style.spec import DiagramAnimationPlan
        from lib.visual_style.validation import validate_diagram_plan_data
        plan_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        errs = validate_diagram_plan_data(plan_data)
        if errs:
            raise ValueError(f"Sidecar failed validation ({len(errs)} errors): {errs}")
        return DiagramAnimationPlan.from_dict(plan_data)
    except Exception as exc:
        logger.warning(f"Could not load sidecar {sidecar_file}: {exc}")
        return None


COPYABLE_MEDIA_EXTS = (EXT_PNG, EXT_JPG, EXT_JPEG, EXT_WEBP, ".mp4", ".webm")


def _copy_composition_visuals(visuals_src: Optional[Path], comp_vis: Path) -> None:
    """Ensure composition visuals directory has no static diagram SVGs in progressive mode."""
    is_legacy = os.environ.get("OPENMONTAGE_VISUAL_STYLE") == "legacy"
    if not is_legacy and comp_vis.is_dir():
        for existing_svg in comp_vis.glob("*.svg"):
            try:
                existing_svg.unlink()
            except OSError:
                pass
    if not visuals_src or not visuals_src.is_dir():
        return
    copy_exts = ALL_SUPPORTED_MEDIA_EXTS if is_legacy else COPYABLE_MEDIA_EXTS
    for vis_file in visuals_src.iterdir():
        if vis_file.is_file() and vis_file.suffix.lower() in copy_exts:
            comp_vis.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vis_file, comp_vis / vis_file.name)


def _copy_composition_vendor(comp_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    local_gsap = repo_root / "assets" / "vendor" / "gsap.min.js"
    if not local_gsap.is_file():
        local_gsap = Path("assets/vendor/gsap.min.js")
    if local_gsap.is_file():
        comp_vendor = comp_dir / "assets" / "vendor"
        comp_vendor.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_gsap, comp_vendor / "gsap.min.js")


def _copy_composition_audio(audio_src: Path, comp_dir: Path) -> None:
    comp_assets = comp_dir / "assets"
    comp_assets.mkdir(parents=True, exist_ok=True)
    if audio_src.is_file():
        shutil.copy2(audio_src, comp_assets / NARRATION_MP3_FILENAME)

    repo_root = Path(__file__).resolve().parents[2]
    parent_assets = comp_dir.parent / "assets"

    # Copy background music bed
    for bgm_cand in (
        parent_assets / "music-bg.mp3",
        audio_src.parent / "music-bg.mp3",
        repo_root / "assets" / "audio" / "music-bg.mp3",
    ):
        if bgm_cand.is_file():
            shutil.copy2(bgm_cand, comp_assets / "music-bg.mp3")
            if not (parent_assets / "music-bg.mp3").is_file():
                parent_assets.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bgm_cand, parent_assets / "music-bg.mp3")
            break

    # Copy sound effects library
    for sfx_dir in (
        parent_assets / "sfx",
        audio_src.parent / "sfx",
        repo_root / "assets" / "audio" / "sfx",
    ):
        if sfx_dir.is_dir():
            comp_sfx = comp_assets / "sfx"
            comp_sfx.mkdir(parents=True, exist_ok=True)
            for f in sfx_dir.glob("*.mp3"):
                shutil.copy2(f, comp_sfx / f.name)
            parent_sfx = parent_assets / "sfx"
            if not parent_sfx.is_dir():
                parent_sfx.mkdir(parents=True, exist_ok=True)
                for f in sfx_dir.glob("*.mp3"):
                    shutil.copy2(f, parent_sfx / f.name)
            break


def _materialize_single_composition(
    comp_name: str,
    project_dir: Path,
    title: str,
    duration: float,
    beats: List[Dict[str, Any]],
    visuals_src: Path,
    audio_src: Path,
    diagram_plan: Optional[Any],
    topic: Optional[Dict[str, Any]] = None,
) -> Path:
    comp_dir = project_dir / comp_name
    comp_dir.mkdir(parents=True, exist_ok=True)
    _copy_composition_visuals(visuals_src, comp_dir / "assets" / "visuals")
    _copy_composition_vendor(comp_dir)
    _copy_composition_audio(audio_src, comp_dir)
    is_vertical = "reels" in comp_name or "short" in comp_name
    html_content = compose_hyperframes_html(
        title=title,
        duration=duration,
        beats=beats,
        is_vertical=is_vertical,
        audio_src=DEFAULT_AUDIO_SRC,
        visuals_src=visuals_src,
        diagram_plan=diagram_plan,
        topic=topic,
        project_dir=project_dir,
    )
    index_file = comp_dir / "index.html"
    index_file.write_text(html_content, encoding="utf-8")
    return index_file


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
    audio_src = project_dir / "assets" / NARRATION_MP3_FILENAME
    beats = visual_plan.get("beats", [])
    title = topic.get("title", "Practical AI Agent Engineering")
    diagram_plan = _load_diagram_plan(project_dir)

    result_paths: Dict[str, Path] = {}
    for comp_name in composition_names:
        result_paths[comp_name] = _materialize_single_composition(
            comp_name=comp_name,
            project_dir=project_dir,
            title=title,
            duration=duration,
            beats=beats,
            visuals_src=visuals_src,
            audio_src=audio_src,
            diagram_plan=diagram_plan,
            topic=topic,
        )
    return result_paths


def render_hyperframes_composition(
    comp_dir: Path,
    output_mp4: Path,
    *,
    quality: str = "draft",
    timeout_seconds: float = 600.0,
    burn_captions: bool = False,
    ass_path: Optional[Path] = None,
) -> Path:
    """Render HyperFrames composition using `npx hyperframes render`.

    If burn_captions is True and ass_path exists, burns subtitles into output.
    """
    comp_dir = Path(comp_dir).resolve()
    output_mp4 = Path(output_mp4).resolve()
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    # Ensure narration and audio assets exist in comp_dir/assets
    _copy_composition_audio(comp_dir.parent / "assets" / NARRATION_MP3_FILENAME, comp_dir)

    raw_mp4 = output_mp4 if not burn_captions else output_mp4.with_suffix(".raw.mp4")
    cmd = [
        "npx", "hyperframes", "render",
        str(comp_dir),
        "-o", str(raw_mp4),
        "--quality", quality,
    ]
    env = dict(os.environ)
    if "HYPERFRAMES_BROWSER_PATH" not in env:
        playwright_shell = Path("/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux/headless_shell")
        brave_sh = Path("/tmp/brave_headless.sh")
        if playwright_shell.is_file():
            env["HYPERFRAMES_BROWSER_PATH"] = str(playwright_shell)
        elif not brave_sh.is_file() and Path("/opt/brave.com/brave/brave").is_file():
            brave_sh.write_text(
                "#!/bin/bash\nexec /opt/brave.com/brave/brave --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage \"$@\"\n",
                encoding="utf-8",
            )
            brave_sh.chmod(0o755)
            env["HYPERFRAMES_BROWSER_PATH"] = str(brave_sh)
        elif brave_sh.is_file():
            env["HYPERFRAMES_BROWSER_PATH"] = str(brave_sh)

    logger.info("Executing HyperFrames render: %s", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"HyperFrames render failed (exit {res.returncode}): {res.stderr or res.stdout}")

    if burn_captions and ass_path and ass_path.is_file():
        esc_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        burn_cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(raw_mp4),
            "-vf", f"ass='{esc_ass}'",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "copy",
            str(output_mp4),
        ]
        subprocess.run(burn_cmd, check=True)
        raw_mp4.unlink(missing_ok=True)

    return output_mp4
from lib.fixed_niche.ffmpeg_composer import render_ffmpeg_composition  # Facade re-export
