"""Validation helpers and DOM inspection for HyperFrames compositions."""

from __future__ import annotations

import html as html_lib
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata

from tools.narration_text import _FORBIDDEN_PATTERN as _MALFORMED_TEXT_PATTERN

PORTRAIT_WIDTH = 1080
PORTRAIT_HEIGHT = 1920

VIETNAMESE_GLYPH_SENTINELS = "ĐđĂăÂâÊêÔôƠơƯưÁáÀàẢảÃãẠạẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẾếỀềỂểỄễỆệỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỨứỪừỬửỮữỰựÝýỲỳỶỷỸỹỴỵ"


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


def _find_string_literal_end(source: str, index: int, quote: str) -> int:
    end = index + 1
    src_len = len(source)
    while end < src_len:
        if source[end] == "\\":
            end += 2
        elif source[end] == quote:
            return end + 1
        else:
            end += 1
    return end


def _find_noncode_range(source: str, index: int) -> int:
    if source.startswith("//", index):
        end = source.find("\n", index)
        return len(source) if end < 0 else end
    if source.startswith("/*", index):
        close = source.find("*/", index + 2)
        return len(source) if close < 0 else close + 2
    if source[index] in "'\"`":
        return _find_string_literal_end(source, index, source[index])
    return -1


def _mask_javascript_noncode(source: str) -> str:
    """Blank comments and quoted literals while retaining source offsets."""
    chars = list(source)
    index = 0
    src_len = len(source)
    while index < src_len:
        end = _find_noncode_range(source, index)
        if end == -1:
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
    if not timelines and re.search(r"\b(?:requestAnimationFrame|setInterval)\s*\(|window\s*\.\s*__timelines\b", code):
        raise ValueError(
            f"{path}: GSAP timeline is not registered with gsap.timeline({{ paused: true }}); "
            "regenerate with a paused GSAP timeline registered on window.__timelines['main']"
        )
    if re.search(r"\b(?:requestAnimationFrame|setInterval)\s*\(", code):
        raise ValueError(
            f"{path}: requestAnimationFrame/setInterval loops are not seek-safe; "
            "regenerate using only a paused GSAP timeline registered on window.__timelines['main']"
        )
    for match in timelines:
        if re.search(r"\bpaused\s*:\s*true\b", match.group(1)) is None:
            raise ValueError(f"{path}: GSAP timelines must be created with paused: true for deterministic seeking")

    for _, attrs, _ in dom.nodes:
        composition_id = attrs.get("data-composition-id")
        if not isinstance(composition_id, str) or "data-no-timeline" in attrs:
            continue
        registration = re.compile(
            r"window\s*\.\s*__timelines\s*(?:\[\s*(['\"])"
            + re.escape(composition_id)
            + r"\1\s*\]|\.\s*"
            + re.escape(composition_id)
            + r"\b)"
        )
        registered = any(
            code[match.start():match.start() + len("window")].strip().startswith("window")
            for match in registration.finditer(inline)
        )
        if timelines and not registered:
            raise ValueError(f"{path}: GSAP timeline is not registered for composition {composition_id!r}; regenerate with window.__timelines registration")


def validate_dimensions(path: Path, html: str, locale: str = "vi-VN") -> list[str]:
    """Reject any composition that does not declare the expected canvas dimensions."""
    is_en = locale == "en-US"
    is_landscape = is_en and path.parent.name == "hyperframes"
    expected = (1920, 1080) if is_landscape else (PORTRAIT_WIDTH, PORTRAIT_HEIGHT)
    found = declared_dimensions(html)
    if not found:
        canvas_str = "1920x1080" if is_landscape else f"{PORTRAIT_WIDTH}x{PORTRAIT_HEIGHT}"
        return [
            f"{path}: cannot determine canvas dimensions; declare "
            f"{canvas_str} on the composition root, meta viewport, and #root CSS"
        ]

    distinct = set(found.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{source}={w}x{h}" for source, (w, h) in sorted(found.items()))
        return [f"{path}: conflicting canvas dimensions ({detail})"]

    width, height = distinct.pop()
    if (width, height) != expected:
        canvas_type = "landscape" if is_landscape else "portrait"
        sources = ", ".join(sorted(found))
        return [
            f"{path}: expected {expected[0]}x{expected[1]} {canvas_type} canvas, "
            f"got {width}x{height} (declared by {sources})"
        ]
    return []


def validate_html(path: Path) -> list[str]:
    errors: list[str] = []
    html = path.read_text(encoding="utf-8")
    locale = "vi-VN"
    try:
        from lib.artifact_paths import resolve_project_locale
        locale = resolve_project_locale(path.parent.parent)
    except Exception:
        pass

    errors.extend(validate_dimensions(path, html, locale=locale))
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
    visible_text = unicodedata.normalize("NFC", html_lib.unescape(html))
    if locale == "vi-VN" and VIETNAMESE_GLYPH_SENTINELS and not any(ch in visible_text for ch in VIETNAMESE_GLYPH_SENTINELS):
        errors.append(f"{path}: no Vietnamese diacritic text found for glyph smoke validation")
    malformed = sorted(set(_MALFORMED_TEXT_PATTERN.findall(html)))
    if malformed:
        codes = ", ".join(f"U+{ord(ch):04X}" for ch in malformed)
        errors.append(f"{path}: composition text contains unrenderable characters: {codes}")
    return errors
