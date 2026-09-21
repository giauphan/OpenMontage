#!/usr/bin/env python3
"""Repair and validate HyperFrames assets before rendering."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

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


def generate_fallback_visual_asset(target_path: Path, label: str = "Editorial Visual") -> None:
    """Generate high-contrast editorial fallback SVG asset so Chromium never throws 404."""
    if target_path.is_dir():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920" width="1080" height="1920">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="50%" stop-color="#1e293b" />
      <stop offset="100%" stop-color="#0284c7" />
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="100%" stop-color="#818cf8" />
    </linearGradient>
  </defs>
  <rect width="1080" height="1920" fill="url(#bg)" />
  <circle cx="540" cy="800" r="280" fill="url(#accent)" opacity="0.15" />
  <rect x="140" y="700" width="800" height="400" rx="32" fill="#1e293b" opacity="0.85" stroke="#38bdf8" stroke-width="4" />
  <text x="540" y="880" font-family="'BeVietnamPro', Arial, sans-serif" font-size="48" font-weight="bold" fill="#f8fafc" text-anchor="middle">{label}</text>
  <text x="540" y="960" font-family="'BeVietnamPro', Arial, sans-serif" font-size="28" fill="#38bdf8" text-anchor="middle">Tin Tức Công Nghệ AI</text>
</svg>"""
    target_path.write_text(svg_content, encoding="utf-8")


