#!/usr/bin/env python3
"""Repair and validate HyperFrames assets before rendering."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
from html.parser import HTMLParser
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.narration_text import _FORBIDDEN_PATTERN as _MALFORMED_TEXT_PATTERN
from scripts.repair_hyperframes_gsap import repair_gsap_timeline

NARRATION_TAG = (
    '<audio id="narration" src="assets/narration.mp3" '
    'data-start="0" data-track-index="10" data-volume="1"></audio>'
)

TAG_HEAD_OPEN = "<head>"
TAG_HEAD_CLOSE = "</head>"
TAG_STYLE_OPEN = "<style>"
STYLE_CLOSE_TAG = "</style>"
TAG_STYLE_CLOSE = STYLE_CLOSE_TAG
TAG_AUDIO_OPEN = "<audio"
MUSIC_BG_MP3 = "music-bg.mp3"
NARRATION_REELS_MP3 = "narration_reels.mp3"

FONT_CSS = """@font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Regular.ttf') format('truetype'); font-weight: 400; font-style: normal; font-display: block; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Bold.ttf') format('truetype'); font-weight: 700; font-style: normal; font-display: block; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-ExtraBold.ttf') format('truetype'); font-weight: 800; font-style: normal; font-display: block; }"""

REQUIRED_FONTS = (
    "BeVietnamPro-Regular.ttf",
    "BeVietnamPro-Bold.ttf",
    "BeVietnamPro-ExtraBold.ttf",
)

VIETNAMESE_GLYPH_SENTINELS = "ĐđĂăÂâÊêÔôƠơƯưÁáÀàẢảÃãẠạẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẾếỀềỂểỄễỆệỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỨứỪừỬửỮữỰựÝýỲỳỶỷỸỹỴỵ"

PORTRAIT_WIDTH = 1080
PORTRAIT_HEIGHT = 1920

_VI_TRAILING_WORDS = frozenset((
    "xuống", "lên", "vào", "ra", "của", "và", "là", "khi",
    "được", "cho", "với", "tại", "từ", "về", "đến", "trong",
    "ngoài", "bởi", "như", "do",
))


def _check_local_reference_symlinks(
    candidate_path: Path, composition_dir: Path, path: Path, kind: str, reference: str
) -> None:
    current = composition_dir
    for part in candidate_path.parts:
        if part in ("", "."):
            continue
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{path}: {kind} asset reference traverses a symbolic link: {reference!r}")


def _is_ignorable_reference(raw_reference: str, kind: str, path: Path) -> tuple[bool, str, str]:
    raw_reference = raw_reference.strip()
    decoded = html_lib.unescape(raw_reference)
    if kind == "CSS URL" and decoded != raw_reference:
        raise ValueError(
            f"{path}: HTML-entity-encoded CSS URL is ambiguous; use a percent-encoded path instead: {raw_reference!r}"
        )
    if not decoded or decoded.startswith("#"):
        return True, "", ""
    if decoded.lower().startswith("data:") or re.match(r"^(?:https?:)?//", decoded, re.IGNORECASE):
        return True, "", ""
    clean = unquote(decoded.split("?", 1)[0].split("#", 1)[0])
    if not clean or clean in (".", "./", "/"):
        return True, "", ""
    return False, decoded, clean


def _validate_local_reference(raw_reference: str, kind: str, path: Path, composition_dir: Path) -> None:
    should_ignore, reference, clean_reference = _is_ignorable_reference(raw_reference, kind, path)
    if should_ignore:
        return

    candidate_path = Path(clean_reference)
    windows_path = PureWindowsPath(clean_reference)
    if candidate_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError(f"{path}: {kind} asset reference must be relative to the composition: {reference!r}")
    scheme_match = re.match(r"^([a-z][a-z0-9+.-]*):", clean_reference, re.IGNORECASE)
    if scheme_match:
        raise ValueError(
            f"{path}: unsupported {kind} asset URL scheme {scheme_match.group(1)!r}: {reference!r}"
        )

    _check_local_reference_symlinks(candidate_path, composition_dir, path, kind, reference)

    target = (composition_dir / candidate_path).resolve()
    try:
        target.relative_to(composition_dir)
    except ValueError as exc:
        raise ValueError(f"{path}: {kind} asset reference escapes the composition directory: {reference!r}") from exc
    if target == composition_dir or target.is_dir():
        return
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError(
            f"{path}: missing or empty local {kind} asset {reference!r}; "
            "provide the intended file within this composition's directory"
        )


