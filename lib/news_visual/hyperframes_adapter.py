"""HyperFrames composition adapter for rendering contextual visual assets."""

from __future__ import annotations

import html as html_mod
from typing import Any, Dict, List, Tuple
from lib.news_visual.scene_layouts import render_scene_visual_html, visual_layout_css


def esc(text: Any) -> str:
    return html_mod.escape(str(text), quote=True)


def build_media_layer_elements(media_list: List[Dict[str, Any]], total_duration: float) -> Tuple[str, str, str]:
    """Build HTML, CSS, and GSAP timeline code for top-level media array entries."""
    html_clips: List[str] = []
    tl_tweens: List[str] = []

    for i, m in enumerate(media_list):
        src = m.get("src", "")
        start = float(m.get("start", 0.0))
        end = float(m.get("end", total_duration))
        dur = max(0.5, end - start)
        dom_id = f"media-clip-{i}"

        if src.endswith((".mp4", ".webm")):
            vol = float(m.get("volume", 0.0))
            html_clips.append(
                f'    <video id="{dom_id}" class="media-clip clip" src="{esc(src)}" '
                f'autoplay loop muted playsinline data-start="{start:.2f}" data-duration="{dur:.2f}" '
                f'data-track-index="1" data-volume="{vol}"></video>'
            )
        else:
            html_clips.append(
                f'    <div id="{dom_id}" class="media-clip clip" data-start="{start:.2f}" '
                f'data-duration="{dur:.2f}" data-track-index="1">\n'
                f'      <img class="media-img" src="{esc(src)}" alt="Media clip {i}" />\n'
                f'    </div>'
            )

        tl_tweens.append(
            f"      tl.from('#{dom_id}', {{ opacity: 0, duration: 0.5, ease: 'power2.out' }}, {start:.2f});"
        )

    css = """
.media-clip {
    position: absolute;
    inset: 0;
    display: flex;
    justify-content: center;
    align-items: center;
    pointer-events: none;
    z-index: 1;
}
.media-img {
    max-width: 90%;
    max-height: 80%;
    object-fit: contain;
    border-radius: 20px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}
"""
    return "\n".join(html_clips), "\n".join(tl_tweens), css
