#!/usr/bin/env python3
"""Repair and validate HyperFrames assets before rendering."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FONT_CSS = """@font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Regular.ttf') format('truetype'); font-weight: 400; font-style: normal; font-display: block; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Bold.ttf') format('truetype'); font-weight: 700; font-style: normal; font-display: block; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-ExtraBold.ttf') format('truetype'); font-weight: 800; font-style: normal; font-display: block; }"""

REQUIRED_FONTS = (
    "BeVietnamPro-Regular.ttf",
    "BeVietnamPro-Bold.ttf",
    "BeVietnamPro-ExtraBold.ttf",
)

VIETNAMESE_GLYPH_SENTINELS = "ĐđĂăÂâÊêÔôƠơƯưÁáÀàẢảÃãẠạẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẾếỀềỂểỄễỆệỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỨứỪừỬửỮữỰựÝýỲỳỶỷỸỹỴỵ"


def patch_html(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
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
    html = re.sub(
        r"(<audio\b(?=[^>]*\bid=[\"']narration[\"'])[^>]*\bsrc=)[\"'][^\"']*[\"']",
        r'\1"assets/narration.mp3"',
        html,
    )
    path.write_text(html, encoding="utf-8")


def validate_html(path: Path) -> list[str]:
    errors: list[str] = []
    html = path.read_text(encoding="utf-8")
    required_bindings = (
        "font-family: 'BeVietnamPro'",
        "--font-heading: 'BeVietnamPro', Arial, sans-serif;",
        "--font-body: 'BeVietnamPro', Arial, sans-serif;",
    )
    for binding in required_bindings:
        if binding not in html:
            errors.append(f"{path}: missing {binding}")
    narration_tags = re.findall(r"<audio\b[^>]*\bid=[\"']narration[\"'][^>]*>", html)
    for tag in narration_tags:
        if not re.search(r"\bsrc=[\"']assets/narration\.mp3[\"']", tag):
            errors.append(f"{path}: narration audio src is empty or wrong")
    if "#app" not in html or "overflow: hidden" not in html:
        errors.append(f"{path}: missing viewport clipping guard")
    if VIETNAMESE_GLYPH_SENTINELS and not any(ch in html for ch in VIETNAMESE_GLYPH_SENTINELS):
        errors.append(f"{path}: no Vietnamese diacritic text found for glyph smoke validation")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair and validate HyperFrames font/audio bindings")
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()

    project_dir = args.project_dir
    errors: list[str] = []
    for composition in ("hyperframes", "hyperframes_reels"):
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
        if not composition_errors:
            try:
                patch_html(index)
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