def repair_missing_composition_assets(path: Path, html: str) -> str:
    """Reject unresolved local media references without mutating project assets."""
    composition_dir = path.parent.resolve()

    for match in re.finditer(r'<img\b[^>]*\bsrc=["\']([^"\']*)["\'][^>]*>', html, flags=re.IGNORECASE):
        _validate_local_reference(match.group(1), "image", path, composition_dir)

    for match in re.finditer(r'url\((["\']?)([^"\'\)]+)\1\)', html, flags=re.IGNORECASE):
        _validate_local_reference(match.group(2), "CSS URL", path, composition_dir)

    return html


def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def _patch_locale_viewport(
    html: str, path: Path, locale: str, is_landscape: bool, default_width: int, default_height: int
) -> str:
    if locale != "en-US" or path.parent.name not in ("hyperframes", "hyperframes_reels"):
        return html
    wrong_w, wrong_h = (1080, 1920) if is_landscape else (1920, 1080)

    def _fix_viewport(m: re.Match) -> str:
        tag = m.group(0)
        tag = re.sub(rf"\bwidth\s*=\s*{wrong_w}\b", f"width={default_width}", tag)
        tag = re.sub(rf"\bheight\s*=\s*{wrong_h}\b", f"height={default_height}", tag)
        return tag

    html = re.sub(r"<meta\b[^>]*\bname=[\"']viewport[\"'][^>]*>", _fix_viewport, html, flags=re.I)

    def _fix_css_rule(m: re.Match) -> str:
        full = m.group(0)
        body = m.group(1)
        if re.search(rf"(?<![-\w])width\s*:\s*{wrong_w}px", body) and re.search(rf"(?<![-\w])height\s*:\s*{wrong_h}px", body):
            new_body = re.sub(rf"(?<![-\w])width\s*:\s*{wrong_w}px", f"width: {default_width}px", body)
            new_body = re.sub(rf"(?<![-\w])height\s*:\s*{wrong_h}px", f"height: {default_height}px", new_body)
            return full[: m.start(1) - m.start(0)] + new_body + "}"
        return full

    return re.sub(r"(?:#root|#stage|body|html)\b[^{}]*\{([^{}]*)\}", _fix_css_rule, html)


def _extract_tag_end_time(tag: str) -> float:
    s_m = re.search(r'\bdata-start=["\']([0-9.]+)["\']', tag)
    d_m = re.search(r'\bdata-duration=["\']([0-9.]+)["\']', tag)
    if s_m and d_m:
        return float(s_m.group(1)) + float(d_m.group(1))
    e_m = re.search(r'\bdata-end=["\']([0-9.]+)["\']', tag)
    if e_m:
        return float(e_m.group(1))
    return 0.0


def _calculate_scenes_max_end(html: str) -> float:
    max_end = 0.0
    for match in re.finditer(r'<[a-zA-Z]+\b[^>]*\bclass=["\'][^"\']*\bscene\b[^"\']*["\'][^>]*>', html):
        max_end = max(max_end, _extract_tag_end_time(match.group(0)))
    if max_end > 0.0:
        return max_end
    for match in re.finditer(r'<[a-zA-Z]+\b(?!data-composition-id)[^>]*>', html):
        tag = match.group(0)
        if "data-composition-id" not in tag:
            max_end = max(max_end, _extract_tag_end_time(tag))
    return max_end


def _skip_attribute_value(text: str, val_start: int, n: int) -> int:
    if val_start < n and text[val_start] in ('"', "'"):
        val_end = text.find(text[val_start], val_start + 1)
        return n if val_end == -1 else val_end + 1
    end = val_start
    while end < n and text[end] not in " \t\r\n>":
        end += 1
    return end


def _strip_composition_id(text: str) -> str:
    target = "data-composition-id="
    if target not in text:
        return text
    result, idx, n = [], 0, len(text)
    while idx < n:
        pos = text.find(target, idx)
        if pos == -1:
            result.append(text[idx:])
            break
        start = pos
        while start > idx and text[start - 1] in " \t\r\n":
            start -= 1
        result.append(text[idx:start])
        idx = _skip_attribute_value(text, pos + len(target), n)
    return "".join(result)


