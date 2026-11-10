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

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _validate_safe_svg_path(raw_path: Path | str, *, param_name: str) -> Path:
    raw = str(raw_path)
    p_obj = Path(raw)
    if not raw or "\x00" in raw or any(part == ".." for part in p_obj.parts):
        raise ValueError(f"Path traversal detected in {param_name}: {raw_path}")
    if p_obj.is_symlink():
        raise ValueError(f"Refusing to access symlink in {param_name}: {raw_path}")
    abs_p = Path(os.path.realpath(raw))
    allowed_roots = (
        Path(os.path.realpath(str(Path(__file__).resolve().parents[2]))),
        Path(os.path.realpath(str(Path.home()))),
        Path(os.path.realpath(str(Path.cwd()))),
        Path(os.path.realpath(tempfile.gettempdir())),
    )
    if not any(
        abs_p.is_relative_to(root) and os.path.commonpath([str(abs_p), str(root)]) == str(root)
        for root in allowed_roots
    ):
        raise ValueError(f"Path traversal detected in {param_name}: {raw_path}")
    return abs_p


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
    src = _validate_safe_svg_path(input_path, param_name="input_path")
    if not src.is_file():
        raise FileNotFoundError(f"Input SVG file not found: {input_path}")

    if output_path is not None:
        dst = _validate_safe_svg_path(output_path, param_name="output_path")
    else:
        dst = src

    with open(src, "r", encoding="utf-8") as in_fh:
        text = in_fh.read()
    opt = optimize_svg_text(text)

    # Validate output is still valid XML
    try:
        ET.fromstring(opt)
    except ET.ParseError as exc:
        raise ValueError(f"Optimized SVG failed XML validation: {exc}") from exc

    with open(dst, "w", encoding="utf-8") as out_fh:
        out_fh.write(opt)
    return dst
