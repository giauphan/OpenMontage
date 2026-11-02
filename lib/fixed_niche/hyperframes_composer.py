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


def _inline_svg_file(visuals_src: Optional[Path], vis_file: str, prefix: str = "") -> str:
    """Inline and clean SVG markup from disk if valid SVG."""
    if not (visuals_src and (visuals_src / vis_file).is_file() and vis_file.lower().endswith(".svg")):
        return ""
    try:
        import re
        raw_svg = (visuals_src / vis_file).read_text(encoding="utf-8")
        clean = re.sub(r"<\?xml.*?\?>", "", raw_svg, flags=re.DOTALL).strip()
        # Strip internal style blocks so global document styling and GSAP timelines control reveals
        clean = re.sub(r"<style\b[^>]*>.*?</style>", "", clean, flags=re.DOTALL).strip()
        if prefix:
            clean = clean.replace('id="flow-', f'id="{prefix}flow-')
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
    raw_end = float(beat.get("end_s", duration))
    end_s = min(raw_end, duration) if i == total_beats - 1 else raw_end
    beat_dur = max(0.5, end_s - start_s)
    s_func = str(beat.get("story_function", "scene")).replace("_", " ").upper()
    scr_state = html_mod.escape(str(beat.get("expected_screen_state", s_func)), quote=True)
    track_idx = i + 1
    sec_id = f"scene-{bid}"

    show_top_header = os.environ.get("OPENMONTAGE_SHOW_TOP_HEADER", "0") in ("1", "true", "True")
    header_snippet = ""
    if show_top_header:
        date_snippet = f'        <span class="date-badge">{html_mod.escape(formatted_date, quote=True)}</span>\n' if formatted_date else ""
        header_snippet = (
            f'      <div class="stage-header stage-header-overlay">\n'
            f'{date_snippet}'
            f'        <span class="stage-badge">Stage {i+1} of {total_beats} // {html_mod.escape(s_func, quote=True)}</span>\n'
            f'      </div>\n'
        )
    html = (
        f'    <section id="{sec_id}" class="clip scene illustration-scene" '
        f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
        f'      <div class="illustration-viewport">\n'
        f'        <img src="assets/visuals/{vis_file}" alt="{scr_state}" class="hero-illustration" />\n'
        f'        <div class="vignette-overlay"></div>\n'
        f'      </div>\n'
        f'{header_snippet}'
        f'    </section>'
    )
    entry_t = _fmt_time(max(0.0, start_s))
    tweens = [
        f'  tl.fromTo("#{sec_id}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5, ease: "power2.out" }}, {entry_t});',
        f'  tl.fromTo("#{sec_id} .hero-illustration", {{ scale: 1.0 }}, {{ scale: 1.03, duration: {beat_dur:.2f}, ease: "none" }}, {entry_t});',
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
    raw_end = float(beat.get("end_s", duration))
    end_s = min(raw_end, duration) if i == total_beats - 1 else raw_end
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

    pfx = f"b{i+1:02d}-" if i > 0 else ""
    inline_svg = _inline_svg_file(visuals_src, vis_file, prefix=pfx)
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
            prefix=pfx,
        )
        clean = re.sub(r"<\?xml.*?\?>", "", raw_svg, flags=re.DOTALL).strip()
        inline_svg = re.sub(r"<style\b[^>]*>.*?</style>", "", clean, flags=re.DOTALL).strip()
    viewport_content = inline_svg if (inline_svg and not is_legacy) else f'<img src="assets/visuals/{vis_file}" alt="{scr_state}" class="technical-svg" />'

    show_top_header = os.environ.get("OPENMONTAGE_SHOW_TOP_HEADER", "0") in ("1", "true", "True")
    header_snippet = ""
    if show_top_header:
        date_snippet = f'          <span class="date-badge">{html_mod.escape(formatted_date, quote=True)}</span>\n' if formatted_date else ""
        header_snippet = (
            f'        <div class="stage-header">\n'
            f'{date_snippet}'
            f'          <span class="stage-badge">Stage {i+1} of {total_beats} // {html_mod.escape(s_func, quote=True)}</span>\n'
            f'        </div>\n'
        )
    html = (
        f'    <section id="{sec_id}" class="clip scene" '
        f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
        f'{bg_snippet}'
        f'      <div class="{card_cls}">\n'
        f'{header_snippet}'
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
    # Continuous Ken Burns camera drift (scale 1.0 to 1.03) so canvas is never static
    tweens.append(
        f'  tl.fromTo("#{sec_id} .diagram-viewport", '
        f'{{ scale: 1.0, y: 0 }}, '
        f'{{ scale: 1.025, y: -6, duration: {beat_dur:.2f}, ease: "none" }}, '
        f'{entry_t});'
    )

    progressive_reveal = os.environ.get("OPENMONTAGE_PROGRESSIVE_SVG", "1") not in ("0", "false", "False")
    if progressive_reveal and vis_file.lower().endswith(".svg"):
        from lib.fixed_niche.voice_timing_aligner import compute_step_timings_for_beat, compute_cta_timing
        from lib.fixed_niche.svg_pipeline_builder import STEP_COUNTS
        num_steps = 4 if (i + 1 == 6 and total_beats == 6) else STEP_COUNTS.get(i + 1, 4)
        narration = str(beat.get("narration") or beat.get("visual_intent") or s_func)
        word_ts = beat.get("word_timestamps")
        is_final = (i == total_beats - 1)
        step_timings = compute_step_timings_for_beat(
            narration=narration,
            duration=beat_dur,
            num_steps=num_steps,
            beat_start_s=start_s,
            word_timestamps=word_ts,
            is_final_beat=is_final,
        )
        cta_rel = compute_cta_timing(beat_dur, step_timings) if is_final else None
        cta_abs_t = _fmt_time(start_s + cta_rel) if cta_rel is not None else None
        tweens.extend([
            f'  tl.set("#{sec_id} .flow-step", {{ opacity: 0, y: 16 }}, {entry_t});',
            f'  tl.set("#{sec_id} .flow-arrow", {{ opacity: 0 }}, {entry_t});',
            f'  tl.to("#{sec_id} #{pfx}flow-header", {{ opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }}, {_fmt_time(start_s + 0.1)});',
        ])
        for s_idx, rel_t in enumerate(step_timings, start=1):
            step_abs_t = _fmt_time(start_s + rel_t)
            tweens.append(
                f'  tl.fromTo("#{sec_id} #{pfx}flow-step-{s_idx}", '
                f'{{ opacity: 0, y: 20, scale: 0.95 }}, '
                f'{{ opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(1.7)" }}, {step_abs_t});'
            )
            if s_idx > 1:
                arrow_abs_t = _fmt_time(max(start_s + 0.1, start_s + rel_t - 0.3))
                tweens.append(
                    f'  tl.fromTo("#{sec_id} #{pfx}flow-arrow-{s_idx-1}", '
                    f'{{ opacity: 0, scaleY: 0.5 }}, '
                    f'{{ opacity: 1, scaleY: 1, duration: 0.35, ease: "power2.out" }}, {arrow_abs_t});'
                )

        if is_final and cta_abs_t:
            cta_reveal_t = cta_abs_t
        elif step_timings:
            cta_reveal_t = _fmt_time(start_s + step_timings[-1])
        else:
            cta_reveal_t = None
        if cta_reveal_t:
            tweens.append(
                f'  tl.fromTo("#{sec_id} #{pfx}flow-cta-banner", '
                f'{{ opacity: 0, y: 25, scale: 0.92 }}, '
                f'{{ opacity: 1, y: 0, scale: 1, duration: 0.55, ease: "back.out(1.7)" }}, {cta_reveal_t});'
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
    track_counter = 10
    progressive_reveal = os.environ.get("OPENMONTAGE_PROGRESSIVE_SVG", "1") not in ("0", "false", "False")
    last_step_timings: List[float] = []
    for idx, beat in enumerate(beats):
        b_start = float(beat.get("start_s") if beat.get("start_s") is not None else beat.get("start_seconds", 0.0))
        sfx_clips.append(
            f'    <audio class="clip sfx" data-start="{_fmt_time(b_start)}" data-duration="0.8" data-track-index="{track_counter}" src="assets/sfx/whoosh-short.mp3" data-volume="0.22"></audio>'
        )
        track_counter += 1

        # Step reveal pop / click sound effects
        aid = beat.get("asset_id") or f"beat_{idx+1}"
        vis_file = _resolve_beat_visual_file(beat, visuals_src, aid)
        if progressive_reveal and vis_file.lower().endswith(EXT_SVG):
            from lib.fixed_niche.voice_timing_aligner import compute_step_timings_for_beat
            from lib.fixed_niche.svg_pipeline_builder import STEP_COUNTS
            raw_end = float(beat.get("end_s", duration))
            b_end = min(raw_end, duration) if idx == len(beats) - 1 else raw_end
            beat_dur = max(0.5, b_end - b_start)
            num_steps = 4 if (idx + 1 == 6 and len(beats) == 6) else STEP_COUNTS.get(idx + 1, 4)
            s_func = str(beat.get("story_function", ""))
            narration = str(beat.get("narration") or beat.get("visual_intent") or s_func)
            word_ts = beat.get("word_timestamps")
            is_final = (idx == len(beats) - 1)
            step_timings = compute_step_timings_for_beat(
                narration=narration,
                duration=beat_dur,
                num_steps=num_steps,
                beat_start_s=b_start,
                word_timestamps=word_ts,
                is_final_beat=is_final,
            )
            if is_final:
                last_step_timings = step_timings
            for s_idx, rel_t in enumerate(step_timings, start=1):
                if s_idx > 1 and (b_start + rel_t) < duration - 1.0:
                    if idx in (0, 1) and s_idx == 2:
                        sfx_sound, sfx_vol = "buzz.mp3", "0.22"
                    elif idx in (3, 4) and s_idx in (2, 3):
                        sfx_sound, sfx_vol = "pass-ping.mp3", "0.20"
                    elif idx == len(beats) - 1 and s_idx == num_steps:
                        sfx_sound, sfx_vol = "pass-ping.mp3", "0.24"
                    else:
                        sfx_sound = "click.mp3" if s_idx % 2 == 0 else "pop.mp3"
                        sfx_vol = "0.16"
                    sfx_clips.append(
                        f'    <audio class="clip sfx" data-start="{_fmt_time(b_start + rel_t)}" data-duration="0.3" data-track-index="{track_counter}" src="assets/sfx/{sfx_sound}" data-volume="{sfx_vol}"></audio>'
                    )
                    track_counter += 1

    cta_sfx_t = max(0.0, duration - 1.5)
    if beats:
        from lib.fixed_niche.voice_timing_aligner import compute_cta_timing
        last_b = beats[-1]
        last_st = float(last_b.get("start_s") if last_b.get("start_s") is not None else last_b.get("start_seconds", 0.0))
        last_end = min(float(last_b.get("end_s", duration)), duration)
        last_dur = max(0.5, last_end - last_st)
        cta_rel = compute_cta_timing(last_dur, last_step_timings)
        cta_sfx_t = max(0.0, last_st + cta_rel)
        sfx_clips.append(
            f'    <audio class="clip sfx" data-start="{_fmt_time(cta_sfx_t)}" data-duration="1.2" data-track-index="{track_counter}" src="assets/sfx/chime.mp3" data-volume="0.30"></audio>'
        )
    sfx_block = "\n".join(sfx_clips)

    clips_block = "\n".join(sections_html)
    tweens_block = "\n".join(tweens_js)
    starts_js = ", ".join(_fmt_time(b.get("start_s") if b.get("start_s") is not None else b.get("start_seconds", 0.0)) for b in beats)
    bgm_fadeout_t = _fmt_time(max(0.0, duration - 1.5))

    flow_hidden_css = """
    .flow-step {
      opacity: 0;
      transform-origin: center center;
      filter: drop-shadow(0 4px 16px rgba(0, 0, 0, 0.45));
    }
    .flow-arrow {
      opacity: 0;
      transform-origin: top center;
    }
    .flow-header {
      opacity: 0;
    }
    .flow-cta-banner {
      opacity: 0;
    }""" if progressive_reveal else ""

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
{flow_hidden_css}
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
    starts.forEach(st => {{
      if (st > 1.0 && st < {_fmt_time(max(0.0, duration - 2.5))}) {{
        tl.to("#bgm", {{ volume: 0.14, duration: 0.4, ease: "power1.in" }}, st - 0.4);
        tl.to("#bgm", {{ volume: 0.09, duration: 0.6, ease: "power1.out" }}, st + 0.1);
      }}
    }});
    tl.to("#bgm", {{ volume: 0.15, duration: 0.8, ease: "power2.out" }}, {_fmt_time(cta_sfx_t)});
    tl.to("#bgm", {{ volume: 0, duration: 1.5, ease: "power2.in" }}, {bgm_fadeout_t});
{tweens_block}
    window.__timelines["main"] = tl;
  }})();
  </script>
</body>
</html>
"""


# Facade re-exports for materialization and rendering
from lib.fixed_niche.ffmpeg_composer import render_ffmpeg_composition  # Facade re-export
from lib.fixed_niche.hyperframes_materializer import (
    load_diagram_plan,
    copy_composition_visuals,
    copy_composition_vendor,
    copy_composition_audio,
    materialize_hyperframes_project,
    render_hyperframes_composition,
)

# Backward compatibility aliases
_load_diagram_plan = load_diagram_plan
_copy_composition_visuals = copy_composition_visuals
_copy_composition_vendor = copy_composition_vendor
_copy_composition_audio = copy_composition_audio