def _wrap_scenes_with_stage(
    html: str,
    scene_match: re.Match,
    max_end: float,
    narration_duration: float,
    default_width: int,
    default_height: int,
) -> tuple[str, re.Match | None]:
    start_pos = scene_match.start()
    body_close = re.search(r"</body>", html[start_pos:], flags=re.IGNORECASE)
    script_match = re.search(r"<script\b", html[start_pos:], flags=re.IGNORECASE)
    if script_match:
        end_pos = start_pos + script_match.start()
    elif body_close:
        end_pos = start_pos + body_close.start()
    else:
        end_pos = len(html)
    initial_dur = max_end if max_end > 0 else narration_duration
    stage_tag = (
        f'<div id="stage" class="composition" data-composition-id="main" '
        f'data-start="0" data-duration="{initial_dur:.3f}" data-width="{default_width}" data-height="{default_height}">'
    )
    inner_scenes = _strip_composition_id(html[start_pos:end_pos])
    html = html[:start_pos] + stage_tag + "\n" + inner_scenes + "\n</div>\n" + html[end_pos:]
    root_open = re.compile(r"<div\b[^>]*>").match(html, start_pos)
    if "#stage" not in html and TAG_STYLE_OPEN in html:
        stage_css = (
            f"\n        #stage {{ position: relative; width: {default_width}px; height: {default_height}px; "
            f"overflow: hidden; background: radial-gradient(circle at 50% 25%, #1e1b4b 0%, #0f172a 70%, #030712 100%); "
            f"font-family: 'BeVietnamPro', sans-serif; }}\n"
        )
        html = html.replace(TAG_STYLE_OPEN, TAG_STYLE_OPEN + stage_css, 1)
    return html, root_open


def _find_or_create_root_element(
    html: str, max_end: float, narration_duration: float, default_width: int, default_height: int
) -> tuple[str, re.Match | None]:
    root_open = re.search(
        r"<(?!body\b)[a-zA-Z0-9]+\b(?![^>]*\bclass=[\"'][^\"']*\bscene\b)"
        r"(?=[^>]*(?:\bdata-composition-id=|id=[\"'](?:main|stage|composition|root)[\"']|"
        r"class=[\"'][^\"']*\b(?:composition|frame|stage)\b[^\"']*[\"']))[^>]*>",
        html,
    )
    if root_open:
        return html, root_open
    root_open = re.search(r"<main\b[^>]*>", html)
    if root_open:
        return html, root_open
    scene_match = re.search(r"<(?:div|section)\b[^>]*\bclass=[\"'][^\"']*\bscene\b[^\"']*[\"'][^>]*>", html)
    if scene_match:
        return _wrap_scenes_with_stage(html, scene_match, max_end, narration_duration, default_width, default_height)
    return html, re.search(r"<div\b[^>]*>", html)


def _patch_root_tag_attributes(
    tag: str,
    path: Path,
    max_end: float,
    narration_duration: float,
    default_width: int,
    default_height: int,
    locale: str,
    is_landscape: bool,
) -> str:
    tag_match = re.match(r"<([a-zA-Z0-9]+)", tag)
    tag_prefix = f"<{tag_match.group(1)}" if tag_match else "<div"
    new_tag = tag
    if not re.search(r'\bid=["\'][^"\']+["\']', new_tag):
        new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} id="stage"', 1)
    if "data-composition-id" not in new_tag:
        new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-composition-id="main"', 1)
    if locale == "en-US" and path.parent.name in ("hyperframes", "hyperframes_reels"):
        wrong_w, wrong_h = (1080, 1920) if is_landscape else (1920, 1080)
        new_tag = re.sub(rf'\bdata-width=["\']{wrong_w}["\']', f'data-width="{default_width}"', new_tag)
        new_tag = re.sub(rf'\bdata-height=["\']{wrong_h}["\']', f'data-height="{default_height}"', new_tag)
    if "data-width" not in new_tag:
        new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-width="{default_width}"', 1)
    if "data-height" not in new_tag:
        new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-height="{default_height}"', 1)
    if "data-duration" not in new_tag:
        initial_dur = max_end if max_end > 0 else narration_duration
        new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-duration="{initial_dur:.3f}"', 1)
    if "data-start" not in new_tag:
        new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-start="0"', 1)
    return new_tag


