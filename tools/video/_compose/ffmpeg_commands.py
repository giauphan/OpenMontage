"""FFmpeg command construction, filter formatting, and subtitle styling helpers.

Pure functions for building FFmpeg filter strings and ASS styles.
"""

from __future__ import annotations

from typing import Any, Optional


def build_atempo(factor: float) -> str:
    """Build atempo filter chain for audio speed adjustment."""
    filters = []
    remaining = factor
    while remaining > 100.0:
        filters.append("atempo=100.0")
        remaining /= 100.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


def parse_probe_fps(fps_str: str) -> float:
    """Parse ffprobe fps string like '30/1' or '24000/1001'."""
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return round(int(num) / max(int(den), 1), 2)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return 0.0


def resolve_subtitle_style(
    explicit_style: dict | None,
    edit_decisions: dict | None,
    playbook: dict | None,
) -> dict:
    """Resolve subtitle style with layered priority.

    Priority: explicit_style > edit_decisions.subtitles.style > playbook > defaults.
    """
    resolved = {
        "font": "Inter",
        "font_size": 28,
        "bold": True,
        "outline_width": 2,
        "shadow": 0,
        "margin_v": 40,
        "alignment": 2,
    }

    # Layer 1: Playbook-derived style
    if playbook:
        typo = playbook.get("typography", {})
        colors = playbook.get("visual_language", {}).get("color_palette", {})
        if typo.get("body", {}).get("family"):
            resolved["font"] = typo["body"]["family"]
        if colors.get("text"):
            resolved["primary_color"] = colors["text"]
        if colors.get("background"):
            resolved["outline_color"] = colors["background"]
            bg = colors["background"]
            resolved["back_color"] = bg

    # Layer 2: edit_decisions subtitle style
    if edit_decisions:
        ed_style = edit_decisions.get("subtitles", {}).get("style", {})
        for k, v in ed_style.items():
            if v is not None:
                resolved[k] = v

    # Layer 3: Explicit override (highest priority)
    if explicit_style:
        for k, v in explicit_style.items():
            if v is not None:
                resolved[k] = v

    return resolved


def build_subtitle_style(style: dict) -> str:
    """Build ASS force_style string from style dict."""
    parts = []
    parts.append(f"FontName={style.get('font', 'Inter')}")
    parts.append(f"FontSize={style.get('font_size', 28)}")
    parts.append(f"Bold={1 if style.get('bold', True) else 0}")
    if style.get("primary_color"):
        parts.append(f"PrimaryColour={style['primary_color']}")
    if style.get("outline_color"):
        parts.append(f"OutlineColour={style['outline_color']}")
    if style.get("back_color"):
        parts.append(f"BackColour={style['back_color']}")
    border_style = style.get("border_style", 1)
    parts.append(f"BorderStyle={border_style}")
    parts.append(f"Outline={style.get('outline_width', 2)}")
    parts.append(f"Shadow={style.get('shadow', 0)}")
    parts.append(f"MarginV={style.get('margin_v', 40)}")
    parts.append(f"Alignment={style.get('alignment', 2)}")
    return ",".join(parts)
