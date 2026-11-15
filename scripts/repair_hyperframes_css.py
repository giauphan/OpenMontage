#!/usr/bin/env python3
"""CSS and typography enhancement helpers for HyperFrames compositions."""

from __future__ import annotations

import os
import re
from pathlib import Path

TAG_HEAD_OPEN = "<head>"
TAG_HEAD_CLOSE = "</head>"
TAG_STYLE_OPEN = "<style>"
STYLE_CLOSE_TAG = "</style>"
TAG_STYLE_CLOSE = STYLE_CLOSE_TAG

FONT_CSS = """@font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Regular.ttf') format('truetype'); font-weight: 400; font-style: normal; font-display: block; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Bold.ttf') format('truetype'); font-weight: 700; font-style: normal; font-display: block; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-ExtraBold.ttf') format('truetype'); font-weight: 800; font-style: normal; font-display: block; }"""


def _ensure_font_face_declaration(html: str) -> str:
    if "font-family: 'BeVietnamPro'" in html:
        return html
    if TAG_STYLE_OPEN not in html:
        if TAG_HEAD_CLOSE in html:
            html = html.replace(TAG_HEAD_CLOSE, f"  {TAG_STYLE_OPEN}\n  {STYLE_CLOSE_TAG}\n{TAG_HEAD_CLOSE}", 1)
        elif TAG_HEAD_OPEN in html:
            html = html.replace(TAG_HEAD_OPEN, f"{TAG_HEAD_OPEN}\n  {TAG_STYLE_OPEN}\n  {STYLE_CLOSE_TAG}", 1)
        else:
            html = f"{TAG_STYLE_OPEN}{STYLE_CLOSE_TAG}\n" + html
    return html.replace(TAG_STYLE_OPEN, f"{TAG_STYLE_OPEN}\n    " + FONT_CSS, 1)


def _ensure_font_css_variables(html: str, path: Path) -> str:
    html = re.sub(r"--font-heading:[^;]+;", "--font-heading: 'BeVietnamPro', Arial, sans-serif;", html)
    html = re.sub(r"--font-body:[^;]+;", "--font-body: 'BeVietnamPro', Arial, sans-serif;", html)
    if "--font-heading:" in html and "--font-body:" in html:
        return html

    root_match = re.search(r":root\s*\{([^{}]*)\}", html)
    if root_match:
        decl = root_match.group(1)
        if "--font-heading:" not in decl:
            decl += " --font-heading: 'BeVietnamPro', Arial, sans-serif;"
        if "--font-body:" not in decl:
            decl += " --font-body: 'BeVietnamPro', Arial, sans-serif;"
        return html[:root_match.start(1)] + decl + html[root_match.end(1):]
    if STYLE_CLOSE_TAG in html:
        return html.replace(
            STYLE_CLOSE_TAG,
            f":root {{ --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }}\n{STYLE_CLOSE_TAG}",
            1,
        )
    raise ValueError(f"{path}: missing style element for font bindings")


_EXCLUDED_TOKENS = frozenset({"badge", "tag", "pill", "kicker", "source", "credit", "caption", "om-asr"})


def _is_excluded_selector(sel_low: str) -> bool:
    for token in re.findall(r"[a-z0-9-]+", sel_low):
        if token in _EXCLUDED_TOKENS or token.rsplit("-", 1)[-1] in _EXCLUDED_TOKENS:
            return True
    return False


class _ExcludeSelectorMatcher:
    @staticmethod
    def search(sel_low: str) -> bool:
        return _is_excluded_selector(sel_low)


_EXCLUDE_SELECTOR_RE = _ExcludeSelectorMatcher()
_H1_SELECTOR_RE = re.compile(r"(?<![\w-])(?:h1|headline|title-large)(?![\w-])")
_H2_SELECTOR_RE = re.compile(r"(?<![\w-])(?:h2|subheadline|section-header)(?![\w-])")
_H3_SELECTOR_RE = re.compile(r"(?<![\w-])(?:card-title|h3)(?![\w-])")
_METRIC_SELECTOR_RE = re.compile(r"(?<![\w-])(?:metric-value|metric)(?![\w-])")


def _bump_font_px(px: float, sel_low: str, fallback_match: str) -> str:
    if _H1_SELECTOR_RE.search(sel_low):
        return f"font-size: {max(int(px), 50)}px"
    if _H2_SELECTOR_RE.search(sel_low):
        return f"font-size: {max(int(px), 38)}px"
    if _H3_SELECTOR_RE.search(sel_low):
        return f"font-size: {max(int(px), 32)}px"
    if _METRIC_SELECTOR_RE.search(sel_low):
        if "label" not in sel_low:
            return f"font-size: {max(int(px), 54)}px"
        if px < 28:
            return "font-size: 28px"
        return fallback_match
    if px < 28:
        return "font-size: 28px"
    return fallback_match


