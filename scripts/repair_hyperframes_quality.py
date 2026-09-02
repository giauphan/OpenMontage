#!/usr/bin/env python3
"""Repair and validate HyperFrames assets before rendering."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
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

    # Ensure composition root has required attributes
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
    if "overflow: hidden" not in html:
        root_match = re.search(r"(#root|body|html)\s*\{[^{}]*\}", html)
        if root_match:
            rule = root_match.group(0)
            rule = rule[:-1].rstrip() + " overflow: hidden; }"
            html = html[:root_match.start()] + rule + html[root_match.end():]
        else:
            raise ValueError(f"{path}: missing viewport CSS rule for clipping guard")
    # For reels composition, bind to reels narration file
    narration_src = "assets/narration_reels.mp3" if "hyperframes_reels" in str(path) else "assets/narration.mp3"
    html = re.sub(
        r"(<audio\b(?=[^>]*\bid=[\"']narration[\"'])[^>]*\bsrc=)[\"'][^\"']*[\"']",
        rf'\1"{narration_src}"',
        html,
    )
    if not re.search(r"<audio\b[^>]*\bid=[\"']narration[\"']", html):
        root_open = re.search(r"<div\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
        if not root_open:
            raise ValueError(f"{path}: missing composition root for narration audio binding")
        # Use reels narration for reels composition
        narration_tag = NARRATION_TAG.replace('assets/narration.mp3', narration_src)
        html = html[:root_open.end()] + "\n    " + narration_tag + html[root_open.end():]
    html = align_timeline(path, html, narration_duration)

    # Remove GSAP display tweens that break HyperFrames internal visibility engine
    # HyperFrames controls visibility based on timeline, GSAP tweens override this and cause blank renders
    # Remove .set() calls with display property
    html = re.sub(
        r"\.set\(['\"]#scene-\d+['\"]\s*,\s*\{\s*display\s*:\s*['\"](?:none|flex|block)['\"]\s*\}\s*,\s*[^)]*\)",
        "",
        html
    )
    # Remove .to() calls with display property
    html = re.sub(
        r"\.to\(['\"]#scene-\d+['\"]\s*,\s*\{[^}]*display\s*:\s*['\"](?:none|flex|block)['\"]\s*[^}]*\}\s*,\s*[^)]*\)",
        "",
        html
    )
    # Remove tl.addLabel() calls that reference scene visibility
    html = re.sub(r"tl\.addLabel\(['\"]#scene-\d+['\"][^)]*\);?", "", html)
    # Fix malformed GSAP syntax: "opacity: 1;," → "opacity: 1,"
    html = re.sub(r"opacity:\s*1\s*;\s*,", "opacity: 1,", html)
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
            "#root, body { animation: hf-live-pulse 0.5s infinite linear !important; }\n"
        )
        html = html[:style_match.end()] + pulse_css + html[style_match.end():]
    if strict:
        root = re.search(r"<div\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
        if not root:
            raise ValueError(f"{path}: missing composition root for strict timeline repair")
        if "data-no-timeline" not in root.group(0):
            html = html[:root.end() - 1] + " data-no-timeline>" + html[root.end():]
        html = re.sub(r"\bopacity\s*:\s*0\s*;?", "opacity: 1;", html)
        html = re.sub(r"\bvisibility\s*:\s*hidden\s*;?", "visibility: visible;", html)

    path.write_text(html, encoding="utf-8")


def align_timeline(path: Path, html: str, narration_duration: float) -> str:
    """Scale composition timings so the visual timeline matches the narration length."""
    root_open = re.search(r"<div\b[^>]*\bdata-composition-id=[\"'][^\"']+[\"'][^>]*>", html)
    if not root_open:
        raise ValueError(f"{path}: missing composition root for timeline alignment")
    root_duration_match = re.search(r"\bdata-duration=[\"']([0-9.]+)[\"']", root_open.group(0))
    if not root_duration_match:
        raise ValueError(f"{path}: composition root has no data-duration")
    root_duration = float(root_duration_match.group(1))
    target = round(narration_duration, 2)
    if root_duration <= 0:
        raise ValueError(f"{path}: composition root has a non-positive data-duration")
    # Keep visual and narration timelines exactly aligned. A tolerance here can
    # leave a dead tail that the post-render duration gate correctly rejects.
    if abs(root_duration - target) < 0.01:
        return html
    scale = target / root_duration

    def scale_attr(match: re.Match[str]) -> str:
        value = float(match.group(2))
        return f'{match.group(1)}="{round(value * scale, 3)}"'

    head = html[:root_open.start()]
    body = html[root_open.start():]
    body = re.sub(r"\b(data-start|data-duration)=[\"']([0-9.]+)[\"']", scale_attr, body)
    body = re.sub(
        r"(const\s+totalDuration\s*=\s*)[0-9.]+",
        lambda m: f"{m.group(1)}{target}",
        body,
    )
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

    for index, rule in enumerate(re.finditer(r"#root\s*\{([^{}]*)\}", html), start=1):
        body = rule.group(1)
        width = re.search(r"(?<![-\w])width\s*:\s*(\d+)px", body)
        height = re.search(r"(?<![-\w])height\s*:\s*(\d+)px", body)
        if width and height:
            found[f"#root CSS rule {index}"] = (int(width.group(1)), int(height.group(1)))

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
    if "overflow: hidden" not in html:
        errors.append(f"{path}: missing viewport clipping guard")
    if VIETNAMESE_GLYPH_SENTINELS and not any(ch in html for ch in VIETNAMESE_GLYPH_SENTINELS):
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
        narration = assets / "narration.mp3"
        if not narration.is_file() or narration.stat().st_size == 0:
            composition_errors.append(f"{narration}: missing or empty narration audio asset")
        narration_duration = 0.0
        if narration.is_file() and narration.stat().st_size > 0:
            narration_duration = probe_duration(narration)
        if not composition_errors:
            try:
                patch_html(index, narration_duration)
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
