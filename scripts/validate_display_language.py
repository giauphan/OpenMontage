#!/usr/bin/env python3
"""Local Vietnamese and English static HTML/subtitle gate, not OCR or runtime JS validation.

Checks text nodes grouped by block, excluding non-rendered HTML containers and
explicitly hidden elements. CSS selectors, generated content, canvas, images and
JavaScript are not evaluated. Animated opacity/visibility is deliberately not
used to exclude text: an initially invisible headline may appear later.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.narration_text import check_vietnamese_prose
from lib.artifact_paths import is_english_locale
from lib.language_validation import get_language_validator

_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_BLOCKS = set("address article aside blockquote div dl dt dd figcaption footer form h1 h2 h3 h4 h5 h6 header li main nav ol p pre section table td th tr ul text".split())
_EXCLUDED = {"head", "script", "style", "template", "title", "desc"}
_VOID = set("area base br col embed hr img input link meta param source track wbr".split())
_SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}


def validate_display_text(text: str, locale: str = "vi-VN") -> list[str]:
    """Apply the locale-aware prose checker with narrow standalone-label exceptions.

    Proper-name recognition is lexical, not entity recognition. Short capitalized
    names are allowed only if the shared checker found no English stop words.
    """
    if is_english_locale(locale):
        return get_language_validator(locale).validate_prose(text)

    text = unicodedata.normalize("NFC", " ".join(text.split()))
    if not text:
        return []
    words = _WORDS.findall(text)
    if not words:
        return []  # dates, percentages, punctuation and numeric labels
    errors = check_vietnamese_prose(text)
    if not errors:
        return []
    if len(words) == 1 and words[0].isupper() and len(words[0]) <= 6:
        return []
    if any("English" in error for error in errors):
        return errors
    if len(words) <= 4 and all(word[0].isupper() and not word.isupper() for word in words):
        return []
    if len(words) <= 3 and all(word.isupper() and len(word) <= 6 for word in words):
        return []
    return errors


class VisibleTextParser(HTMLParser):
    """Conservative static text extraction; inline markup stays in its block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.parts: list[str] = []
        self.blocks: list[tuple[int, str]] = []
        self.line = 1
        self.tracks: list[str] = []

    def flush(self) -> None:
        text = " ".join("".join(self.parts).split())
        if text:
            self.blocks.append((self.line, text))
        self.parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in _BLOCKS or tag == "br":
            self.flush()
        hidden = bool(self.stack and self.stack[-1][1]) or tag in _EXCLUDED
        hidden = hidden or "hidden" in attributes or bool(re.search(
            r"(?:^|;)\s*display\s*:\s*none\s*(?:!important\s*)?(?:;|$)",
            attributes.get("style") or "", re.I,
        ))
        if tag == "track" and attributes.get("src"):
            self.tracks.append(attributes["src"])
        if tag not in _VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCKS:
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not self.stack or not self.stack[-1][1]:
            if not self.parts:
                self.line = self.getpos()[0]
            self.parts.append(data)


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError("missing or empty static text source")
    return text


def _text_errors(path: Path, blocks: list[tuple[int, str]], locale: str = "vi-VN") -> list[str]:
    errors = []
    for line, text in blocks:
        reasons = validate_display_text(text, locale=locale)
        if reasons:
            expected_lang = "English" if is_english_locale(locale) else "Vietnamese"
            errors.append(f"{path}:{line}: display text must be {expected_lang}: {text[:180]!r} ({'; '.join(reasons)})")
    return errors


def _subtitle_blocks(path: Path) -> list[tuple[int, str]]:
    text = _read(path)
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("word_timestamps", data.get("segments", data.get("cues", [])))
        if not isinstance(data, list) or not data:
            raise ValueError("no subtitle entries")
        words = []
        for entry in data:
            if not isinstance(entry, dict):
                raise ValueError("invalid subtitle entry")
            value = entry.get("text", entry.get("word"))
            if not isinstance(value, str) or not value.strip():
                raise ValueError("missing subtitle text")
            words.append(value)
        # Word-level exports need context, not per-word language detection.
        return [(1, " ".join(words))]
    if path.suffix.lower() in {".ass", ".ssa"}:
        blocks = []
        for line, value in enumerate(text.splitlines(), 1):
            if value.startswith("Dialogue:"):
                fields = value.split(",", 9)
                if len(fields) != 10:
                    raise ValueError("invalid ASS dialogue")
                value = re.sub(r"\{[^}]*\}", "", fields[-1])
                blocks.append((line, value.replace(r"\N", " ").replace(r"\n", " ")))
        return blocks
    blocks = []
    for cue in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = cue.splitlines()
        timing = next((i for i, value in enumerate(lines) if "-->" in value), None)
        if timing is not None:
            text_lines = [l for l in lines[timing + 1:] if l.strip()]
            if text_lines:
                blocks.append((timing + 1, " ".join(text_lines)))
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--locale", default="vi-VN", help="Target locale (en-US or vi-VN)")
    args = parser.parse_args()

    all_errors: list[str] = []
    for target in args.paths:
        if not target.is_file():
            all_errors.append(f"File not found: {target}")
            continue
        try:
            if target.suffix.lower() in _SUBTITLE_SUFFIXES or target.name.endswith(".json"):
                blocks = _subtitle_blocks(target)
            else:
                parser_inst = VisibleTextParser()
                parser_inst.feed(_read(target))
                parser_inst.flush()
                blocks = parser_inst.blocks
            all_errors.extend(_text_errors(target, blocks, locale=args.locale))
        except Exception as exc:
            all_errors.append(f"{target}: failed to parse text ({exc})")

    for err in all_errors:
        print(err, file=sys.stderr)
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
