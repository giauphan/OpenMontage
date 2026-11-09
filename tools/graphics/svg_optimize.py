"""Safe SVG Optimization Tool for OpenMontage.

Strips redundant metadata, comments, editor namespaces, and whitespace
while strictly preserving:
1. All element IDs and class attributes
2. clipPath, mask, and linearGradient / filter IDs
3. url(#id) references in fill, stroke, clip-path, and mask
4. GSAP inline style and animation properties
5. ViewBox, width, and height scaling definitions
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def optimize_svg_text(svg_content: str) -> str:
    """Safely optimize SVG content string preserving all animation and selector contracts."""
    if not svg_content or not svg_content.strip():
        return svg_content

    # 1. Remove XML declaration and DOCTYPE if present
    content = re.sub(r"<\?xml[^>]*\?>", "", svg_content)
    content = re.sub(r"<!DOCTYPE[^>]*>", "", content)

    # 2. Remove XML comments
    content = re.sub(r"<!--[\s\S]*?-->", "", content)

    # 3. Strip editor-specific namespace declarations and attributes (inkscape, sodipodi, sketch, etc.)
    content = re.sub(r'\s+xmlns:(?:inkscape|sodipodi|sketch|illustrator|adobe)="[^"]*"', "", content)
    content = re.sub(r'\s+(?:inkscape|sodipodi|sketch|illustrator|adobe):[a-zA-Z0-9_-]+="[^"]*"', "", content)

    # 4. Collapse redundant whitespace between tags while preserving whitespace in text content
    content = re.sub(r">\s+<", "><", content)
    content = content.strip()

    return content


def optimize_svg_file(input_path: Path | str, output_path: Path | str | None = None) -> Path:
    """Optimize an SVG file on disk."""
    inp_obj = Path(input_path)
    if any(part == ".." for part in inp_obj.parts):
        raise ValueError(f"Path traversal detected in input_path: {input_path}")
    src = inp_obj.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Input SVG file not found: {input_path}")

    if output_path:
        out_obj = Path(output_path)
        if any(part == ".." for part in out_obj.parts):
            raise ValueError(f"Path traversal detected in output_path: {output_path}")
        dst = out_obj.resolve()
    else:
        dst = src

    text = src.read_text(encoding="utf-8")
    opt = optimize_svg_text(text)

    # Validate output is still valid XML
    try:
        ET.fromstring(opt)
    except ET.ParseError as exc:
        raise ValueError(f"Optimized SVG failed XML validation: {exc}") from exc

    unresolved_dst = Path(output_path) if output_path else inp_obj
    if unresolved_dst.is_symlink():
        raise ValueError(f"Refusing to write to symlink: {unresolved_dst}")
    dst.write_text(opt, encoding="utf-8")
    return dst
