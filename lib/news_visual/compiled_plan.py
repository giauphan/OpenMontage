"""Compile news_visual_plan into HyperFrames DOM elements and GSAP timelines."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from lib.news_visual.scene_layouts import render_scene_visual_html, visual_layout_css


def compile_visual_plan_to_dom(
    visual_plan: Dict[str, Any],
    assets_manifest: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str]:
    """Compile visual beats into HTML clips, CSS rules, and GSAP timeline steps."""
    html_clips: List[str] = []
    tl_tweens: List[str] = []

    asset_map = {}
    if assets_manifest:
        for a in assets_manifest.get("assets", []):
            asset_map[a.get("asset_id")] = a

    for beat in visual_plan.get("beats", []):
        beat_id = beat.get("id", "vb")
        sec_id = beat.get("script_section_id", "scene")
        start = float(beat.get("start_seconds", 0.0))
        end = float(beat.get("end_seconds", start + 5.0))
        dur = max(0.5, end - start)
        asset_ids = beat.get("asset_ids", [])

        primary_src = None
        for aid in asset_ids:
            if aid in asset_map:
                primary_src = asset_map[aid].get("file")
                break
        if not primary_src and asset_ids:
            primary_src = f"assets/visuals/{asset_ids[0]}.svg"

        if primary_src:
            visual_spec = {
                "src": primary_src,
                "layout": beat.get("layout", "hero_center"),
                "kind": beat.get("visual_kind", "svg_diagram"),
                "source_label": beat.get("source_label"),
            }
            clip_html = render_scene_visual_html(sec_id, visual_spec, start, dur)
            html_clips.append(clip_html)
            dom_id = f"visual-{sec_id}"
            motion = beat.get("motion_preset", "node_flow_reveal")
            if motion == "fade_in_scale":
                tl_tweens.append(
                    f"      tl.from('#{dom_id} .visual-media-wrapper', {{ opacity: 0, scale: 0.9, duration: 0.6, ease: 'back.out(1.2)' }}, {start:.2f});"
                )
            else:
                tl_tweens.append(
                    f"      tl.from('#{dom_id} .visual-media-wrapper', {{ opacity: 0, y: 30, duration: 0.6, ease: 'power2.out' }}, {start:.2f});"
                )

    css = visual_layout_css()
    return "\n".join(html_clips), "\n".join(tl_tweens), css
