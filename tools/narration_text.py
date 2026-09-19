"""Shared preparation of Vietnamese narration and on-screen display text.

The stored editorial script keeps its original wording. Only the text handed to
the Vietnamese TTS voice is rewritten to handle English technical terminology.

Two modes:
1. Vietnamese phonetics (default): Transliterates English terms to Vietnamese spelling
   so Vietnamese-only TTS engines (FPT, VBee, Edge) can pronounce them.
2. SSML with IPA (premium): Uses true International Phonetic Alphabet in <phoneme>
   tags for authentic English pronunciation with multilingual TTS (Google Cloud,
   ElevenLabs, Azure Speech).
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
    "OpenAI": "Ô-pừn ây-ai",
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
    "AI": "ây-ai",
    "CPU": "Xi-Pi-Yu",
    "GPU": "Ghi-Pi-Yu",
    "CUDA": "Cu-đa",
    "3D": "ba đê",
    "2.5D": "hai phẩy năm đê",
    "HBM": "hê-bê-em",
    "HBM3": "hê-bê-em ba",
    "zHBM": "di-hê-bê-em",
    "machine learning": "meo-sin lơ-ning",
    "cloud": "cờ-lao",
    "framework": "phrêm-uốc",
    "backend": "béc-en",
    "frontend": "phờ-ron-en",
}

# True International Phonetic Alphabet (IPA) for English technical terms.
# Used when TTS engine supports SSML <phoneme> tags for authentic English voice.
# IPA source: Standard American English pronunciation (GA), verified against major dictionaries.
_IPA_TERMS: dict[str, str] = {
    # Hardware & Architecture
    "CUDA": "ˈkuː.də",
    "CPU": "ˌsiː piː ˈjuː",
    "GPU": "ˌdʒiː piː ˈjuː",
    "3D": "θriː diː",
    "2.5D": "tuː pɔɪnt faɪv diː",
    "HBM": "eɪtʃ biː em",
    "HBM3": "eɪtʃ biː em θriː",
    "zHBM": "ziː eɪtʃ biː em",

    # Programming Languages
    "Python": "ˈpaɪ.θɑːn",
    "JavaScript": "ˈdʒɑː.və.skrɪpt",
    "TypeScript": "ˈtaɪp.skrɪpt",
    "Node.js": "noʊd dʒeɪ ɛs",
    "React": "riːˈækt",

    # Databases
    "PostgreSQL": "ˈpoʊst.ɡrɛs ˌɛs kjuː ˈɛl",
    "MySQL": "maɪ ˌɛs kjuː ˈɛl",
    "GraphQL": "ˈɡræf kjuː ˈɛl",
    "SQL": "ˌɛs kjuː ˈɛl",

    # APIs & Protocols
    "API": "ˌeɪ piː ˈaɪ",
    "REST API": "ɹɛst ˌeɪ piː ˈaɪ",
    "HTTP": "ˌeɪtʃ tiː tiː ˈpiː",
    "HTTPS": "ˌeɪtʃ tiː tiː ˈpiː ɛs",
    "URL": "ˌjuː ɑːr ˈɛl",

    # Tools & Platforms
    "Docker": "ˈdɑː.kɚ",
    "GitHub": "ˈɡɪt.hʌb",
    "Kubernetes": "ˌkuː.bɚˈneɪ.tiːz",

    # Markup & Data Formats
    "JSON": "ˈdʒeɪ.sən",
    "HTML": "ˌeɪtʃ tiː ɛm ˈɛl",
    "CSS": "ˌsiː ɛs ˈɛs",
    "XML": "ˌɛks ɛm ˈɛl",

    # Tools & Frameworks
    "SDK": "ˌɛs diː ˈkeɪ",
    "CLI": "ˌsiː ɛl ˈaɪ",
    "framework": "ˈfreɪm.wɝːk",
    "backend": "ˈbæk.ɛnd",
    "frontend": "ˈfrʌnt.ɛnd",

    # AI & ML
    "AI": "eɪ aɪ",
    "machine learning": "məˈʃiːn ˈlɝː.nɪŋ",
    "OpenAI": "ˈoʊ.pən eɪ aɪ",
    "ChatGPT": "ˌtʃæt dʒiː piː ˈtiː",

    # Cloud & Infrastructure
    "cloud": "klaʊd",
}

# Characters that never belong in narration or rendered text: C0/C1 controls
# (tab/newline are folded to spaces first), zero-width and bidi formatting
# characters, the byte-order mark, and the Unicode replacement character.
_FORBIDDEN_PATTERN = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    "​-‏‪-‮⁠-⁤⁦-⁩"
    "﻿�]"
)

_ACRONYM_PATTERN = re.compile(r"\b(?:[A-Z][A-Z0-9]{0,5}|[A-Z]\d[A-Z]?\d?)\b")

# Lightweight fail-closed language gate. It is intentionally lexical rather
# than model-based: narration generation must not depend on network language
# detection, and common English technical terms are allowed via the lexicon.
_VIETNAMESE_MARKERS = frozenset({
    "ai", "bạn", "báo", "bằng", "bị", "các", "cách", "cần", "chỉ", "cho",
    "chúng", "có", "của", "đã", "đang", "đây", "đến", "để", "điều", "đó",
    "được", "giả", "giúp", "hệ", "hiện", "họ", "khi", "không", "là", "làm",
    "mà", "một", "này", "những", "người", "nhưng", "nó", "phải", "qua", "sẽ",
    "sự", "tạo", "thành", "theo", "thể", "thống", "tin", "trong", "trí", "từ",
    "và", "vào", "về", "với", "rất", "tiện", "công", "động", "hoạt", "năm",
})
_VIETNAMESE_DIACRITICS = "ĐđĂăÂâÊêÔôƠơƯưÁáÀàẢảÃãẠạẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẾếỀềỂểỄễỆệỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỨứỪừỬửỮữỰựÝýỲỳỶỷỸỹỴỵ"
_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)


def validate_vietnamese_narration(text: str) -> list[str]:
    """Reject narration that is not predominantly Vietnamese prose."""
    try:
        normalized = normalize_text(text)
    except ValueError as exc:
        return [str(exc)]

    words = [word.casefold() for word in _WORD_PATTERN.findall(normalized)]
    if not words:
        return ["narration contains no words"]

    marker_count = sum(word in _VIETNAMESE_MARKERS for word in words)
    has_vietnamese_diacritic = any(ch in _VIETNAMESE_DIACRITICS for ch in normalized)

    # A Vietnamese narration must contain both Vietnamese diacritics and at
    # least one common Vietnamese word. This rejects an English script that
    # happens to contain the technical term "AI".
    if not has_vietnamese_diacritic or marker_count == 0:
        return ["narration must be Vietnamese (missing Vietnamese diacritics or common words)"]
    return []


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


def prepare_narration_ssml(text: str, ipa_lexicon: list[tuple[str, str]] | None = None) -> str:
    """Full narration preparation with SSML <phoneme> tags for true English pronunciation.

    Returns SSML with <phoneme alphabet="ipa" ph="..."> tags for English technical terms,
    compatible with Google Cloud TTS, Azure Speech, and ElevenLabs multilingual models.
    """
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("narration text is empty after normalization")

    # Use IPA lexicon for SSML phoneme tags
    entries = [(src, ipa) for src, ipa in _IPA_TERMS.items()] if ipa_lexicon is None else ipa_lexicon
    entries = [(src, ipa) for src, ipa in entries if src and ipa]

    if not entries:
        return normalized

    def one_pattern(src: str) -> str:
        left = r"\b" if src[0].isalnum() else ""
        right = r"\b" if src[-1].isalnum() else ""
        return left + re.escape(src) + right

    combined = re.compile("|".join(one_pattern(src) for src, _ in entries), re.IGNORECASE)
    ipa_by_lower = {src.lower(): ipa for src, ipa in entries}

    protected: list[str] = []

    def replace_with_phoneme(match: re.Match[str]) -> str:
        original = match.group(0)
        ipa = ipa_by_lower[original.lower()]
        protected.append(f'<phoneme alphabet="ipa" ph="{ipa}">{original}</phoneme>')
        return f"{len(protected) - 1}"

    # Apply SSML phoneme tags as protected replacements
    ssml_text = combined.sub(replace_with_phoneme, normalized)

    # Spell out any remaining unknown ALL-CAPS acronyms
    ssml_text = _ACRONYM_PATTERN.sub(_spell_acronym, ssml_text)

    # Restore the protected SSML phoneme tags
    ssml_text = re.sub(r"(\d+)", lambda m: protected[int(m.group(1))], ssml_text)

    return f'<speak>{re.sub(r" {2,}", " ", ssml_text).strip()}</speak>'


def prepare_narration(text: str, use_ssml: bool = False) -> str:
    """Full narration preparation: normalise, localise, then re-fold spacing.

    Args:
        text: Input text to prepare
        use_ssml: If True, returns SSML with IPA phoneme tags for true English pronunciation.
                 If False (default), uses Vietnamese phonetic approximations.
    """
    if use_ssml:
        return prepare_narration_ssml(text)

    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("narration text is empty after normalization")
    language_errors = validate_vietnamese_narration(normalized)
    if language_errors:
        raise ValueError(language_errors[0])
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
