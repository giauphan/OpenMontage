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

logger = logging.getLogger(__name__)


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
    visuals_src: Optional[Path] = None,
    diagram_plan: Optional[Any] = None,
) -> str:
    """Compose production HyperFrames HTML composition matching hyperframes-core contract."""
    import os
    visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "animated_agent_diagram_v1")
    flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "1") not in ("0", "false", "False")
    if (visual_style == "animated_agent_diagram_v1") and flag_enabled:
        from lib.visual_style.hyperframes_adapter import compose_animated_diagram_html
        return compose_animated_diagram_html(
            title=title,
            duration=duration,
            beats=beats,
            is_vertical=is_vertical,
            audio_src=audio_src,
            visuals_src=visuals_src,
            diagram_plan=diagram_plan,
        )

    width = 1080 if is_vertical else 1920
    height = 1920 if is_vertical else 1080
    dia_w = 980 if is_vertical else 960
    dia_h = 1100 if is_vertical else 540
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

        # Resolve asset file type
        vis_file = f"{aid}.svg"
        if visuals_src and visuals_src.is_dir():
            found = False
            is_ai_beat = (
                beat.get("visual_kind") == "illustration"
                or beat.get("render_strategy") == "ai_illustration_eligible"
            )
            pref_exts = (
                (".webp", ".png", ".jpg", ".jpeg", ".svg")
                if is_ai_beat
                else (".svg", ".webp", ".png", ".jpg", ".jpeg")
            )
            for ext in pref_exts:
                if (visuals_src / f"{aid}{ext}").is_file():
                    vis_file = f"{aid}{ext}"
                    found = True
                    break
                for alt_aid in beat.get("asset_ids", []):
                    if (visuals_src / f"{alt_aid}{ext}").is_file():
                        vis_file = f"{alt_aid}{ext}"
                        found = True
                        break
                if found:
                    break
        elif beat.get("file"):
            vis_file = Path(beat["file"]).name

        sec_id = f"scene-{bid}"
        is_illustration = vis_file.lower().endswith((".webp", ".png", ".jpg", ".jpeg"))

        if is_illustration:
            sections_html.append(
                f'    <section id="{sec_id}" class="clip scene illustration-scene" '
                f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
                f'      <div class="illustration-viewport">\n'
                f'        <img src="assets/visuals/{vis_file}" alt="{scr_state}" class="hero-illustration" />\n'
                f'        <div class="vignette-overlay"></div>\n'
                f'      </div>\n'
                f'      <div class="stage-header stage-header-overlay">\n'
                f'        <span class="stage-badge">Stage {i+1} of {len(beats)} // {html_mod.escape(s_func, quote=True)}</span>\n'
                f'      </div>\n'
                f'    </section>'
            )
            entry_t = _fmt_time(max(0.0, start_s))
            tweens_js.append(
                f'  tl.fromTo("#{sec_id}", '
                f'{{ opacity: 0 }}, '
                f'{{ opacity: 1, duration: 0.5, ease: "power2.out" }}, '
                f'{entry_t});'
            )
            tweens_js.append(
                f'  tl.fromTo("#{sec_id} .hero-illustration", '
                f'{{ scale: 1.0 }}, '
                f'{{ scale: 1.05, duration: {beat_dur:.2f}, ease: "none" }}, '
                f'{entry_t});'
            )
            if i < len(beats) - 1:
                exit_start_t = _fmt_time(max(0.0, end_s - 0.25))
                exit_end_t = _fmt_time(max(0.0, end_s))
                tweens_js.append(
                    f'  tl.to("#{sec_id}", '
                    f'{{ opacity: 0, duration: 0.25, ease: "power2.in" }}, '
                    f'{exit_start_t});'
                )
                tweens_js.append(
                    f'  tl.set("#{sec_id}", {{ opacity: 0 }}, {exit_end_t});'
                )
        else:
            bg_art = f"bg_{bid}.webp" if visuals_src and (visuals_src / f"bg_{bid}.webp").is_file() else ""
            bg_snippet = (
                f'      <div class="illustration-viewport">\n'
                f'        <img src="assets/visuals/{bg_art}" alt="" class="hero-illustration" />\n'
                f'        <div class="vignette-overlay"></div>\n'
                f'      </div>\n'
                if bg_art else ""
            )
            card_cls = "stage-card hybrid-card" if bg_art else "stage-card"

            # Read and inline progressive SVG if available
            inline_svg = ""
            if visuals_src and (visuals_src / vis_file).is_file() and vis_file.lower().endswith(".svg"):
                try:
                    import re
                    raw_svg = (visuals_src / vis_file).read_text(encoding="utf-8")
                    clean_svg = re.sub(r"<\?xml.*?\?>", "", raw_svg, flags=re.DOTALL).strip()
                    inline_svg = clean_svg
                except Exception:
                    inline_svg = ""

            viewport_content = inline_svg if inline_svg else f'<img src="assets/visuals/{vis_file}" alt="{scr_state}" class="technical-svg" />'

            sections_html.append(
                f'    <section id="{sec_id}" class="clip scene" '
                f'data-start="{_fmt_time(start_s)}" data-duration="{_fmt_time(beat_dur)}" data-track-index="{track_idx}">\n'
                f'{bg_snippet}'
                f'      <div class="{card_cls}">\n'
                f'        <div class="stage-header">\n'
                f'          <span class="stage-badge">Stage {i+1} of {len(beats)} // {html_mod.escape(s_func, quote=True)}</span>\n'
                f'        </div>\n'
                f'        <div class="diagram-viewport" data-asset-file="assets/visuals/{vis_file}">\n'
                f'          {viewport_content}\n'
                f'        </div>\n'
                f'      </div>\n'
                f'    </section>'
            )

            # GSAP animation per beat: smooth fade and subtle rise on entry
            entry_t = _fmt_time(max(0.0, start_s))
            if bg_art:
                tweens_js.append(
                    f'  tl.fromTo("#{sec_id} .hero-illustration", '
                    f'{{ scale: 1.0 }}, '
                    f'{{ scale: 1.05, duration: {beat_dur:.2f}, ease: "none" }}, '
                    f'{entry_t});'
                )
            tweens_js.append(
                f'  tl.fromTo("#{sec_id} .stage-card", '
                f'{{ opacity: 0, y: 30, scale: 0.98 }}, '
                f'{{ opacity: 1, y: 0, scale: 1.0, duration: 0.45, ease: "power2.out" }}, '
                f'{entry_t});'
            )

            # Progressive voice-ordered reveals for SVG diagrams
            progressive_reveal = os.environ.get("OPENMONTAGE_PROGRESSIVE_SVG", "1") not in ("0", "false", "False")
            if progressive_reveal and vis_file.lower().endswith(".svg"):
                from lib.fixed_niche.voice_timing_aligner import compute_step_timings_for_beat
                from lib.fixed_niche.svg_pipeline_builder import STEP_COUNTS
                num_steps = STEP_COUNTS.get(i + 1, 4)
                narration = str(beat.get("narration") or beat.get("visual_intent") or s_func)
                step_timings = compute_step_timings_for_beat(
                    narration=narration,
                    duration=beat_dur,
                    num_steps=num_steps,
                    beat_start_s=start_s,
                )
                tweens_js.append(f'  tl.set("#{sec_id} .flow-step", {{ opacity: 0, y: 16 }}, {entry_t});')
                tweens_js.append(f'  tl.set("#{sec_id} .flow-arrow", {{ opacity: 0 }}, {entry_t});')
                tweens_js.append(f'  tl.to("#{sec_id} #flow-header", {{ opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }}, {_fmt_time(start_s + 0.1)});')
                for s_idx, rel_t in enumerate(step_timings, start=1):
                    step_abs_t = _fmt_time(start_s + rel_t)
                    tweens_js.append(
                        f'  tl.to("#{sec_id} #flow-step-{s_idx}", '
                        f'{{ opacity: 1, y: 0, duration: 0.45, ease: "power2.out" }}, {step_abs_t});'
                    )
                    if s_idx > 1:
                        arrow_abs_t = _fmt_time(max(start_s + 0.1, start_s + rel_t - 0.3))
                        tweens_js.append(
                            f'  tl.to("#{sec_id} #flow-arrow-{s_idx-1}", '
                            f'{{ opacity: 1, duration: 0.3, ease: "power1.inOut" }}, {arrow_abs_t});'
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
    starts_js = ", ".join(_fmt_time(b.get("start_s") if b.get("start_s") is not None else b.get("start_seconds", 0.0)) for b in beats)

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
{clips_block}
  </div>
  <script>
  (function() {{
    const starts = [{starts_js}];
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

    # Resolve diagram animation plan if available
    diagram_plan = None
    sidecar_file = project_dir / "artifacts" / "diagram_animation_plan.json"
    if sidecar_file.is_file():
        try:
            from lib.visual_style.spec import DiagramAnimationPlan
            from lib.visual_style.validation import validate_diagram_plan_data
            plan_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
            errs = validate_diagram_plan_data(plan_data)
            if errs:
                raise ValueError(f"Sidecar failed validation ({len(errs)} errors): {errs}")
            diagram_plan = DiagramAnimationPlan.from_dict(plan_data)
        except Exception as exc:
            logger.warning(f"Could not load sidecar {sidecar_file}: {exc}")

    result_paths: Dict[str, Path] = {}

    for comp_name in composition_names:
        comp_dir = project_dir / comp_name
        comp_dir.mkdir(parents=True, exist_ok=True)

        # Copy visual media assets (SVG diagrams, PNG/JPEG/WEBP illustrations, captures)
        comp_vis = comp_dir / "assets" / "visuals"
        comp_vis.mkdir(parents=True, exist_ok=True)
        if visuals_src.is_dir():
            for vis_file in visuals_src.iterdir():
                if vis_file.is_file() and vis_file.suffix.lower() in (".svg", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"):
                    shutil.copy2(vis_file, comp_vis / vis_file.name)

        # Copy local vendor scripts (e.g. pinned gsap.min.js) if present for offline render
        repo_root = Path(__file__).resolve().parents[2]
        local_gsap = repo_root / "assets" / "vendor" / "gsap.min.js"
        if not local_gsap.is_file():
            local_gsap = Path("assets/vendor/gsap.min.js")
        if local_gsap.is_file():
            comp_vendor = comp_dir / "assets" / "vendor"
            comp_vendor.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_gsap, comp_vendor / "gsap.min.js")

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
            visuals_src=visuals_src,
            diagram_plan=diagram_plan,
        )

        index_file = comp_dir / "index.html"
        index_file.write_text(html_content, encoding="utf-8")
        result_paths[comp_name] = index_file

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

    # Ensure narration.mp3 exists in comp_dir/assets if present in parent project assets
    parent_audio = comp_dir.parent / "assets" / "narration.mp3"
    comp_audio = comp_dir / "assets" / "narration.mp3"
    if parent_audio.is_file() and (not comp_audio.is_file() or comp_audio.stat().st_size != parent_audio.stat().st_size):
        comp_audio.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent_audio, comp_audio)

    raw_mp4 = output_mp4 if not burn_captions else output_mp4.with_suffix(".raw.mp4")
    cmd = [
        "npx", "hyperframes", "render",
        str(comp_dir),
        "-o", str(raw_mp4),
        "--quality", quality,
    ]
    env = dict(os.environ)
    if "HYPERFRAMES_BROWSER_PATH" not in env:
        brave_sh = Path("/tmp/brave_headless.sh")
        if not brave_sh.is_file() and Path("/opt/brave.com/brave/brave").is_file():
            brave_sh.write_text(
                "#!/bin/bash\nexec /opt/brave.com/brave/brave --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage \"$@\"\n",
                encoding="utf-8",
            )
            brave_sh.chmod(0o755)
        if brave_sh.is_file():
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


def render_ffmpeg_composition(
    project_dir: Path,
    output_mp4: Path,
    render_dur: float,
    width: int = 1080,
    height: int = 1920,
    burn_captions: bool = False,
) -> Path:
    """Render composition via FFmpeg concat demuxer for fast offline/CI execution."""
    import os
    visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "animated_agent_diagram_v1")
    flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "1") not in ("0", "false", "False")
    if (visual_style == "animated_agent_diagram_v1") and flag_enabled:
        raise RuntimeError(
            "CRITICAL: Static slideshow fallback via FFmpeg is strictly forbidden for animated_agent_diagram_v1. "
            "HyperFrames dynamic element-level animation is required."
        )

    project_dir = Path(project_dir).resolve()
    output_mp4 = Path(output_mp4).resolve()
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    visuals_dir = project_dir / "assets" / "visuals"
    audio_path = project_dir / "assets" / "narration.mp3"
    renders_dir = output_mp4.parent

    visual_plan_file = project_dir / "artifacts" / "news_visual_plan.json"
    beats: List[Dict[str, Any]] = []
    if visual_plan_file.is_file():
        try:
            plan_json = json.loads(visual_plan_file.read_text(encoding="utf-8"))
            beats = plan_json.get("beats", [])
        except Exception as e:
            logger.warning(f"Could not load news_visual_plan.json: {e}")

    svg_assets = sorted(list(visuals_dir.glob("*.svg"))) if visuals_dir.is_dir() else []

    dar_str = "9/16" if (width < height) else "16/9"
    aspect_flag = "9:16" if (width < height) else "16:9"
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=#0b1120,"
        f"setsar=1/1,setdar={dar_str},"
        f"format=yuv420p"
    )

    ass_path = project_dir / "artifacts" / "captions.ass"
    srt_path = project_dir / "artifacts" / "captions.srt"
    if burn_captions:
        if ass_path.is_file():
            esc_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += f",ass='{esc_ass}'"
        elif srt_path.is_file():
            esc_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += (
                f",subtitles='{esc_srt}':force_style="
                f"'Fontname=DejaVu Sans,Fontsize=22,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H000B0F19,BorderStyle=1,Outline=2.5,Shadow=0,"
                f"MarginV=120,Alignment=2,MarginL=80,MarginR=80'"
            )

    if beats:
        planned_total = float(beats[-1].get("end_s", 0.0)) - float(beats[0].get("start_s", 0.0))
        scale = (render_dur / planned_total) if planned_total > 0 else 1.0

        concat_list = renders_dir / "slides_concat.txt"
        with concat_list.open("w", encoding="utf-8") as f:
            for b in beats:
                beat_dur = max(0.1, (float(b.get("end_s", 0.0)) - float(b.get("start_s", 0.0))) * scale)
                aid = b.get("asset_id") or (b.get("asset_ids", [""])[0] if b.get("asset_ids") else "")
                svg_cand = visuals_dir / f"{aid}.svg"
                if not svg_cand.is_file():
                    matches = list(visuals_dir.glob(f"{aid}.*"))
                    svg_cand = matches[0] if matches else (svg_assets[0] if svg_assets else None)
                if svg_cand and svg_cand.is_file():
                    f.write(f"file '{svg_cand.resolve()}'\n")
                    f.write(f"duration {beat_dur:.3f}\n")
            if svg_assets:
                last_aid = beats[-1].get("asset_id") or (beats[-1].get("asset_ids", [""])[0] if beats[-1].get("asset_ids") else "")
                last_svg = visuals_dir / f"{last_aid}.svg"
                if not last_svg.is_file():
                    last_svg = svg_assets[-1]
                f.write(f"file '{last_svg.resolve()}'\n")

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio_path),
            "-vf", vf,
            "-aspect", aspect_flag,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(render_dur),
            str(output_mp4),
        ]
        subprocess.run(cmd, check=True)
        concat_list.unlink(missing_ok=True)
    elif svg_assets:
        slide_dur = render_dur / len(svg_assets)
        concat_list = renders_dir / "slides_concat.txt"
        with concat_list.open("w", encoding="utf-8") as f:
            for svg in svg_assets:
                f.write(f"file '{svg.resolve()}'\n")
                f.write(f"duration {slide_dur:.2f}\n")
            f.write(f"file '{svg_assets[-1].resolve()}'\n")

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio_path),
            "-vf", vf,
            "-aspect", aspect_flag,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(render_dur),
            str(output_mp4),
        ]
        subprocess.run(cmd, check=True)
        concat_list.unlink(missing_ok=True)
    else:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=#0b1120:s={width}x{height}:d={render_dur}:r=30",
            "-i", str(audio_path),
            "-vf", vf,
            "-aspect", aspect_flag,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(render_dur),
            str(output_mp4),
        ]
        subprocess.run(cmd, check=True)

    return output_mp4
