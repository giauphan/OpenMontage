"""HTML and CSS generators for news visual layouts."""

from __future__ import annotations

import html as html_mod
from typing import Any, Dict, Optional


def esc(text: Any) -> str:
    return html_mod.escape(str(text), quote=True)


def render_scene_visual_html(
    slot_id: str,
    visual_spec: Dict[str, Any],
    start_time: float,
    duration: float,
    track_index: int = 2,
) -> str:
    """Render a visual element (<img>, <video>, or SVG diagram) for a scene slot."""
    src = visual_spec.get("src") or visual_spec.get("file")
    if not src:
        asset_id = visual_spec.get("asset_id")
        if asset_id:
            src = f"assets/visuals/{asset_id}.svg"
        else:
            return ""

    layout = visual_spec.get("layout", "hero_center")
    kind = visual_spec.get("kind", "svg_diagram")
    source_label = visual_spec.get("source_label")

    dom_id = f"visual-{slot_id}"
    label_html = ""
    if source_label:
        label_html = f'<div class="visual-source-label">Nguồn: {esc(source_label)}</div>'

    media_element = ""
    if src.endswith((".mp4", ".webm")):
        media_element = (
            f'<video class="visual-media" src="{esc(src)}" autoplay loop muted playsinline '
            f'data-start="{start_time:.2f}" data-duration="{duration:.2f}"></video>'
        )
    else:
        media_element = f'<img class="visual-media" src="{esc(src)}" alt="Visual for {esc(slot_id)}" />'

    return (
        f'    <div id="{dom_id}" class="scene-visual-container layout-{esc(layout)} clip" '
        f'data-start="{start_time:.2f}" data-duration="{duration:.2f}" data-track-index="{track_index}">\n'
        f'      <div class="visual-media-wrapper">\n'
        f'        {media_element}\n'
        f'        {label_html}\n'
        f'      </div>\n'
        f'    </div>'
    )


def visual_layout_css() -> str:
    """CSS styling for visual layout containers, ensuring proper framing and caption safe zone."""
    return """
/* Context-Aware Visual Layouts */
.scene-visual-container {
    position: absolute;
    inset: 0;
    display: flex;
    justify-content: center;
    align-items: center;
    pointer-events: none;
    padding-top: 180px;
    padding-bottom: 240px; /* Preserve caption safe zone */
    box-sizing: border-box;
    z-index: 1;
}
.layout-diagram_left_copy_right {
    justify-content: flex-start;
    padding-left: 60px;
}
.layout-hero_center {
    justify-content: center;
}
.visual-media-wrapper {
    position: relative;
    max-width: 960px;
    max-height: 800px;
    display: flex;
    flex-direction: column;
    align-items: center;
    border-radius: 20px;
    overflow: hidden;
    box-shadow: 0 16px 40px rgba(0,0,0,0.6);
}
.visual-media {
    max-width: 100%;
    max-height: 750px;
    object-fit: contain;
    border-radius: 16px;
}
.visual-source-label {
    font-size: 18px;
    color: #94a3b8;
    background: rgba(15, 23, 42, 0.85);
    padding: 4px 14px;
    border-radius: 6px;
    margin-top: 8px;
    font-family: 'BeVietnamPro', sans-serif;
}
.has-visual .scene-inner {
    justify-content: flex-start !important;
    padding-top: 120px !important;
    padding-bottom: 240px !important;
}
.has-visual .title {
    font-size: 42px !important;
    margin-bottom: 20px !important;
    max-width: 960px !important;
}
.has-visual .scene-text {
    position: absolute !important;
    bottom: 230px !important;
    font-size: 26px !important;
    max-width: 860px !important;
    background: rgba(10, 20, 16, 0.88);
    padding: 12px 24px;
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.12);
}
.has-visual .capability-card, .has-visual .limitation-box, .has-visual .metric-card {
    position: absolute !important;
    bottom: 230px !important;
    max-width: 860px !important;
}
"""