def _fix_css_rule(rule_m: re.Match) -> str:
    selector, body = rule_m.group(1), rule_m.group(2)
    sel_low = selector.lower()
    if _is_excluded_selector(sel_low):
        return rule_m.group(0)
    new_body = re.sub(r"font-size\s*:\s*([\d.]+)px", lambda fm: _bump_font_px(float(fm.group(1)), sel_low, fm.group(0)), body)
    if "scene-content" in sel_low:
        new_body = re.sub(r"overflow\s*:\s*hidden", "overflow: visible", new_body)
    return f"{selector}{{{new_body}}}"


def _upscale_css_block(style_m: re.Match) -> str:
    return re.sub(r"([^\r\n{}@]+)\{([^{}]+)\}", _fix_css_rule, style_m.group(0))


def _bump_svg_font(m: re.Match) -> str:
    val = int(m.group(1))
    return f'font-size="{max(18, val + 6)}"' if val < 18 else m.group(0)


def _normalize_mobile_readable_css(html: str) -> str:
    """Upscale tiny desktop CSS font-sizes (< 26px) in scene/card/flow rules and SVG text."""
    html = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", _upscale_css_block, html, flags=re.IGNORECASE)
    return re.sub(r'\bfont-size=["\'](\d+)["\']', _bump_svg_font, html)


def _build_visual_enhancement_css(html: str) -> str:
    visual_mode = os.environ.get("NEWS_VISUAL_MODE", "0") in ("1", "true", "True")
    if visual_mode:
        legacy_scene = (
            ".scene {\n    display: flex;\n    flex-direction: column;\n    justify-content: center;\n"
            "    align-items: center;\n    padding: 80px 48px 300px 48px;\n    box-sizing: border-box;\n}"
        )
        has_authored_scene_rule = bool(re.search(r"(?<![-\w])\.scene\s*\{", html))
        scene_css = ".scene {\n    box-sizing: border-box;\n}" if has_authored_scene_rule else legacy_scene
        return f"""
/* Visual Quality Enhancement (Context-Aware Visual Mode) */
#stage {{ font-family: 'BeVietnamPro', sans-serif; }}
{scene_css}
.scene-content {{ overflow: visible !important; padding-left: 12px; padding-right: 12px; box-sizing: border-box; }}
.scene img, .scene video, .scene .svg-container svg, .scene .diagram svg, .scene-media {{ max-width: 100%; max-height: 520px; height: auto; object-fit: contain; z-index: 1; }}
.card-title svg, .badge svg, .icon svg, svg[width="26"], svg[width="28"] {{ width: 28px !important; height: 28px !important; min-width: 28px !important; min-height: 28px !important; max-width: 28px !important; max-height: 28px !important; flex-shrink: 0 !important; display: inline-block !important; }}
.card-default {{ background: rgba(30, 41, 59, 0.82); border: 1px solid rgba(56, 189, 248, 0.4); border-radius: 28px; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px rgba(56, 189, 248, 0.18); backdrop-filter: blur(14px); box-sizing: border-box; width: 960px; max-width: 90vw; margin: 16px auto; padding: 32px 40px; }}
.scene .stage-card, .stage-card, [class*="stage-card"] {{ border-radius: 24px !important; box-sizing: border-box !important; }}
h1, h2, h3, h4, .title, .title-large, .section-header, .headline, [class*="title"], [class*="header"] {{ color: #ffffff; font-weight: 800; text-shadow: 0 4px 20px rgba(0, 0, 0, 0.9); }}
p, .body-text, .description, .subtitle, .footer-text, [class*="text"]:not([class*="highlight"]) {{ color: #f8fafc; font-weight: 500; text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8); }}
.brand-name, .badge, .category, .tag, [class*="badge"]:not([class*="card"]), [class~="tag"], [class*="-tag"]:not([class*="card"]), [class*="tag-pill"] {{ color: #38bdf8; background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(56, 189, 248, 0.5); border-radius: 9999px; padding: 8px 24px; box-shadow: 0 0 15px rgba(56, 189, 248, 0.25); }}
.highlight-text, .accent, [class*="highlight"], [class*="accent"], [class*="metric"], [class*="stat"] {{ color: #38bdf8; font-weight: 700; text-shadow: 0 0 20px rgba(56, 189, 248, 0.4); }}
{STYLE_CLOSE_TAG}"""

    return f"""
/* Visual Quality Enhancement */
#stage {{ background: radial-gradient(circle at 50% 25%, #1e1b4b 0%, #0f172a 70%, #030712 100%); font-family: 'BeVietnamPro', sans-serif !important; }}
.scene:not([class*="scene-"]):not([style*="background"]) {{ background: transparent; }}
.scene {{ display: flex !important; flex-direction: column !important; justify-content: center !important; align-items: center !important; padding: 80px 48px 300px 48px !important; box-sizing: border-box !important; }}
.scene-content {{ overflow: visible !important; padding-left: 12px !important; padding-right: 12px !important; box-sizing: border-box !important; }}
.scene > div:not(.om-asr-caption):not([class*="diagram"]):not([class*="visual"]), .card, .container, [class*="card"], [class*="container"], [class*="box"], [class*="plate"] {{ background: rgba(30, 41, 59, 0.82) !important; border: 1px solid rgba(56, 189, 248, 0.4) !important; border-radius: 28px !important; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px rgba(56, 189, 248, 0.18) !important; backdrop-filter: blur(14px) !important; box-sizing: border-box !important; width: 960px !important; max-width: 90vw !important; margin: 16px auto !important; padding: 32px 40px !important; }}
.scene .stage-card, .stage-card, [class*="stage-card"] {{ border-radius: 24px !important; box-sizing: border-box !important; }}
h1, h2, h3, h4, .title, .title-large, .section-header, .headline, [class*="title"], [class*="header"] {{ color: #ffffff !important; font-weight: 800 !important; text-shadow: 0 4px 20px rgba(0, 0, 0, 0.9) !important; }}
p, .body-text, .description, .subtitle, .footer-text, [class*="text"]:not([class*="highlight"]) {{ color: #f8fafc !important; font-weight: 500 !important; text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8) !important; }}
.brand-name, .badge, .category, .tag, [class*="badge"]:not([class*="card"]), [class~="tag"], [class*="-tag"]:not([class*="card"]), [class*="tag-pill"] {{ color: #38bdf8 !important; background: rgba(15, 23, 42, 0.85) !important; border: 1px solid rgba(56, 189, 248, 0.5) !important; border-radius: 9999px !important; padding: 8px 24px !important; box-shadow: 0 0 15px rgba(56, 189, 248, 0.25) !important; }}
.highlight-text, .accent, [class*="highlight"], [class*="accent"], [class*="metric"], [class*="stat"] {{ color: #38bdf8 !important; font-weight: 700 !important; text-shadow: 0 0 20px rgba(56, 189, 248, 0.4) !important; }}
{STYLE_CLOSE_TAG}"""


