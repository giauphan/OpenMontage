"""HTML generation, escaping, and formatting helpers for HyperFrames.

Pure functions for turning cut definitions and audio references into
HyperFrames-compliant HTML and GSAP timeline scripts.
"""

from __future__ import annotations

import html as html_lib
from pathlib import Path
from typing import Any, Optional, Set, Tuple


def format_float(v: float) -> str:
    """Format a float seconds value compactly."""
    if v is None:
        return "0"
    s = f"{float(v):.3f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def escape_text(s: str) -> str:
    """Escape text for HTML body."""
    return html_lib.escape(s or "")


def escape_attr(s: str) -> str:
    """Escape text for HTML attributes."""
    return html_lib.escape(s or "", quote=True)


def rel_from_workspace(path: str) -> str:
    """Normalize asset path to be relative to index.html in the workspace."""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        return str(p).replace("\\", "/")
    parts = p.parts
    for anchor in ("assets", "compositions"):
        if anchor in parts:
            index = len(parts) - 1 - list(reversed(parts)).index(anchor)
            return "/".join(parts[index:])
    return f"assets/{p.name}"


def compute_total_duration(cuts: list[dict[str, Any]]) -> float:
    """Compute overall composition duration from the latest out_seconds."""
    if not cuts:
        return 0.0
    return max(float(c.get("out_seconds", 0) or 0) for c in cuts)


def cut_to_html(
    index: int,
    cut: dict[str, Any],
    width: int,
    height: int,
    image_extensions: Set[str],
    video_extensions: Set[str],
) -> Tuple[str, Optional[str]]:
    """Render one cut + its entrance tween. Returns (html, tween or None)."""
    cut_id = f"cut-{index}"
    in_s = float(cut.get("in_seconds", 0) or 0)
    out_s = float(cut.get("out_seconds", 0) or 0)
    duration = max(0.1, out_s - in_s)

    source = cut.get("source") or ""
    cut_type = (cut.get("type") or "").lower()
    text = cut.get("text") or cut.get("title") or ""

    src_path = Path(source) if source else None
    ext = src_path.suffix.lower() if src_path else ""

    if cut_type in {"text_card", "hero_title", "callout"} or (not source and text):
        inner = f'<h1>{escape_text(text or f"Scene {index + 1}")}</h1>'
        subtitle = cut.get("subtitle") or cut.get("caption")
        if subtitle:
            inner += f'<div class="subtitle">{escape_text(subtitle)}</div>'
        html = (
            f'<div id="{cut_id}" class="clip text-card" '
            f'data-start="{format_float(in_s)}" data-duration="{format_float(duration)}" '
            f'data-track-index="1">{inner}</div>'
        )
        tween = (
            f'tl.from("#{cut_id} h1", {{ y: 40, opacity: 0, duration: 0.6, '
            f'ease: "power3.out" }}, {format_float(in_s + 0.1)});'
        )
        return html, tween

    if ext in image_extensions and src_path:
        rel = rel_from_workspace(str(src_path))
        html = (
            f'<img id="{cut_id}" class="clip image-clip" '
            f'src="{escape_attr(rel)}" '
            f'data-start="{format_float(in_s)}" data-duration="{format_float(duration)}" '
            f'data-track-index="1" alt="">'
        )
        tween = (
            f'tl.from("#{cut_id}", {{ scale: 1.05, opacity: 0, duration: 0.5, '
            f'ease: "power2.out" }}, {format_float(in_s)});'
        )
        return html, tween

    if ext in video_extensions and src_path:
        rel = rel_from_workspace(str(src_path))
        html = (
            f'<video id="{cut_id}" class="clip video-clip" '
            f'src="{escape_attr(rel)}" '
            f'data-start="{format_float(in_s)}" data-duration="{format_float(duration)}" '
            f'data-track-index="1" muted playsinline></video>'
        )
        return html, None

    if ext in {".html", ".htm"} and src_path:
        rel = rel_from_workspace(str(src_path))
        composition_id = Path(rel).stem
        html = (
            f'<div id="{cut_id}" class="clip composition-clip" '
            f'data-composition-id="{escape_attr(composition_id)}" '
            f'data-composition-src="{escape_attr(rel)}" '
            f'data-start="{format_float(in_s)}" data-duration="{format_float(duration)}" '
            f'data-width="{width}" data-height="{height}" '
            f'data-track-index="1"></div>'
        )
        return html, None

    placeholder = escape_text(text or cut.get("reason") or f"Scene {index + 1}")
    html = (
        f'<div id="{cut_id}" class="clip text-card" '
        f'data-start="{format_float(in_s)}" data-duration="{format_float(duration)}" '
        f'data-track-index="1"><h1>{placeholder}</h1></div>'
    )
    return html, None


def generate_index_html(
    cuts: list[dict[str, Any]],
    audio_refs: dict[str, Any],
    width: int,
    height: int,
    total_duration: float,
    css_vars: dict[str, str],
    title: str,
    image_extensions: Set[str],
    video_extensions: Set[str],
) -> str:
    """Emit a HyperFrames-contract-compliant index.html."""
    vars_css = "\n      ".join(f"{k}: {v};" for k, v in css_vars.items())

    clip_html: list[str] = []
    entrance_tweens: list[str] = []
    for i, cut in enumerate(cuts):
        html, tween = cut_to_html(i, cut, width, height, image_extensions, video_extensions)
        clip_html.append(html)
        if tween:
            entrance_tweens.append(tween)

    audio_html: list[str] = []
    for j, nar in enumerate(audio_refs.get("narration") or []):
        src = rel_from_workspace(nar["src"])
        start = nar.get("start_seconds", 0)
        end = nar.get("end_seconds")
        duration = (end - start) if end and end > start else (total_duration - start)
        audio_html.append(
            f'<audio id="nar-{j}" '
            f'data-start="{format_float(start)}" data-duration="{format_float(duration)}" '
            f'data-track-index="2" src="{escape_attr(src)}" '
            f'data-volume="1"></audio>'
        )

    music = audio_refs.get("music")
    if music:
        src = rel_from_workspace(music["src"])
        audio_html.append(
            f'<audio id="music" '
            f'data-start="0" data-duration="{format_float(total_duration)}" '
            f'data-track-index="3" src="{escape_attr(src)}" '
            f'data-volume="{format_float(music["volume"])}"></audio>'
        )

    tween_block = "\n        ".join(entrance_tweens) if entrance_tweens else "// no tweens"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape_text(title)}</title>
  <style>
    :root {{
      {vars_css}
    }}
    body {{ margin: 0; background: var(--color-bg); color: var(--color-fg); font-family: var(--font-body); }}
    [data-composition-id="root"] {{
      position: relative;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
    }}
    .clip {{ position: absolute; inset: 0; }}
    .clip.video-clip, .clip.image-clip {{ object-fit: cover; width: 100%; height: 100%; }}
    .clip.text-card {{ display: flex; align-items: center; justify-content: center; padding: 120px 160px; box-sizing: border-box; text-align: center; }}
    .clip.text-card h1 {{ font-family: var(--font-heading); font-weight: 700; font-size: 96px; line-height: 1.1; margin: 0; color: var(--color-fg); }}
    .clip.text-card .subtitle {{ font-size: 36px; margin-top: 24px; color: var(--color-accent); }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
</head>
<body>
  <div data-composition-id="root" data-start="0" data-duration="{format_float(total_duration)}" data-width="{width}" data-height="{height}">
    {"".join(clip_html)}
    {"".join(audio_html)}
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {tween_block}
      window.__timelines["root"] = tl;
    </script>
  </div>
</body>
</html>
"""