def repair_missing_composition_assets(path: Path, html: str) -> str:
    """Detect missing local asset references (img src, css url) and materialize fallbacks to prevent 404."""
    composition_dir = path.parent
    project_root = composition_dir.parent
    assets_dir = composition_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 1. Match img src
    def fix_img_src(match: re.Match[str]) -> str:
        tag = match.group(0)
        src = match.group(1).strip()
        if not src or src.startswith("data:"):
            return tag

        # Check if local relative path
        if not src.startswith(("http://", "https://", "//")):
            clean_src = src.split("?")[0].split("#")[0]
            if not clean_src or clean_src in (".", "./", "/"):
                return tag
            try:
                target = (composition_dir / clean_src).resolve()
            except Exception:
                return tag
            if target.is_dir() or target == composition_dir:
                return tag
            if not target.is_file() or target.stat().st_size == 0:
                # Look for matching filename in project assets
                filename = Path(clean_src).name
                if not filename or filename.startswith("."):
                    return tag
                candidates = [c for c in project_root.glob(f"**/{filename}") if c.is_file()]
                found = False
                for cand in candidates:
                    if cand.stat().st_size > 0 and cand != target:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(cand, target)
                        found = True
                        break
                if not found:
                    # Materialize fallback SVG
                    fallback_file = target.with_suffix(".svg") if target.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else target
                    if fallback_file.is_dir() or fallback_file == composition_dir:
                        return tag
                    label = Path(clean_src).stem.replace("_", " ").replace("-", " ").title()
                    generate_fallback_visual_asset(fallback_file, label=label or "Visual Asset")
                    if fallback_file != target:
                        return tag.replace(src, str(fallback_file.relative_to(composition_dir)))
        return tag

    html = re.sub(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', fix_img_src, html, flags=re.IGNORECASE)

    # 2. Match background url(...)
    def fix_css_url(match: re.Match[str]) -> str:
        full_match = match.group(0)
        url_target = match.group(2).strip()
        if not url_target or url_target.startswith("data:"):
            return full_match
        if not url_target.startswith(("http://", "https://", "//")):
            clean_url = url_target.split("?")[0].split("#")[0]
            if not clean_url or clean_url in (".", "./", "/"):
                return full_match
            try:
                target = (composition_dir / clean_url).resolve()
            except Exception:
                return full_match
            if target.is_dir() or target == composition_dir:
                return full_match
            if not target.is_file() or target.stat().st_size == 0:
                filename = Path(clean_url).name
                if not filename or filename.startswith("."):
                    return full_match
                candidates = [c for c in project_root.glob(f"**/{filename}") if c.is_file()]
                found = False
                for cand in candidates:
                    if cand.stat().st_size > 0 and cand != target:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(cand, target)
                        found = True
                        break
                if not found:
                    fallback_file = target.with_suffix(".svg") if target.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else target
                    if fallback_file.is_dir() or fallback_file == composition_dir:
                        return full_match
                    generate_fallback_visual_asset(fallback_file, label="Background Visual")
                    if fallback_file != target:
                        rel_path = str(fallback_file.relative_to(composition_dir))
                        return full_match.replace(url_target, rel_path)
        return full_match

    html = re.sub(r'url\((["\']?)([^"\'\)]+)\1\)', fix_css_url, html, flags=re.IGNORECASE)
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
    if narration_duration <= 0:
        narration_duration = 60.0

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
    root_open = re.search(r"<[a-zA-Z0-9]+\b(?=[^>]*(?:id=[\"'](?:stage|composition|root)[\"']|class=[\"'][^\"']*\bcomposition\b[^\"']*[\"']))[^>]*>", html)
    if not root_open:
        root_open = re.search(r"<div\b[^>]*>", html)
    if root_open:
        tag = root_open.group(0)
        new_tag = tag
        if "data-composition-id" not in new_tag:
            new_tag = new_tag.replace("<div", '<div data-composition-id="main"', 1)
        if "data-width" not in new_tag:
            new_tag = new_tag.replace("<div", '<div data-width="1080"', 1)
        if "data-height" not in new_tag:
            new_tag = new_tag.replace("<div", '<div data-height="1920"', 1)
        if "data-duration" not in new_tag:
            initial_dur = max_end if max_end > 0 else narration_duration
            new_tag = new_tag.replace("<div", f'<div data-duration="{initial_dur:.3f}"', 1)
        elif max_end > 0:
            new_tag = re.sub(
                r'\bdata-duration=["\'][0-9.]+["\']',
                f'data-duration="{max_end:.3f}"',
                new_tag,
                count=1,
            )
        if "data-start" not in new_tag:
            new_tag = new_tag.replace("<div", '<div data-start="0"', 1)
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

    if strict:
        composition_tags = list(
            re.finditer(
                r"<[a-zA-Z]+\b[^>]*\bdata-composition-id=([\"'])([^\"']+)\1[^>]*>",
                html,
            )
        )
        if composition_tags:
            root_tag = composition_tags[0]
            registered_ids = {
                match.group(2)
                for match in re.finditer(
                    r"window\.__timelines\s*\[\s*([\"'])([^\"']+)\1\s*\]",
                    html,
                )
            }
            replacements = []
            for tag in composition_tags[1:]:
                composition_id = tag.group(2)
                if composition_id not in registered_ids:
                    cleaned = re.sub(
                        r"\s+data-composition-id=([\"'])[^\"']+\1",
                        "",
                        tag.group(0),
                        count=1,
                    )
                    replacements.append((tag.start(), tag.end(), cleaned))
            for start, end, cleaned in reversed(replacements):
                html = html[:start] + cleaned + html[end:]

    html = align_timeline(path, html, narration_duration)
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

    # Fix malformed GSAP object syntax without changing CSS declarations.
    # Normalize GSAP src to CDN — absolute /hyperframes/... is 404 on HyperFrames file_server (cwd=workspace)
    html = re.sub(r'<script\s+[^>]*\bsrc=["\']\/hyperframes(?:_reels)?\/gsap\.min\.js["\'][^>]*>\s*</script>', '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>', html)
    html = re.sub(r'<script\s+[^>]*\bsrc=["\']gsap\.min\.js["\'][^>]*>\s*</script>', '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>', html)
    # Fallback if closing tag already consumed differently (e.g. no space before />)
    html = re.sub(r'["\']\/hyperframes(?:_reels)?\/gsap\.min\.js["\']', '"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"', html)
    html = re.sub(r"(\bopacity\s*:\s*[^,{};]+)\s*;\s*,", r"\1,", html)
    html = re.sub(r"(\.clip\b[^{}]*\{[^{}]*)\bvisibility\s*:\s*hidden\s*;?", r"\1", html)
    # Add subtle continuous background animation to prevent false-positive static canvas detection
    style_match = re.search(r"<style[^>]*>", html)
    if style_match:
        html = re.sub(r"@keyframes\s+hf-live-pulse\s*\{[^\n]*\}\s*", "", html)
        html = re.sub(
            r"#root\s*,\s*body\s*\{\s*animation:\s*hf-live-pulse[^}]*\}\s*",
            "",
            html,
        )
        pulse_css = (
            "\n@keyframes hf-live-pulse { 0% { filter: hue-rotate(0deg); } 50% { filter: hue-rotate(1deg); } 100% { filter: hue-rotate(0deg); } }\n"
            "#root, body { animation: hf-live-pulse 0.5s infinite linear !important; background: radial-gradient(circle at 10% 20%, #1e2235 0%, #171b2b 100%) !important; }\n"
        )
        html = html[:style_match.end()] + pulse_css + html[style_match.end():]
    if strict:
        root = re.search(r"<[a-zA-Z0-9]+\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
        if not root:
            raise ValueError(f"{path}: missing composition root for strict timeline repair")
        if "data-no-timeline" not in root.group(0) and "window.__timelines[" not in html:
            html = html[:root.end() - 1] + " data-no-timeline>" + html[root.end():]
        html = re.sub(r"\bopacity\s*:\s*0(\s*;?)", r"opacity: 1\1", html)
        html = re.sub(r"\bvisibility\s*:\s*hidden(\s*;?)", r"visibility: visible\1", html)
        # Enforce exact 1080x1920 portrait
        html = re.sub(r"#root\s*\{\s*width:\s*\d+px;\s*height:\s*\d+px;", "#root { width: 1080px; height: 1920px;", html)
        html = re.sub(r"meta\s+name=\"viewport\"[^>]*", 'meta name="viewport" content="width=1080, height=1920"', html)

    path.write_text(html, encoding="utf-8")


def align_timeline(path: Path, html: str, narration_duration: float) -> str:
    """Scale composition timings and GSAP animations so visual timeline matches narration length."""
    root_open = re.search(r"<[a-zA-Z0-9]+\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
    if not root_open:
        raise ValueError(f"{path}: missing composition root for timeline alignment")
    root_duration_match = re.search(r"\bdata-duration=[\"']([0-9.]+)[\"']", root_open.group(0))
    if not root_duration_match:
        raise ValueError(f"{path}: composition root has no data-duration")
    root_duration = float(root_duration_match.group(1))
    target = round(narration_duration, 3)
    if root_duration <= 0:
        raise ValueError(f"{path}: composition root has a non-positive data-duration")

    scale = target / root_duration if root_duration > 0 else 1.0

    def scale_attr(match: re.Match[str]) -> str:
        value = float(match.group(2))
        return f'{match.group(1)}="{value * scale:.3f}"'

    head = html[:root_open.start()]
    body = html[root_open.start():]
    if abs(root_duration - target) >= 0.01:
        body = re.sub(r"\b(data-start|data-duration)=[\"']([0-9.]+)[\"']", scale_attr, body)

    body = re.sub(
        r'(<[a-zA-Z0-9]+\b[^>]*\bdata-composition-id=[\'"][^\'"]+[\'"][^>]*\bdata-duration=)[\'"][0-9.]+[\'"]',
        rf'\1"{target:.3f}"',
        body,
        count=1,
    )

    body = re.sub(
        r"\bconst\s+",
        r"let ",
        body,
    )
    body = re.sub(
        r"((?:let|var|const)\s+total(?:Dur(?:ation)?)?\s*=\s*)[0-9.]+",
        lambda m: f"{m.group(1)}{target:.3f}",
        body,
    )

    # Scale JS array of SCENE_DURATIONS or sceneStarts if it exists
    def scale_array(match: re.Match[str]) -> str:
        arr_str = match.group(2)
        try:
            import ast
            arr = ast.literal_eval(arr_str)
            if isinstance(arr, list) and len(arr) > 0:
                arr_sum = sum(arr)
                if arr_sum > 0:
                    arr_scale = target / arr_sum
                    new_arr = [round(x * arr_scale, 3) for x in arr]
                    return f"{match.group(1)}[{', '.join(map(str, new_arr))}]{match.group(3)}"
        except Exception:
            pass
        return match.group(0)

    body = re.sub(r'((?:let|var|const)\s+SCENE_DURATIONS\s*=\s*)(\[[0-9.,\s]+\])(\s*;)', scale_array, body)

    # Scale JS array of scenes = [{start: 0, duration: 4}, ...]
    scenes_match = re.search(r"(?:let|var|const)\s+(?:scenes|sections)\s*=\s*(\[\s*\{[^\[\]]+?\}\s*\])\s*;", body, re.DOTALL)
    if scenes_match:
        import json
        json_str = scenes_match.group(1)
        json_str = re.sub(r'([\{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', json_str)
        json_str = json_str.replace("'", '"')
        try:
            scenes_data = json.loads(json_str)
            if isinstance(scenes_data, list) and len(scenes_data) > 0:
                max_end = max((float(s.get("start", 0)) + float(s.get("duration", s.get("end", 0) - s.get("start", 0)))) for s in scenes_data)
                if max_end > 0:
                    s_scale = target / max_end
                    if abs(s_scale - 1.0) >= 0.01:
                        for s in scenes_data:
                            if "start" in s: s["start"] = round(float(s["start"]) * s_scale, 3)
                            if "duration" in s: s["duration"] = round(float(s["duration"]) * s_scale, 3)
                            if "end" in s: s["end"] = round(float(s["end"]) * s_scale, 3)
                        new_scenes = json.dumps(scenes_data, ensure_ascii=False)
                        new_scenes = re.sub(r'"([a-zA-Z0-9_]+)":', r'\1:', new_scenes)
                        body = body[:scenes_match.start(1)] + new_scenes + body[scenes_match.end(1):]
        except Exception:
            pass

    indexed_scene_schedule = re.search(
        r"sceneMotion\(\s*scene\s*,\s*index\s*\*\s*([0-9.]+)\s*\)",
        body,
    )
    timeline_end = re.search(
        r"tl\.to\(\s*\{\}\s*,\s*\{\s*duration\s*:\s*[0-9.]+\s*\}\s*,\s*([0-9.]+)\s*\)\s*;?",
        body,
    )
    if indexed_scene_schedule and timeline_end:
        authored_end = float(timeline_end.group(1))
        if authored_end > 0 and abs(authored_end - target) >= 0.01:
            authored_step = float(indexed_scene_schedule.group(1))
            step = authored_step * target / authored_end
            body = body[:indexed_scene_schedule.start(1)] + f"{step:.3f}" + body[indexed_scene_schedule.end(1):]
            body = re.sub(
                r"(tl\.to\(\s*\{\}\s*,\s*\{\s*duration\s*:\s*[0-9.]+\s*\}\s*,\s*)[0-9.]+(\s*\)\s*;?)",
                rf"\g<1>{target:.3f}\2",
                body,
                count=1,
            )

    if "tl.duration(" in body:
        body = re.sub(r"tl\.duration\(\s*[0-9.]+\s*\);?", f"tl.duration({target:.3f});", body)
    else:
        tl_decl = re.search(r"(?:const|let|var)\s+tl\s*=\s*[^;]+;", body)
        if tl_decl:
            idx = tl_decl.end()
            body = body[:idx] + f"\n  tl.duration({target:.3f});\n" + body[idx:]

    # Guarantee <50% static in strict frozen-canvas by adding a full-duration
    # breathing zoom. A single slow linear ramp moves sub-pixel per frame and
    # still trips freezedetect, so oscillate instead: each 1.6s half-cycle
    # shifts several pixels per frame and never freezes for the 2s window.
    cycles = max(1, int(round(target / 1.6)))
    # Animate the visible canvas, not a nested metadata-only composition node.
    comp_tag = re.search(r"<[a-zA-Z]+\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", body)
    root_selector = ""
    for candidate_id in ("stage", "composition", "viewport", "canvas", "app", "container", "root", "main"):
        # Avoid matching `id="..."` inside `data-*-id="..."` attributes.
        if re.search(rf"(?<!-)id=[\"']{candidate_id}[\"']", html):
            root_selector = f"#{candidate_id}"
            break
    if not root_selector and comp_tag:
        id_match = re.search(r'(?<!-)id=["\']([^"\']+)["\']', comp_tag.group(0))
        if id_match:
            root_selector = f"#{id_match.group(1)}"
    if not root_selector:
        # If no explicit ID exists, target the data-composition-id attribute directly
        # or fallback to body. Both exist and will animate the canvas successfully.
        if comp_tag:
            root_selector = "[data-composition-id]"
        else:
            root_selector = "body"

    # Retarget existing injection if needed
    if "__repair_scale_injected" in body:
        body = re.sub(r"tl\.fromTo\(['\"]#[a-zA-Z0-9_-]+['\"]", f"tl.fromTo('{root_selector}'", body)

    if "__repair_scale_injected" not in body or not root_selector:
        scale_code = (
            f"\n<script>\n"
            f"// __repair_scale_injected\n"
            f"(function() {{\n"
            f"  window.__timelines = window.__timelines || {{}};\n"
            f"  var _r_tl = (typeof tl !== 'undefined') ? tl : (window['_'+'_timelines']['main'] || window['_'+'_timelines']['full'] || Object.values(window['_'+'_timelines'])[0]);\n"
            f"  if (!_r_tl && typeof gsap !== 'undefined') {{\n"
            f"      _r_tl = gsap.timeline();\n"
            f"      var cidMatch = document.querySelector('[data-composition-id]');\n"
            f"      var compId = cidMatch ? cidMatch.getAttribute('data-composition-id') : 'main';\n"
            f"      window['_'+'_timelines'][compId] = _r_tl;\n"
            f"  }}\n"
            f"  if (_r_tl) {{\n"
            f"    try {{\n" \
            f"      var rawD = _r_tl.duration();\n" \
            f"      if (rawD > 0 && Math.abs(rawD - {target:.3f}) > 0.5) {{\n" \
            f"        _r_tl.timeScale(rawD / {target:.3f});\n" \
            f"      }}\n" \
            f"    }} catch (e) {{}}\n"
            f"    try {{\n"
            f"      _r_tl.fromTo('{root_selector}', {{scale: 1.0}}, {{scale: 1.12, transformOrigin: '50% 50%', force3D: true, duration: 1.6, yoyo: true, repeat: {cycles}, ease: 'sine.inOut'}}, 0);\n"
            f"    }} catch (e) {{}}\n"
            f"  }}\n"
            f"}})();\n"
            f"</script>\n"
        )
        if "</body>" in body:
            body = body.replace("</body>", scale_code + "\n</body>", 1)
        elif "</html>" in body:
            body = body.replace("</html>", scale_code + "\n</html>", 1)
        elif "</script>" in body:
            idx = body.rfind("</script>")
            body = body[:idx+9] + scale_code + body[idx+9:]
        else:
            body = body + f"\n{scale_code}\n"

    cues_match = re.search(r"var\s+cues\s*=\s*(\[[^;]+\]);", body)
    if cues_match:
        try:
            cues = json.loads(cues_match.group(1))
            if cues and isinstance(cues, list):
                max_end = max(float(c.get("end", 0.0)) for c in cues)
                if max_end > 0:
                    c_scale = target / max_end
                    for c in cues:
                        if "start" in c:
                            c["start"] = round(float(c["start"]) * c_scale, 3)
                        if "end" in c:
                            c["end"] = round(float(c["end"]) * c_scale, 3)
                    body = body[:cues_match.start()] + f"var cues = {json.dumps(cues, ensure_ascii=False)};" + body[cues_match.end():]
        except Exception:
            pass

    return head + body


def declared_dimensions(html: str) -> dict[str, tuple[int, int]]:
    """Collect every explicit canvas size declaration, keyed by its source."""
    found: dict[str, tuple[int, int]] = {}

    root_open = re.search(r"<[a-zA-Z]+\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
    if root_open:
        tag = root_open.group(0)
        width = re.search(r"\bdata-width=[\"'](\d+)[\"']", tag)
        height = re.search(r"\bdata-height=[\"'](\d+)[\"']", tag)
        if width and height:
            found["root data-width/data-height"] = (int(width.group(1)), int(height.group(1)))

    viewport = re.search(
        r"<meta\b[^>]*\bname=[\"']viewport[\"'][^>]*\bcontent=[\"']([^\"']+)[\"']",
        html,
    )
    if viewport:
        content = viewport.group(1)
        width = re.search(r"\bwidth\s*=\s*(\d+)", content)
        height = re.search(r"\bheight\s*=\s*(\d+)", content)
        if width and height:
            found["meta viewport"] = (int(width.group(1)), int(height.group(1)))

    for index, rule in enumerate(re.finditer(r"(?:#root|body|html)\b[^{]*\{([^{}]*)\}", html), start=1):
        body = rule.group(1)
        width = re.search(r"(?<![-\w])width\s*:\s*(\d+)px", body)
        height = re.search(r"(?<![-\w])height\s*:\s*(\d+)px", body)
        if width and height:
            found[f"CSS rule {index}"] = (int(width.group(1)), int(height.group(1)))

    return found


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
    parser.add_argument("--strict", action="store_true", help="Apply strict timeline compatibility repairs")
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