def _normalize_root_element(
    html: str,
    path: Path,
    max_end: float,
    narration_duration: float,
    default_width: int,
    default_height: int,
    locale: str,
    is_landscape: bool,
) -> str:
    html, root_open = _find_or_create_root_element(html, max_end, narration_duration, default_width, default_height)
    if not root_open:
        return html
    tag = root_open.group(0)
    new_tag = _patch_root_tag_attributes(
        tag, path, max_end, narration_duration, default_width, default_height, locale, is_landscape
    )
    if new_tag != tag:
        html = html[:root_open.start()] + new_tag + html[root_open.end():]
    return html


def _patch_badges_and_attributions(html: str) -> str:
    for pat in (
        r"<div\b[^>]*\bclass=[\"'][^>]*\bheader-bar\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\bbrand-logo\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\blive-badge\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\btag-badge\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\bbadge-label\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bid=[\"']source-badge[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\bsource-badge\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\bstage-header\b[^>]*[\"'][^>]*>.*?</div>",
        r"<div\b[^>]*\bclass=[\"'][^>]*\bbadge\b[^>]*[\"'][^>]*>.*?//.*?</div>",
        r"<(?:div|span)\b[^>]*\bclass=[\"'][^>]*\b(?:date-badge|stage-badge|date-pill)\b[^>]*[\"'][^>]*>.*?</(?:div|span)>",
        r"<section\b[^>]*\bclass=[\"'][^>]*\bbadge-overlay\b[^>]*[\"'][^>]*>\s*</section>",
    ):
        html = re.sub(pat, "", html, flags=re.IGNORECASE | re.DOTALL)

    html = html.replace("#source-badge, [class*='source-badge'], [id*='source-badge'] { display: none !important; opacity: 0 !important; visibility: hidden !important; }", "")
    html = html.replace("#source-badge, .source, [class*='source-badge'], [id*='source-badge'] { display: none !important; opacity: 0 !important; visibility: hidden !important; }", "")
    html = re.sub(r"\.source\s*,\s*", "", html)
    html = re.sub(r",\s*\.source(?=\s*\{)", "", html)
    if ".source {" in html and "display: none" in html:
        html = html.replace(".source { display: none", ".source-legacy-removed { display: none")
    return html


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


_EXCLUDE_SELECTOR_RE = re.compile(
    r"(?<![-\w])(?:[.#])?(?:[a-z0-9]+-)?(?:badge|tag|pill|kicker|source|credit|caption|om-asr)(?![-\w])"
)
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
        return f"font-size: {max(int(px), 54)}px" if "label" not in sel_low else ("font-size: 28px" if px < 28 else fallback_match)
    return "font-size: 28px" if px < 28 else fallback_match


def _fix_css_rule(rule_m: re.Match) -> str:
    selector, body = rule_m.group(1), rule_m.group(2)
    sel_low = selector.lower()
    if _EXCLUDE_SELECTOR_RE.search(sel_low):
        return rule_m.group(0)
    new_body = re.sub(r"font-size\s*:\s*([\d.]+)px", lambda fm: _bump_font_px(float(fm.group(1)), sel_low, fm.group(0)), body)
    if "scene-content" in sel_low:
        new_body = re.sub(r"overflow\s*:\s*hidden", "overflow: visible", new_body)
    return f"{selector}{{{new_body}}}"