def _patch_typography_and_css(html: str, path: Path) -> str:
    html = _ensure_font_face_declaration(html)
    html = _ensure_font_css_variables(html, path)
    html = _normalize_mobile_readable_css(html)

    if "overflow-wrap: break-word" not in html:
        html = html.replace(
            STYLE_CLOSE_TAG,
            f"\n/* Enforce text wrapping */\nh1, h2, h3, h4, h5, h6, p, span, .caption, .title, .text, .highlight, .accent, [class*='caption'], [class*='text'] {{ overflow-wrap: break-word !important; word-wrap: break-word !important; word-break: break-word !important; max-width: 100%; box-sizing: border-box; }}\n{STYLE_CLOSE_TAG}",
            1,
        )

    legacy_scene = (
        ".scene {\n    display: flex;\n    flex-direction: column;\n    justify-content: center;\n"
        "    align-items: center;\n    padding: 80px 48px 300px 48px;\n    box-sizing: border-box;\n}"
    )
    if legacy_scene in html and len(re.findall(r"(?<![-\w])\.scene\s*\{", html)) > 1:
        html = html.replace(legacy_scene, ".scene {\n    box-sizing: border-box;\n}")

    if "/* Visual Quality Enhancement" in html:
        enhancement_css = _build_visual_enhancement_css(html).replace(STYLE_CLOSE_TAG, "").strip()
        html = re.sub(
            r"/\* Visual Quality Enhancement[^*]*\*/[\s\S]*?(?=\s*</style>)",
            enhancement_css,
            html,
            count=1,
        )
    elif STYLE_CLOSE_TAG in html:
        html = html.replace(STYLE_CLOSE_TAG, _build_visual_enhancement_css(html), 1)

    return html
