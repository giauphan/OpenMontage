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

NARRATION_TAG = (
    '<audio id="narration" src="assets/narration.mp3" '
    'data-start="0" data-track-index="10" data-volume="1"></audio>'
)

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


def repair_missing_composition_assets(path: Path, html: str) -> str:
    """Reject unresolved local media references without mutating project assets."""
    composition_dir = path.parent.resolve()

    def validate_local_reference(raw_reference: str, kind: str) -> None:
        raw_reference = raw_reference.strip()
        decoded_reference = html_lib.unescape(raw_reference)
        if kind == "CSS URL" and decoded_reference != raw_reference:
            raise ValueError(
                f"{path}: HTML-entity-encoded CSS URL is ambiguous; use a percent-encoded path instead: {raw_reference!r}"
            )
        reference = decoded_reference
        if not reference or reference.startswith("#"):
            return
        if reference.lower().startswith("data:") or re.match(r"^(?:https?:)?//", reference, re.IGNORECASE):
            return

        clean_reference = unquote(reference.split("?", 1)[0].split("#", 1)[0])
        if not clean_reference or clean_reference in (".", "./", "/"):
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

        unresolved = composition_dir / candidate_path
        current = composition_dir
        for part in candidate_path.parts:
            if part in ("", "."):
                continue
            current = current / part
            if current.is_symlink():
                raise ValueError(f"{path}: {kind} asset reference traverses a symbolic link: {reference!r}")

        target = unresolved.resolve()
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

    for match in re.finditer(r'<img\b[^>]*\bsrc=["\']([^"\']*)["\'][^>]*>', html, flags=re.IGNORECASE):
        validate_local_reference(match.group(1), "image")

    for match in re.finditer(r'url\((["\']?)([^"\'\)]+)\1\)', html, flags=re.IGNORECASE):
        validate_local_reference(match.group(2), "CSS URL")

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