def _upscale_css_block(style_m: re.Match) -> str:
    return re.sub(r"([^{}@\r\n]+)\{([^}]+)\}", _fix_css_rule, style_m.group(0))


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
h1, h2, h3, h4, .title, .title-large, .section-header, .headline, [class*="title"], [class*="header"] {{ color: #ffffff; font-weight: 800; text-shadow: 0 4px 20px rgba(0, 0, 0, 0.9); }}
p, .body-text, .description, .subtitle, .footer-text, [class*="text"]:not([class*="highlight"]) {{ color: #f8fafc; font-weight: 500; text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8); }}
.brand-name, .badge, .category, .tag, [class*="badge"], [class*="tag"] {{ color: #38bdf8; background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(56, 189, 248, 0.5); border-radius: 9999px; padding: 8px 24px; box-shadow: 0 0 15px rgba(56, 189, 248, 0.25); }}
.highlight-text, .accent, [class*="highlight"], [class*="accent"], [class*="metric"], [class*="stat"] {{ color: #38bdf8; font-weight: 700; text-shadow: 0 0 20px rgba(56, 189, 248, 0.4); }}
{STYLE_CLOSE_TAG}"""

    return f"""
/* Visual Quality Enhancement */
#stage {{ background: radial-gradient(circle at 50% 25%, #1e1b4b 0%, #0f172a 70%, #030712 100%); font-family: 'BeVietnamPro', sans-serif !important; }}
.scene:not([class*="scene-"]):not([style*="background"]) {{ background: transparent; }}
.scene {{ display: flex !important; flex-direction: column !important; justify-content: center !important; align-items: center !important; padding: 80px 48px 300px 48px !important; box-sizing: border-box !important; }}
.scene-content {{ overflow: visible !important; padding-left: 12px !important; padding-right: 12px !important; box-sizing: border-box !important; }}
.scene > div:not(.om-asr-caption):not([class*="diagram"]):not([class*="visual"]), .card, .container, [class*="card"], [class*="container"], [class*="box"], [class*="plate"] {{ background: rgba(30, 41, 59, 0.82) !important; border: 1px solid rgba(56, 189, 248, 0.4) !important; border-radius: 28px !important; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px rgba(56, 189, 248, 0.18) !important; backdrop-filter: blur(14px) !important; box-sizing: border-box !important; width: 960px !important; max-width: 90vw !important; margin: 16px auto !important; padding: 32px 40px !important; }}
h1, h2, h3, h4, .title, .title-large, .section-header, .headline, [class*="title"], [class*="header"] {{ color: #ffffff !important; font-weight: 800 !important; text-shadow: 0 4px 20px rgba(0, 0, 0, 0.9) !important; }}
p, .body-text, .description, .subtitle, .footer-text, [class*="text"]:not([class*="highlight"]) {{ color: #f8fafc !important; font-weight: 500 !important; text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8) !important; }}
.brand-name, .badge, .category, .tag, [class*="badge"], [class*="tag"] {{ color: #38bdf8 !important; background: rgba(15, 23, 42, 0.85) !important; border: 1px solid rgba(56, 189, 248, 0.5) !important; border-radius: 9999px !important; padding: 8px 24px !important; box-shadow: 0 0 15px rgba(56, 189, 248, 0.25) !important; }}
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

    if "/* Visual Quality Enhancement" not in html and STYLE_CLOSE_TAG in html:
        html = html.replace(STYLE_CLOSE_TAG, _build_visual_enhancement_css(html), 1)

    return html


def _replace_trailing_stopword(m: re.Match) -> str:
    if m.group(1).lower() in _VI_TRAILING_WORDS:
        return f".{m.group(2)}"
    return m.group(0)


def _ensure_clipping_guard(html: str, path: Path) -> str:
    if "overflow: hidden" in html:
        return html
    root_match = re.search(r"(#stage|#root|body|html)\s*\{[^{}]*\}", html)
    if root_match:
        rule = root_match.group(0)[:-1].rstrip() + " overflow: hidden; }"
        return html[:root_match.start()] + rule + html[root_match.end():]
    if TAG_STYLE_OPEN in html:
        return html.replace(TAG_STYLE_OPEN, f"{TAG_STYLE_OPEN}\n    body, html {{ overflow: hidden; }}\n", 1)
    raise ValueError(f"{path}: missing viewport CSS rule for clipping guard")


EMOJI_SVG_MAP: dict[str, str] = {
    "🔍": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;margin-right:6px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "🤖": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;margin-right:6px;"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8.01" y2="16"/><line x1="16" y1="16" x2="16.01" y2="16"/></svg>',
    "🚀": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;margin-right:6px;"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/></svg>',
    "⚡": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;margin-right:6px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    "🎯": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;margin-right:6px;"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>',
    "💡": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;margin-right:6px;"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5.76.76 1.23 1.52 1.41 2.5"/></svg>',
}


def _sanitize_emojis_to_vector_svg(html: str) -> str:
    for emoji, svg in EMOJI_SVG_MAP.items():
        html = html.replace(emoji, svg)
    return re.sub(r'[\U00010000-\U0010ffff]', '', html)


def _sanitize_metrics_and_symbols(html: str) -> str:
    def _strip_period(m: re.Match) -> str:
        open_tag, body, close_tag = m.group(1), m.group(2).rstrip(), m.group(3)
        if body.endswith(".") and not body.endswith("..."):
            body = body[:-1].rstrip()
        return f"{open_tag}{body}{close_tag}"

    for cls in (
        "metric-value", "flow-box", "flow-arrow", "flow-step", "step-box",
        "step-label", "step", "diagram-box", "diagram-node", "node", "badge",
        "date-pill", "date-badge", "stage-badge", "kicker", "card-title",
        "tag", "pill", "status-badge", "metric-card"
    ):
        html = re.sub(rf'(<[a-zA-Z0-9]+\b[^>]*\bclass="[^"]*{cls}[^"]*"[^>]*>)(.*?)(</[a-zA-Z0-9]+>)', _strip_period, html, flags=re.DOTALL)

    # Strip trailing periods from unicode and ascii arrows (e.g. ->. or →.)
    html = re.sub(r'([↓↑→←➔➜➡➤]|--?>|==?>|<--?|<==?)\.(?=\s*<)', r'\1', html)
    # Strip periods inside // separators (e.g. "2026. //" -> "2026 //")
    html = re.sub(r'\.\s*(//)', r' \1', html)

    def _strip_heading_span_period(h_match: re.Match) -> str:
        text = h_match.group(0)
        text = re.sub(r'(?<!\.)\.(?=</span>(?:\s*\w|\s*$))', '', text)
        return re.sub(r'(?<!\.)\.(?=(?:\s*</[^>]+>)*\s*$)', '', text)

    html = re.sub(r'<h[1-6]\b[^>]*>[\s\S]*?</h[1-6]>', _strip_heading_span_period, html)

    # Strip periods from short text/tspan nodes in SVG diagrams
    def _strip_svg_text_period(m: re.Match) -> str:
        open_tag, body, close_tag = m.group(1), m.group(2).rstrip(), m.group(3)
        if body.endswith(".") and len(body) <= 50 and not body.endswith("..."):
            body = body[:-1].rstrip()
        return f"{open_tag}{body}{close_tag}"

    html = re.sub(r'(<(?:text|tspan)\b[^>]*>)(.*?)(</(?:text|tspan)>)', _strip_svg_text_period, html, flags=re.DOTALL)
    return html


def _sanitize_sentence_cutoffs(html: str, path: Path) -> str:
    html = re.sub(r'([.!?])\s+[^<>\r\n]{2,80}?(</p>)', r'\1\2', html)
    html = re.sub(r'([^\s<>]{1,64})\s*?(</p>)', _replace_trailing_stopword, html)
    html = _sanitize_metrics_and_symbols(html)
    html = _sanitize_emojis_to_vector_svg(html)
    return _ensure_clipping_guard(html, path)


def _fix_bg_audio_tag(match: re.Match) -> str:
    tag = match.group(0)
    if "data-track-index" not in tag:
        tag = tag.replace(TAG_AUDIO_OPEN, f'{TAG_AUDIO_OPEN} data-track-index="1"', 1)
    if "data-start" not in tag:
        tag = tag.replace(TAG_AUDIO_OPEN, f'{TAG_AUDIO_OPEN} data-start="0"', 1)
    if "data-volume" not in tag:
        tag = tag.replace(TAG_AUDIO_OPEN, f'{TAG_AUDIO_OPEN} data-volume="0.12"', 1)
    return tag


def _patch_bgm_bindings(html: str, has_bg: bool) -> str:
    if not has_bg:
        return re.sub(r'<audio\b[^>]*\bid=["\'](?:bg-audio|bgm)["\'][^>]*>\s*(?:</audio>)?\s*', '', html)

    if not re.search(r'<audio\b[^>]*\bid=["\'](?:bg-audio|bgm)["\']', html):
        return html

    html = re.sub(
        r'(<audio\b(?=[^>]*\bid=["\'](?:bg-audio|bgm)["\'])[^>]*\bsrc=)["\'][^"\']*["\']',
        rf'\1"assets/{MUSIC_BG_MP3}"',
        html,
    )
    return re.sub(r'<audio\b[^>]*\bid=["\'](?:bg-audio|bgm)["\'][^>]*>', _fix_bg_audio_tag, html)


def _ensure_narration_audio_tag(html: str, path: Path, narration_src: str) -> str:
    root_open = re.search(r"<[a-zA-Z0-9]+\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
    if not root_open:
        body_root = re.search(r"<body\b[^>]*>", html, flags=re.IGNORECASE)
        if body_root:
            root_open = body_root
            html = html[:root_open.start()] + html[root_open.start():root_open.end()].replace(">", ' data-composition-id="main">', 1) + html[root_open.end():]
        else:
            raise ValueError(f"{path}: missing composition root for narration audio binding")
    narration_tag = NARRATION_TAG.replace('assets/narration.mp3', narration_src)
    return html[:root_open.end()] + "\n    " + narration_tag + html[root_open.end():]


def _add_audio_data_start(match: re.Match) -> str:
    tag = match.group(0)
    return tag.replace(TAG_AUDIO_OPEN, f'{TAG_AUDIO_OPEN} data-start="0"', 1) if "data-start=" not in tag else tag


def _patch_audio_bindings(html: str, path: Path, narration_src: str) -> str:
    html = re.sub(r"(<audio\b(?=[^>]*\bid=[\"']narration[\"'])[^>]*\bsrc=)[\"'][^\"']*[\"']", rf'\1"{narration_src}"', html)

    # A common director failure is emitting the narration element without a
    # src attribute.  The element's presence must not suppress materialization:
    # bind its source in-place so its authored timing/class attributes survive.
    def add_missing_narration_src(match: re.Match) -> str:
        tag = match.group(0)
        if re.search(r"\bsrc\s*=", tag, flags=re.IGNORECASE):
            return tag
        return tag[:-1] + f' src="{narration_src}">'

    html = re.sub(
        r"<audio\b(?=[^>]*\bid=[\"']narration[\"'])[^>]*>",
        add_missing_narration_src,
        html,
    )
    html = re.sub(r"<audio\b[^>]*\bid=[\"']narration_\d+[\"'][^>]*>\s*(?:</audio>)?\s*", "", html)

    has_bg = (path.parent / "assets" / MUSIC_BG_MP3).is_file()
    html = _patch_bgm_bindings(html, has_bg)

    if not re.search(r"<audio\b[^>]*\bid=[\"']narration[\"']", html):
        html = _ensure_narration_audio_tag(html, path, narration_src)

    return re.sub(r"<audio\b[^>]*>", _add_audio_data_start, html)


def _ensure_gsap_script(html: str) -> str:
    if "gsap.min.js" not in html and "gsap" not in html:
        gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
        if TAG_HEAD_CLOSE in html:
            html = html.replace(TAG_HEAD_CLOSE, f"  {gsap_tag}\n{TAG_HEAD_CLOSE}", 1)
        elif TAG_HEAD_OPEN in html:
            html = html.replace(TAG_HEAD_OPEN, f"{TAG_HEAD_OPEN}\n  {gsap_tag}", 1)
        else:
            html = f"{gsap_tag}\n" + html
    return html


def patch_html(path: Path, narration_duration: float = 0.0, **_kwargs: object) -> None:
    html = path.read_text(encoding="utf-8")
    locale = "vi-VN"
    try:
        from lib.artifact_paths import resolve_project_locale
        locale = resolve_project_locale(path.parent.parent)
    except Exception:
        pass
    is_landscape = locale == "en-US" and path.parent.name == "hyperframes"
    default_width, default_height = (1920, 1080) if is_landscape else (PORTRAIT_WIDTH, PORTRAIT_HEIGHT)

    html = _patch_locale_viewport(html, path, locale, is_landscape, default_width, default_height)
    max_end = _calculate_scenes_max_end(html)
    html = _normalize_root_element(html, path, max_end, narration_duration, default_width, default_height, locale, is_landscape)
    html = _patch_typography_and_css(html, path)
    html = _patch_badges_and_attributions(html)
    html = _sanitize_sentence_cutoffs(html, path)

    narration_src = (
        f"assets/{NARRATION_REELS_MP3}"
        if "hyperframes_reels" in str(path) and (path.parent / "assets" / NARRATION_REELS_MP3).is_file()
        else "assets/narration.mp3"
    )
    html = _patch_audio_bindings(html, path, narration_src)

    _validate_seek_safety(path, html)
    if (path.parent / "assets").is_dir():
        html = html.replace("../assets/", "assets/")
    html = repair_missing_composition_assets(path, html)
    html = _ensure_gsap_script(html)
    html = repair_gsap_timeline(html, path, narration_duration)

    path.write_text(html, encoding="utf-8")


def _ensure_bgm_asset(comp_dir: Path, assets_dir: Path) -> Path:
    bg_asset = assets_dir / MUSIC_BG_MP3
    if not bg_asset.is_file():
        for candidate_bg in (
            comp_dir.parent / "assets" / MUSIC_BG_MP3,
            Path(__file__).resolve().parents[1] / "assets" / "audio" / MUSIC_BG_MP3,
        ):
            if candidate_bg.is_file():
                shutil.copy2(candidate_bg, bg_asset)
                break
    return bg_asset


def _ensure_sfx_library(comp_dir: Path, assets_dir: Path) -> None:
    sfx_dir = assets_dir / "sfx"
    if not sfx_dir.is_dir() or not any(sfx_dir.glob("*.mp3")):
        for candidate_sfx in (
            comp_dir.parent / "assets" / "sfx",
            Path(__file__).resolve().parents[1] / "assets" / "audio" / "sfx",
        ):
            if candidate_sfx.is_dir():
                sfx_dir.mkdir(parents=True, exist_ok=True)
                for sfx_file in candidate_sfx.glob("*.mp3"):
                    shutil.copy2(sfx_file, sfx_dir / sfx_file.name)
                break


def _inject_bgm_tag(path: Path, bg_asset: Path) -> None:
    if not bg_asset.is_file():
        return
    html = path.read_text(encoding="utf-8")
    if re.search(r'<audio\b[^>]*\bid=["\'](?:bg-audio|bgm)["\']', html):
        return
    bgm_tag = f'<audio id="bgm" src="assets/{MUSIC_BG_MP3}" data-start="0" data-track-index="1" data-volume="0.12" loop></audio>'
    if re.search(r'<audio\b[^>]*\bid=["\']narration["\'][^>]*>', html):
        html = re.sub(
            r'(<audio\b[^>]*\bid=["\']narration["\'][^>]*>(?:</audio>)?)',
            rf'\1\n    {bgm_tag}',
            html,
            count=1,
        )
        path.write_text(html, encoding="utf-8")
    elif '<div id="stage"' in html or '<div id="root"' in html:
        html = re.sub(
            r'(<div\b[^>]*\bid=["\'](?:stage|root)["\'][^>]*>)',
            rf'\1\n    {bgm_tag}',
            html,
            count=1,
        )
        path.write_text(html, encoding="utf-8")


def repair_hyperframes_composition(path: Path) -> None:
    """Repair HyperFrames composition assets, inject background music and SFX if missing."""
    path = Path(path)
    comp_dir = path.parent
    assets_dir = comp_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    bg_asset = _ensure_bgm_asset(comp_dir, assets_dir)
    _ensure_sfx_library(comp_dir, assets_dir)
    _inject_bgm_tag(path, bg_asset)
    patch_html(path)


from scripts.repair_hyperframes_validation import (
    _CompositionDOM,
    declared_dimensions,
    _mask_javascript_noncode,
    _validate_seek_safety,
    validate_dimensions,
    validate_html,
)


def _check_composition_fonts(assets: Path) -> list[str]:
    errors: list[str] = []
    for font in REQUIRED_FONTS:
        font_path = assets / font
        if not font_path.is_file() or font_path.stat().st_size == 0:
            errors.append(f"{font_path}: missing or empty Vietnamese font asset")
    return errors


def _repair_single_composition(composition_dir: Path) -> list[str]:
    index = composition_dir / "index.html"
    assets = composition_dir / "assets"
    if not index.is_file():
        return [f"{index}: missing composition index"]

    errors = _check_composition_fonts(assets)
    narration_src = (
        NARRATION_REELS_MP3
        if "hyperframes_reels" in str(index) and (assets / NARRATION_REELS_MP3).is_file()
        else "narration.mp3"
    )
    narration = assets / narration_src
    if not narration.is_file() or narration.stat().st_size == 0:
        errors.append(f"{narration}: missing or empty narration audio asset")

    if not errors:
        narration_duration = probe_duration(narration) if narration.is_file() and narration.stat().st_size > 0 else 0.0
        try:
            patch_html(index, narration_duration)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            errors.extend(validate_html(index))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair and validate HyperFrames font/audio bindings")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument(
        "--composition",
        choices=("hyperframes", "hyperframes_reels"),
        help="Repair only one composition instead of both",
    )
    parser.add_argument("--strict", action="store_true", help="Compatibility flag; seek-safety checks always apply")
    args = parser.parse_args()

    project_dir = args.project_dir
    errors: list[str] = []
    compositions = (args.composition,) if args.composition else ("hyperframes", "hyperframes_reels")
    for composition in compositions:
        errors.extend(_repair_single_composition(project_dir / composition))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
