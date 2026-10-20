"""T02: Verify template media and visual asset binding.

Baseline failure (RED):
1. templates/news/_schemas/base.schema.json rejects png/jpg/svg in media.
2. scripts/materialize_news_template.py generates fixed text cards and completely
   ignores content.get("media") or slot visual bindings in the emitted HTML.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from jsonschema import ValidationError
from scripts.materialize_news_template import (
    load_package_schema,
    validate_content,
    _build_explainer_html,
)

ROOT = Path(__file__).resolve().parents[2]


def test_t02_schema_accepts_raster_and_svg_images():
    """Template schemas must accept png/jpg/svg in media and per-slot visual blocks (R5)."""
    valid_content = {
        "template": "news-explainer",
        "template_version": "1.0.0",
        "variant": "full",
        "title": "Kiểm Tra Bản Mẫu",
        "duration": 45.0,
        "narration": "Nội dung tường thuật thử nghiệm mẫu.",
        "slots": {
            "hook": {"heading": "Mở đầu", "text": "Đoạn mở đầu giới thiệu", "start": 0, "end": 8},
            "capability": {
                "heading": "Tính năng",
                "text": "Giải thích tính năng mới",
                "label": "DemoNode v1.0",
                "visual": {
                    "kind": "svg_diagram",
                    "asset_id": "chip-diagram-1",
                    "src": "assets/visuals/chip_diagram.svg"
                },
                "start": 8,
                "end": 22
            },
            "steps": {"heading": "Cơ chế", "text": "Phân tích cơ chế", "start": 22, "end": 45},
        },
        "media": [
            {
                "src": "assets/chip_diagram.svg",
                "start": 8.0,
                "end": 22.0
            }
        ]
    }
    # Invariant: schema MUST accept SVG and raster images
    validate_content(valid_content, "news-explainer")


def test_t02_materializer_ignores_media_in_rendered_html():
    """Current materializer does not render <video> or <img> from content['media'] (R4)."""
    content = {
        "template": "news-explainer",
        "template_version": "1.0.0",
        "variant": "full",
        "title": "Kiểm Tra Bản Mẫu",
        "duration": 45.0,
        "narration": "Nội dung tường thuật thử nghiệm mẫu.",
        "slots": {
            "hook": {"heading": "Mở đầu", "text": "Đoạn mở đầu", "start": 0, "end": 8},
            "concept": {"heading": "Khái niệm", "text": "Giải thích", "start": 8, "end": 22},
            "mechanism": {"heading": "Cơ chế", "text": "Cơ chế", "start": 22, "end": 36},
            "takeaway": {"heading": "Kết luận", "text": "Kết luận", "start": 36, "end": 45},
        },
        "media": [
            {
                "src": "assets/clip_sample.mp4",
                "start": 8.0,
                "end": 22.0
            }
        ]
    }
    html = _build_explainer_html(content, "full")
    # Invariant: Materializer MUST render media into HTML elements
    assert "assets/clip_sample.mp4" in html, (
        "FAIL: materialize_news_template completely ignored content['media'] in emitted HTML."
    )


def test_t02_materializer_caption_docking_and_has_visual():
    """Verify that materialize_news_template pins captions to bottom 96px and applies has-visual."""
    content = {
        "template": "news-explainer",
        "template_version": "1.0.0",
        "variant": "short",
        "title": "Kiểm Tra Bản Mẫu",
        "duration": 40.0,
        "narration": "Nội dung tường thuật.",
        "narration_short": "Tường thuật ngắn.",
        "slots": {
            "hook": {
                "heading": "Mở đầu",
                "text": "Đoạn mở đầu",
                "start": 0,
                "end": 10,
                "visual": {
                    "kind": "illustration",
                    "src": "assets/visuals/demonode_device.svg",
                    "layout": "hero_center"
                }
            },
            "capability": {
                "heading": "Tính năng",
                "text": "Giải thích",
                "label": "DemoNode v1.0",
                "start": 10,
                "end": 25
            },
            "steps": {
                "heading": "Cơ chế",
                "text": "Cơ chế",
                "start": 25,
                "end": 40,
                "visual": {
                    "kind": "svg_diagram",
                    "src": "assets/visuals/local_vs_cloud.svg"
                }
            }
        }
    }
    html = _build_explainer_html(content, "short")

    # 1. Caption docking invariants
    assert "bottom:96px !important" in html, "Caption must be pinned to bottom 96px rail"
    assert "top:auto !important" in html, "Caption must override top to avoid center stretching"

    # 2. has-visual tagging invariants
    assert 'id="scene-hook" class="clip has-visual"' in html, "scene-hook with visual must have has-visual class"
    assert 'id="scene-capability" class="clip"' in html, "scene-capability without visual must NOT have has-visual class"
    assert 'id="scene-steps" class="clip has-visual"' in html, "scene-steps with visual must have has-visual class"

    # 3. Visual layout CSS presence
    assert ".has-visual .scene-inner" in html
    assert ".has-visual .title" in html
    assert ".has-visual .scene-text" in html


def test_t02_svg_visual_assets_valid_xml_and_text_boundaries():
    """Verify that staged SVG assets in assets/visuals are well-formed XML and fit bounds."""
    import xml.etree.ElementTree as ET

    visuals_dir = ROOT / "assets" / "visuals"
    assert visuals_dir.is_dir(), "assets/visuals directory must exist"

    svg_files = list(visuals_dir.glob("*.svg"))
    assert len(svg_files) >= 3, f"Expected at least 3 SVG visual assets, found {len(svg_files)}"

    for svg_p in svg_files:
        tree = ET.parse(svg_p)
        root = tree.getroot()
        assert root.tag.endswith("svg"), f"{svg_p.name} root tag must be svg"
        viewbox = root.get("viewBox", "")
        assert viewbox, f"{svg_p.name} must specify viewBox"

        # Check text lengths inside specific bounded containers to prevent text overflow
        for text_el in root.iter():
            if text_el.tag.endswith("text") and text_el.text:
                text_content = text_el.text.strip()
                # Text inside small sub-boxes should not exceed 55 characters on a single line
                font_size = float(text_el.get("font-size", 16))
                if font_size <= 14:
                    assert len(text_content) <= 55, (
                        f"Text '{text_content}' in {svg_p.name} exceeds 55 chars ({len(text_content)} chars), "
                        f"risking box overflow"
                    )

