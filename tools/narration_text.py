"""Shared preparation of Vietnamese narration and on-screen display text.

The stored editorial script keeps its original wording. Only the text handed to
the Vietnamese TTS voice is rewritten, so that English technical terminology is
spoken with Vietnamese phonetics instead of switching to an English voice.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

LEXICON_PATH = Path(__file__).resolve().parents[1] / "config" / "vietnamese_tts_lexicon.json"

# Default pronunciation lexicon. config/vietnamese_tts_lexicon.json (gitignored)
# may override/extend this at runtime. Applied to TTS input only; the stored
# script and on-screen captions keep their original wording. Matching is
# case-insensitive, longest-source-first, word-boundary aware.
_DEFAULT_TERMS: dict[str, str] = {
    "TypeScript": "Thai-Sờ-Cờ-ríp",
    "JavaScript": "Java-Sờ-Cờ-ríp",
    "PostgreSQL": "Pốt-grét S-Q-L",
    "MySQL": "My S-Q-L",
    "GraphQL": "Gráp Q-L",
    "Kubernetes": "Ku-bơ-nê-tít",
    "Docker": "Đóc-cơ",
    "Python": "Pai-thần",
    "Node.js": "Nốt Jây-ét",
    "React": "Ri-át",
    "GitHub": "Gít-hấp",
    "OpenAI": "Ô-pừn Ây Âi",
    "ChatGPT": "Chát G P T",
    "API": "Ây Pi Ây",
    "REST API": "Rét Ây Pi Ây",
    "SDK": "Ét-Đi-Kây",
    "CLI": "Xi-eo-Ai",
    "URL": "Iu-a-eo",
    "HTTP": "Hắt-Ti-Ti-Pi",
    "HTTPS": "Hắt-Ti-Ti-Pi-Ét",
    "JSON": "Jây-sần",
    "CSS": "Xi-Ét-Ét",
    "HTML": "Hắt-Ti-Em-eo",
    "SQL": "Ét-Q-eo",
    "AI": "Ây Âi",
    "machine learning": "meo-sin lơ-ning",
    "cloud": "cờ-lao",
    "framework": "phrêm-uốc",
    "backend": "béc-en",
    "frontend": "phờ-ron-en",
}

# Characters that never belong in narration or rendered text: C0/C1 controls
# (tab/newline are folded to spaces first), zero-width and bidi formatting
# characters, the byte-order mark, and the Unicode replacement character.
_FORBIDDEN_PATTERN = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    "​-‏‪-‮⁠-⁤⁦-⁩"
    "﻿�]"
)

_ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")


def _load_lexicon() -> list[tuple[str, str]]:
    terms = dict(_DEFAULT_TERMS)
    if LEXICON_PATH.is_file():
        data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
        override = data.get("terms")
        if not isinstance(override, dict):
            raise ValueError(f"{LEXICON_PATH}: 'terms' must be an object")
        terms.update(override)
    # Longest source first so multi-word terms win over their components.
    return sorted(terms.items(), key=lambda item: (-len(item[0]), item[0].lower()))


def normalize_text(text: str) -> str:
    """NFC-normalise, fold whitespace, and reject unrenderable characters."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = re.sub(r"[\t\r\n]+", " ", normalized)
    normalized = normalized.replace(" ", " ")
    forbidden = sorted(set(_FORBIDDEN_PATTERN.findall(normalized)))
    if forbidden:
        codes = ", ".join(f"U+{ord(ch):04X}" for ch in forbidden)
        raise ValueError(f"text contains unrenderable characters: {codes}")
    return re.sub(r" {2,}", " ", normalized).strip()


def _spell_acronym(match: re.Match[str]) -> str:
    return " ".join(match.group(0))


def localize_pronunciation(text: str, lexicon: list[tuple[str, str]] | None = None) -> str:
    """Rewrite approved English technical terms into Vietnamese spoken forms.

    All lexicon terms are matched in a single left-to-right pass so a rewritten
    term is never re-scanned; unknown English words are left untouched, and only
    residual all-caps acronyms are spelled out.
    """
    entries = _load_lexicon() if lexicon is None else lexicon
    entries = [(src, spoken) for src, spoken in entries if src]
    if not entries:
        return _ACRONYM_PATTERN.sub(_spell_acronym, text)

    def one_pattern(src: str) -> str:
        left = r"\b" if src[0].isalnum() else ""
        right = r"\b" if src[-1].isalnum() else ""
        return left + re.escape(src) + right

    combined = re.compile("|".join(one_pattern(src) for src, _ in entries), re.IGNORECASE)
    spoken_by_lower = {src.lower(): spoken for src, spoken in entries}

    protected: list[str] = []

    def replace(match: re.Match[str]) -> str:
        protected.append(spoken_by_lower[match.group(0).lower()])
        return f"{len(protected) - 1}"

    localized = combined.sub(replace, text)
    localized = _ACRONYM_PATTERN.sub(_spell_acronym, localized)
    return re.sub(r"(\d+)", lambda m: protected[int(m.group(1))], localized)


def prepare_narration(text: str) -> str:
    """Full narration preparation: normalise, localise, then re-fold spacing."""
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("narration text is empty after normalization")
    localized = localize_pronunciation(normalized)
    return re.sub(r" {2,}", " ", localized).strip()


def validate_display_text(text: str) -> list[str]:
    """Return human-readable reasons why ``text`` would render incorrectly."""
    try:
        normalize_text(text)
    except ValueError as exc:
        return [str(exc)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare Vietnamese narration text for TTS")
    parser.add_argument("--in-file", type=Path, help="Read source text from this file instead of stdin")
    parser.add_argument("--out-file", type=Path, help="Write prepared text here instead of stdout")
    args = parser.parse_args(argv)

    source = args.in_file.read_text(encoding="utf-8") if args.in_file else sys.stdin.read()
    try:
        prepared = prepare_narration(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.out_file:
        args.out_file.write_text(prepared + "\n", encoding="utf-8")
    else:
        sys.stdout.write(prepared + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