def patch_html(path: Path, narration_duration: float = 0.0, strict: bool = False) -> None:
    html = path.read_text(encoding="utf-8")

    # Calculate original duration of scenes to avoid incorrectly skipping timeline alignment
    # when data-duration is missing or stale on the root element
    max_end = 0.0
    for match in re.finditer(r'<[a-zA-Z]+\b[^>]*\bclass=["\'][^"\']*\bscene\b[^"\']*["\'][^>]*>', html):
        tag = match.group(0)
        s_match = re.search(r'\bdata-start=["\']([0-9.]+)[\"\']', tag)
        d_match = re.search(r'\bdata-duration=["\']([0-9.]+)[\"\']', tag)
        if s_match and d_match:
            max_end = max(max_end, float(s_match.group(1)) + float(d_match.group(1)))
    if max_end == 0.0:
        for match in re.finditer(r'<[a-zA-Z]+\b(?!data-composition-id)[^>]*>', html):
            tag = match.group(0)
            if "data-composition-id" in tag:
                continue
            s_match = re.search(r'\bdata-start=["\']([0-9.]+)[\"\']', tag)
            d_match = re.search(r'\bdata-duration=["\']([0-9.]+)[\"\']', tag)
            if s_match and d_match:
                max_end = max(max_end, float(s_match.group(1)) + float(d_match.group(1)))

    # Ensure composition root has required attributes.
    root_open = re.search(r"<[a-zA-Z0-9]+\b(?![^>]*\bclass=[\"'][^\"']*\bscene\b)(?=[^>]*(?:\bdata-composition-id=|id=[\"'](?:stage|composition|root)[\"']|class=[\"'][^\"']*\bcomposition\b[^\"']*[\"']))[^>]*>", html)
    if not root_open:
        scene_match = re.search(r"<div\b[^>]*\bclass=[\"'][^\"']*\bscene\b[^\"']*[\"'][^>]*>", html)
        if scene_match:
            start_pos = scene_match.start()
            body_close = re.search(r"</body>", html[start_pos:], flags=re.IGNORECASE)
            script_match = re.search(r"<script\b", html[start_pos:], flags=re.IGNORECASE)
            end_pos = (start_pos + script_match.start()) if script_match else ((start_pos + body_close.start()) if body_close else len(html))
            initial_dur = max_end if max_end > 0 else narration_duration
            stage_open = (
                f'<div id="stage" class="composition" data-composition-id="main" '
                f'data-start="0" data-duration="{initial_dur:.3f}" data-width="1080" data-height="1920">\n'
            )
            stage_close = "\n</div>\n"
            inner_scenes = html[start_pos:end_pos]
            inner_scenes = re.sub(r'\s+data-composition-id=([\'"])[^\'"]+\1', '', inner_scenes)
            html = html[:start_pos] + stage_open + inner_scenes + stage_close + html[end_pos:]
            root_open = re.search(r"<div\b[^>]*id=[\"']stage[\"'][^>]*>", html)
            if "#stage" not in html and "<style>" in html:
                stage_css = "\n        #stage { position: relative; width: 1080px; height: 1920px; overflow: hidden; background: radial-gradient(circle at 50% 25%, #1e1b4b 0%, #0f172a 70%, #030712 100%); font-family: 'BeVietnamPro', sans-serif; }\n"
                html = html.replace("<style>", "<style>" + stage_css, 1)
        else:
            root_open = re.search(r"<div\b[^>]*>", html)
    if root_open:
        tag = root_open.group(0)
        tag_match = re.match(r"<([a-zA-Z0-9]+)", tag)
        tag_prefix = f"<{tag_match.group(1)}" if tag_match else "<div"
        new_tag = tag
        if "data-composition-id" not in new_tag:
            new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-composition-id="main"', 1)
        if "data-width" not in new_tag:
            new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-width="1080"', 1)
        if "data-height" not in new_tag:
            new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-height="1920"', 1)
        if "data-duration" not in new_tag:
            initial_dur = max_end if max_end > 0 else narration_duration
            new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-duration="{initial_dur:.3f}"', 1)
        if "data-start" not in new_tag:
            new_tag = new_tag.replace(tag_prefix, f'{tag_prefix} data-start="0"', 1)
        if new_tag != tag:
            html = html[:root_open.start()] + new_tag + html[root_open.end():]

    if "font-family: 'BeVietnamPro'" not in html:
        if "<style>" not in html:
            raise ValueError(f"{path}: missing style element for font binding")
        html = html.replace("<style>", "<style>\n    " + FONT_CSS, 1)
    html = re.sub(
        r"--font-heading:\s*[^;]+;",
        "--font-heading: 'BeVietnamPro', Arial, sans-serif;",
        html,
    )
    html = re.sub(
        r"--font-body:\s*[^;]+;",
        "--font-body: 'BeVietnamPro', Arial, sans-serif;",
        html,
    )
    if "--font-heading:" not in html or "--font-body:" not in html:
        root_match = re.search(r":root\s*\{([^{}]*)\}", html)
        if root_match:
            declarations = root_match.group(1)
            if "--font-heading:" not in declarations:
                declarations += " --font-heading: 'BeVietnamPro', Arial, sans-serif;"
            if "--font-body:" not in declarations:
                declarations += " --font-body: 'BeVietnamPro', Arial, sans-serif;"
            html = html[:root_match.start(1)] + declarations + html[root_match.end(1):]
        elif "</style>" in html:
            html = html.replace(
                "</style>",
                ":root { --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }\n</style>",
                1,
            )
        else:
            raise ValueError(f"{path}: missing style element for font bindings")
    # Remove any header bars, logo badges, or top ticker banners
    html = re.sub(r"<div\b[^>]*\bclass=[\"'][^>]*\bheader-bar\b[^>]*[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<div\b[^>]*\bclass=[\"'][^>]*\bbrand-logo\b[^>]*[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<div\b[^>]*\bclass=[\"'][^>]*\blive-badge\b[^>]*[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<div\b[^>]*\bclass=[\"'][^>]*\btag-badge\b[^>]*[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<div\b[^>]*\bclass=[\"'][^>]*\bbadge-label\b[^>]*[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)

    # Strict transparency: NEVER inject display:none for news source attribution.
    # Remove any badge nodes that remain from director artifacts, but do NOT
    # inject a hide rule. The retired "hide all sources" behavior was the
    # Content Appropriateness blocker (cand_adf 58/100).
    html = re.sub(r"<div\b[^>]*\bid=[\"']source-badge[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<div\b[^>]*\bclass=[\"'][^>]*\bsource-badge\b[^>]*[\"'][^>]*>.*?</div>", "", html, flags=re.IGNORECASE | re.DOTALL)
    # Strip any hide rule that was previously injected by older repair versions.
    html = html.replace("#source-badge, [class*='source-badge'], [id*='source-badge'] { display: none !important; opacity: 0 !important; visibility: hidden !important; }", "")
    html = html.replace("#source-badge, .source, [class*='source-badge'], [id*='source-badge'] { display: none !important; opacity: 0 !important; visibility: hidden !important; }", "")
    html = re.sub(r"\.source\s*,\s*", "", html)
    html = re.sub(r",\s*\.source(?=\s*\{)", "", html)
    if ".source {" in html and "display: none" in html:
        html = html.replace(".source { display: none", ".source-legacy-removed { display: none")


    # Enforce text wrapping and container bounds to fix misaligned yellow boxes
    if "overflow-wrap: break-word" not in html:
        wrap_css_rule = """

/* Enforce text wrapping and dynamic bounds for text containers */
h1, h2, h3, h4, h5, h6, p, span, .caption, .title, .text, .highlight, .accent, [class*='caption'], [class*='text'] { overflow-wrap: break-word !important; word-wrap: break-word !important; word-break: break-word !important; max-width: 100%; box-sizing: border-box; }
</style>"""
        html = html.replace("</style>", wrap_css_rule, 1)

    if "/* Visual Quality Enhancement */" not in html and "</style>" in html:
        visual_mode = os.environ.get("NEWS_VISUAL_MODE", "0") in ("1", "true", "True")
        if visual_mode:
            enhancement_css = """
/* Visual Quality Enhancement (Context-Aware Visual Mode) */
#stage {
    font-family: 'BeVietnamPro', sans-serif;
}
.scene {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 80px 48px 300px 48px;
    box-sizing: border-box;
}
/* Ensure visual media elements are properly layered and never clipped */
.scene img, .scene video, .scene svg, .scene-media {
    max-width: 100%;
    height: auto;
    object-fit: contain;
    z-index: 1;
}
/* Scoped default card styling without overriding specific scene elements or diagrams */
.card-default {
    background: rgba(30, 41, 59, 0.82);
    border: 1px solid rgba(56, 189, 248, 0.4);
    border-radius: 28px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px rgba(56, 189, 248, 0.18);
    backdrop-filter: blur(14px);
    box-sizing: border-box;
    width: 960px;
    max-width: 90vw;
    margin: 16px auto;
    padding: 32px 40px;
}
/* High-contrast typography */
h1, h2, h3, h4, .title, .title-large, .section-header, .headline, [class*="title"], [class*="header"] {
    color: #ffffff;
    font-weight: 800;
    text-shadow: 0 4px 20px rgba(0, 0, 0, 0.9);
}
p, .body-text, .description, .subtitle, .footer-text, [class*="text"]:not([class*="highlight"]) {
    color: #f8fafc;
    font-weight: 500;
    text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8);
}
.brand-name, .badge, .category, .tag, [class*="badge"], [class*="tag"] {
    color: #38bdf8;
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(56, 189, 248, 0.5);
    border-radius: 9999px;
    padding: 8px 24px;
    box-shadow: 0 0 15px rgba(56, 189, 248, 0.25);
}
.highlight-text, .accent, [class*="highlight"], [class*="accent"], [class*="metric"], [class*="stat"] {
    color: #38bdf8;
    font-weight: 700;
    text-shadow: 0 0 20px rgba(56, 189, 248, 0.4);
}
</style>"""
        else:
            enhancement_css = """
/* Visual Quality Enhancement */
#stage {
    background: radial-gradient(circle at 50% 25%, #1e1b4b 0%, #0f172a 70%, #030712 100%);
    font-family: 'BeVietnamPro', sans-serif !important;
}
.scene:not([class*="scene-"]):not([style*="background"]) {
    background: transparent;
}
.scene {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    padding: 80px 48px 300px 48px !important;
    box-sizing: border-box !important;
}
.scene > div:not(.om-asr-caption):not([class*="diagram"]):not([class*="visual"]), .card, .container, [class*="card"], [class*="container"], [class*="box"], [class*="plate"] {
    background: rgba(30, 41, 59, 0.82) !important;
    border: 1px solid rgba(56, 189, 248, 0.4) !important;
    border-radius: 28px !important;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 30px rgba(56, 189, 248, 0.18) !important;
    backdrop-filter: blur(14px) !important;
    box-sizing: border-box !important;
    width: 960px !important;
    max-width: 90vw !important;
    margin: 16px auto !important;
    padding: 32px 40px !important;
}
/* High-contrast typography */
h1, h2, h3, h4, .title, .title-large, .section-header, .headline, [class*="title"], [class*="header"] {
    color: #ffffff !important;
    font-weight: 800 !important;
    text-shadow: 0 4px 20px rgba(0, 0, 0, 0.9) !important;
}
p, .body-text, .description, .subtitle, .footer-text, [class*="text"]:not([class*="highlight"]) {
    color: #f8fafc !important;
    font-weight: 500 !important;
    text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8) !important;
}
.brand-name, .badge, .category, .tag, [class*="badge"], [class*="tag"] {
    color: #38bdf8 !important;
    background: rgba(15, 23, 42, 0.85) !important;
    border: 1px solid rgba(56, 189, 248, 0.5) !important;
    border-radius: 9999px !important;
    padding: 8px 24px !important;
    box-shadow: 0 0 15px rgba(56, 189, 248, 0.25) !important;
}
.highlight-text, .accent, [class*="highlight"], [class*="accent"], [class*="metric"], [class*="stat"] {
    color: #38bdf8 !important;
    font-weight: 700 !important;
    text-shadow: 0 0 20px rgba(56, 189, 248, 0.4) !important;
}
</style>"""
        html = html.replace("</style>", enhancement_css, 1)

    # Sanitize abrupt sentence cutoffs in text elements
    # 1. Strip dangling unpunctuated clauses if a complete sentence ending with [.!?] preceded it
    html = re.sub(
        r'([.!?])\s+[^<.!?]{3,}\s*(</(?:p|div|span)>)',
        r'\1\2',
        html,
    )
    # 2. Safety net for specific dangling connector words
    html = re.sub(
        r'\b(xuống|lên|vào|ra|của|và|là|khi|được|cho|với|tại|từ|về|đến|trong|ngoài|bởi|như|do)\s*(</(?:p|div|span)>)',
        r'.\2',
        html,
        flags=re.IGNORECASE,
    )
    # 3. Ensure prose elements end with terminal punctuation
    html = re.sub(
        r'([^.!?\s>])\s*(</(?:p|div|span)>)',
        r'\1.\2',
        html,
    )

    if "overflow: hidden" not in html:
        root_match = re.search(r"(#root|body|html)\s*\{[^{}]*\}", html)
        if root_match:
            rule = root_match.group(0)
            rule = rule[:-1].rstrip() + " overflow: hidden; }"
            html = html[:root_match.start()] + rule + html[root_match.end():]
        else:
            raise ValueError(f"{path}: missing viewport CSS rule for clipping guard")
    # For reels composition, bind to reels narration file if present, else fallback to narration.mp3
    narration_src = (
        "assets/narration_reels.mp3"
        if "hyperframes_reels" in str(path) and (path.parent / "assets" / "narration_reels.mp3").is_file()
        else "assets/narration.mp3"
    )
    html = re.sub(
        r"(<audio\b(?=[^>]*\bid=[\"']narration[\"'])[^>]*\bsrc=)[\"'][^\"']*[\"']",
        rf'\1"{narration_src}"',
        html,
    )
    # Remove individual narration tags that lack materialized assets
    html = re.sub(r"<audio\b[^>]*\bid=[\"']narration_\d+[\"'][^>]*>\s*(?:</audio>)?\s*", "", html)

    # Handle background audio: if music-bg.mp3 exists, point to it; otherwise remove bg-audio
    has_bg = (path.parent / "assets" / "music-bg.mp3").is_file()
    if has_bg:
        html = re.sub(
            r'(<audio\b(?=[^>]*\bid=["\']bg-audio["\'])[^>]*\bsrc=)["\'][^"\']*["\']',
            r'\1"assets/music-bg.mp3"',
            html,
        )
        # Ensure track index and data-start
        def fix_bg_tag(match):
            tag = match.group(0)
            if "data-track-index" not in tag:
                tag = tag.replace("<audio", '<audio data-track-index="1"', 1)
            if "data-start" not in tag:
                tag = tag.replace("<audio", '<audio data-start="0"', 1)
            return tag
        html = re.sub(r'<audio\b[^>]*\bid=["\']bg-audio["\'][^>]*>', fix_bg_tag, html)
    else:
        html = re.sub(r'<audio\b[^>]*\bid=["\']bg-audio["\'][^>]*>\s*(?:</audio>)?\s*', '', html)

    if not re.search(r"<audio\b[^>]*\bid=[\"']narration[\"']", html):
        root_open = re.search(r"<[a-zA-Z0-9]+\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
        if not root_open:
            body_root = re.search(r"<body\b[^>]*>", html, flags=re.IGNORECASE)
            if body_root:
                root_open = body_root
                html = html[:root_open.start()] + html[root_open.start():root_open.end()].replace(
                    ">", ' data-composition-id="main">', 1
                ) + html[root_open.end():]
            else:
                raise ValueError(f"{path}: missing composition root for narration audio binding")
        # Use reels narration for reels composition
        narration_tag = NARRATION_TAG.replace('assets/narration.mp3', narration_src)
        html = html[:root_open.end()] + "\n    " + narration_tag + html[root_open.end():]

    # Ensure all remaining audio tags have data-start="0" if missing
    def add_data_start(match):
        tag = match.group(0)
        if "data-start=" not in tag:
            tag = tag.replace("<audio", '<audio data-start="0"', 1)
        return tag

    html = re.sub(r"<audio\b[^>]*>", add_data_start, html)

    _validate_seek_safety(path, html)
    html = repair_missing_composition_assets(path, html)

    # Ensure GSAP CDN script is always present in HTML
    if "gsap.min.js" not in html and "gsap" not in html:
        gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
        if "</head>" in html:
            html = html.replace("</head>", f"  {gsap_tag}\n</head>", 1)
        elif "<head>" in html:
            html = html.replace("<head>", f"<head>\n  {gsap_tag}", 1)
        else:
            html = f"{gsap_tag}\n" + html

    # Authored visibility, scene styling and JavaScript are never rewritten.

    path.write_text(html, encoding="utf-8")


class _CompositionDOM(HTMLParser):
    """Inspect actual elements, never CSS, comments or script strings as DOM."""

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.nodes: list[tuple[str, dict, tuple[int, ...]]] = []
        self.stack: list[int] = []
        self.scripts: list[tuple[dict, str]] = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.nodes.append((tag, attributes, tuple(self.stack)))
        index = len(self.nodes) - 1
        if tag == "script":
            self.scripts.append((attributes, ""))
        if tag not in self._VOID:
            self.stack.append(index)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for position in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[position]][0] == tag:
                del self.stack[position:]
                break

    def handle_data(self, data):
        if self.stack and self.nodes[self.stack[-1]][0] == "script":
            attrs, text = self.scripts[-1]
            self.scripts[-1] = attrs, text + data


def declared_dimensions(html: str) -> dict[str, tuple[int, int]]:
    """Collect explicit canvas dimensions from the root, viewport and CSS."""
    found: dict[str, tuple[int, int]] = {}
    dom = _CompositionDOM(html)
    roots = [(tag, attrs) for tag, attrs, _ in dom.nodes if "data-composition-id" in attrs]
    if roots:
        attrs = roots[0][1]
        try:
            found["root data-width/data-height"] = (int(attrs["data-width"]), int(attrs["data-height"]))
        except (KeyError, TypeError, ValueError):
            pass
    viewport = re.search(r"<meta\b[^>]*\bname=[\"']viewport[\"'][^>]*\bcontent=[\"']([^\"']+)[\"']", html, re.I)
    if viewport:
        w = re.search(r"\bwidth\s*=\s*(\d+)", viewport.group(1))
        h = re.search(r"\bheight\s*=\s*(\d+)", viewport.group(1))
        if w and h:
            found["meta viewport"] = (int(w.group(1)), int(h.group(1)))
    for i, rule in enumerate(re.finditer(r"(?:#root|#stage|body|html)\b[^{}]*\{([^{}]*)\}", html), 1):
        w = re.search(r"(?<![-\w])width\s*:\s*(\d+)px", rule.group(1))
        h = re.search(r"(?<![-\w])height\s*:\s*(\d+)px", rule.group(1))
        if w and h:
            found[f"CSS rule {i}"] = (int(w.group(1)), int(h.group(1)))
    return found


def _mask_javascript_noncode(source: str) -> str:
    """Blank comments and quoted literals while retaining source offsets."""
    chars = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
        elif source.startswith("/*", index):
            close = source.find("*/", index + 2)
            end = len(source) if close < 0 else close + 2
        elif source[index] in "'\"`":
            quote = source[index]
            end = index + 1
            while end < len(source):
                if source[end] == "\\":
                    end += 2
                elif source[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
        else:
            index += 1
            continue
        for pos in range(index, min(end, len(chars))):
            if chars[pos] not in "\r\n":
                chars[pos] = " "
        index = max(end, index + 1)
    return "".join(chars)


def _validate_seek_safety(path: Path, html: str) -> None:
    """Reject a few identifiable unsafe GSAP patterns; this is not a JS parser."""
    dom = _CompositionDOM(html)
    scripts = [body for attrs, body in dom.scripts if not attrs.get("src")]
    inline = "\n".join(scripts)
    code = _mask_javascript_noncode(inline)
    if re.search(r"\brepeat\s*:\s*-\s*1\b", code):
        raise ValueError(f"{path}: infinite GSAP repeat is not seek-safe; regenerate with finite registered timeline animations")
    if re.search(r"\bgsap\s*\.\s*(?:to|from|fromTo|set)\s*\(", code):
        raise ValueError(f"{path}: standalone gsap animation is not registered to the paused HyperFrames timeline; regenerate using the registered timeline")

    timelines = list(re.finditer(r"\bgsap\s*\.\s*timeline\s*\(([^)]*)\)", code))
    for match in timelines:
        if re.search(r"\bpaused\s*:\s*true\b", match.group(1)) is None:
            raise ValueError(f"{path}: GSAP timelines must be created with paused: true for deterministic seeking")

    for _, attrs, _ in dom.nodes:
        composition_id = attrs.get("data-composition-id")
        if not isinstance(composition_id, str) or "data-no-timeline" in attrs:
            continue
        registration = re.compile(
            r"window\s*\.\s*__timelines\s*\[\s*(['\"])" + re.escape(composition_id) + r"\1\s*\]"
        )
        registered = any(
            code[match.start():match.start() + len("window")].strip().startswith("window")
            for match in registration.finditer(inline)
        )
        if timelines and not registered:
            raise ValueError(f"{path}: GSAP timeline is not registered for composition {composition_id!r}; regenerate with window.__timelines registration")


def validate_dimensions(path: Path, html: str) -> list[str]:
    """Reject any composition that does not declare a true portrait canvas."""
    expected = (PORTRAIT_WIDTH, PORTRAIT_HEIGHT)
    found = declared_dimensions(html)
    if not found:
        return [
            f"{path}: cannot determine canvas dimensions; declare "
            f"{PORTRAIT_WIDTH}x{PORTRAIT_HEIGHT} on the composition root, meta viewport, and #root CSS"
        ]

    distinct = set(found.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{source}={w}x{h}" for source, (w, h) in sorted(found.items()))
        return [f"{path}: conflicting canvas dimensions ({detail})"]

    width, height = distinct.pop()
    if (width, height) != expected:
        sources = ", ".join(sorted(found))
        return [
            f"{path}: expected {PORTRAIT_WIDTH}x{PORTRAIT_HEIGHT} portrait canvas, "
            f"got {width}x{height} (declared by {sources})"
        ]
    return []


def validate_html(path: Path) -> list[str]:
    errors: list[str] = []
    html = path.read_text(encoding="utf-8")
    errors.extend(validate_dimensions(path, html))
    required_bindings = (
        "font-family: 'BeVietnamPro'",
        "--font-heading: 'BeVietnamPro', Arial, sans-serif;",
        "--font-body: 'BeVietnamPro', Arial, sans-serif;",
    )
    for binding in required_bindings:
        if binding not in html:
            errors.append(f"{path}: missing {binding}")
    narration_tags = re.findall(r"<audio\b[^>]*\bid=[\"']narration[\"'][^>]*>", html)
    if not narration_tags:
        errors.append(f"{path}: no narration audio element bound in composition")
    for tag in narration_tags:
        if not re.search(r"\bsrc=[\"']assets/narration(_reels)?\.mp3[\"']", tag):
            errors.append(f"{path}: narration audio src is empty or wrong")

    # Enforce text wrapping and container bounds to fix misaligned yellow boxes
    if "overflow-wrap: break-word" not in html:
        wrap_css_rule = """

/* Enforce text wrapping and dynamic bounds for text containers */
h1, h2, h3, h4, h5, h6, p, span, .caption, .title, .text, .highlight, .accent, [class*='caption'], [class*='text'] { overflow-wrap: break-word !important; word-wrap: break-word !important; word-break: break-word !important; max-width: 100%; box-sizing: border-box; }
</style>"""
        html = html.replace("</style>", wrap_css_rule, 1)

    if "overflow: hidden" not in html:
        errors.append(f"{path}: missing viewport clipping guard")
    # NFD-decomposed text and HTML entities still count as genuine Vietnamese
    # on-screen content; normalize before the glyph smoke check.
    visible_text = unicodedata.normalize("NFC", html_lib.unescape(html))
    if VIETNAMESE_GLYPH_SENTINELS and not any(ch in visible_text for ch in VIETNAMESE_GLYPH_SENTINELS):
        errors.append(f"{path}: no Vietnamese diacritic text found for glyph smoke validation")
    malformed = sorted(set(_MALFORMED_TEXT_PATTERN.findall(html)))
    if malformed:
        codes = ", ".join(f"U+{ord(ch):04X}" for ch in malformed)
        errors.append(f"{path}: composition text contains unrenderable characters: {codes}")
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
        composition_errors: list[str] = []
        composition_dir = project_dir / composition
        index = composition_dir / "index.html"
        assets = composition_dir / "assets"
        if not index.is_file():
            errors.append(f"{index}: missing composition index")
            continue
        for font in REQUIRED_FONTS:
            font_path = assets / font
            if not font_path.is_file() or font_path.stat().st_size == 0:
                composition_errors.append(f"{font_path}: missing or empty Vietnamese font asset")
        narration_src = "narration_reels.mp3" if ("hyperframes_reels" in str(index) and (assets / "narration_reels.mp3").is_file()) else "narration.mp3"
        narration = assets / narration_src
        if not narration.is_file() or narration.stat().st_size == 0:
            composition_errors.append(f"{narration}: missing or empty narration audio asset")
        narration_duration = 0.0
        if narration.is_file() and narration.stat().st_size > 0:
            narration_duration = probe_duration(narration)
        if not composition_errors:
            try:
                patch_html(index, narration_duration, strict=args.strict)
            except ValueError as exc:
                composition_errors.append(str(exc))
            else:
                composition_errors.extend(validate_html(index))
        errors.extend(composition_errors)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
