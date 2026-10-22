"""Locale-aware language and prose validators for OpenMontage.

Provides strict, locale-specific validation strategies:
- VietnameseLanguageValidator: Preserves existing strict vi-VN rules and heuristics.
- EnglishLanguageValidator: Enforces native US/CA English prose, detects foreign
  language leaks, Vietnamese diacritics, unidiomatic copy, and currency mismatches.
"""
from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from typing import Any

from lib.artifact_paths import is_english_locale

# Vietnamese diacritics that must never leak into pure en-US copy (outside quotes)
VIETNAMESE_DIACRITICS = set(
    "áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ"
    "ÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴ"
)

# Common Vietnamese words that indicate an untranslated or mixed Vietnamese phrase
VIETNAMESE_LEAK_WORDS = {
    "tin", "tức", "tintuc", "công", "nghệ", "congnghe", "hôm", "nay", "chúng",
    "tôi", "phần", "mềm", "của", "và", "được", "cho", "với", "trong", "này",
    "đang", "sẽ", "đã", "rất", "nhiều", "người", "dùng", "thay", "đổi", "cuộc",
    "sống", "bạn", "xin", "chào", "bấm", "chuông", "đăng", "ký", "kênh",
    "chia", "sẻ", "bình", "luận", "xem", "thêm"
}

# Unresolved currency markers that should not be quietly converted
VIETNAM_CURRENCY_PATTERNS = [
    re.compile(r"\b\d+\s*(?:triệu|tỷ|nghìn|k|vnd|đ|dong|đồng)\b", re.IGNORECASE),
]

UNIDIOMATIC_ENGLISH_PATTERNS = [
    (re.compile(r"\bvery\s+much\s+(?:people|users|developers|engineers|customers|clients|persons)\b", re.IGNORECASE),
     "Unidiomatic quantifier: 'very much {noun}' is unnatural English (use 'many {noun}' or 'a large number of {noun}')."),
    (re.compile(r"\bmuch\s+(?:people|users|developers|engineers|customers|persons)\b", re.IGNORECASE),
     "Grammar error: 'much' used with countable noun (use 'many')."),
    (re.compile(r"\b(?:many|much|few)\s+informations?\b", re.IGNORECASE),
     "Grammar error: 'information' is uncountable in English."),
    (re.compile(r"\b(?:many|much)\s+advices?\b", re.IGNORECASE),
     "Grammar error: 'advice' is uncountable in English."),
    (re.compile(r"\b(?:big|large)\s+amount\s+of\s+(?:people|users|developers|persons)\b", re.IGNORECASE),
     "Unidiomatic quantifier: 'amount of' with countable people (use 'number of people')."),
    (re.compile(r"\bopen\s+the\s+(?:light|lamp|screen|computer)\b", re.IGNORECASE),
     "Literal translation calque: 'open the' instead of 'turn on'."),
    (re.compile(r"\bclose\s+the\s+(?:light|lamp|screen|computer)\b", re.IGNORECASE),
     "Literal translation calque: 'close the' instead of 'turn off'."),
    (re.compile(r"\bmake\s+a\s+question\b", re.IGNORECASE),
     "Literal translation calque: 'make a question' instead of 'ask a question'."),
    (re.compile(r"\bdiscuss\s+about\b", re.IGNORECASE),
     "Unidiomatic preposition: 'discuss about' (use 'discuss')."),
    (re.compile(r"\bwith\s+the\s+(?:fast\s+)?development\s+of\s+technology\b", re.IGNORECASE),
     "Unidiomatic trope: 'with the development of technology' is non-native filler."),
    (re.compile(r"\bas\s+we\s+all\s+know\b", re.IGNORECASE),
     "Unidiomatic trope: 'as we all know' is non-native filler."),
    (re.compile(r"\bit\s+is\s+worth\s+mentioning\s+that\b", re.IGNORECASE),
     "Unidiomatic trope: 'it is worth mentioning that' is non-native filler."),
]

_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)


class LanguageValidator(ABC):
    """Abstract strategy for locale prose validation."""

    @abstractmethod
    def validate_prose(self, text: str) -> list[str]:
        """Validate prose text, returning a list of validation errors."""

    @abstractmethod
    def validate_metadata(
        self,
        title: str,
        description: str,
        tags: list[str] | None = None,
    ) -> list[str]:
        """Validate metadata fields for the locale."""


class VietnameseLanguageValidator(LanguageValidator):
    """Encapsulates existing Vietnamese heuristics without breaking legacy contracts."""

    def validate_prose(self, text: str) -> list[str]:
        from tools.narration_text import check_vietnamese_prose
        return check_vietnamese_prose(text)

    def validate_metadata(
        self,
        title: str,
        description: str,
        tags: list[str] | None = None,
    ) -> list[str]:
        errors = []
        if title:
            errors.extend(self.validate_prose(title))
        if description:
            errors.extend(self.validate_prose(description))
        return errors


class EnglishLanguageValidator(LanguageValidator):
    """Strict US/CA English prose validator.

    Detects:
    1. Vietnamese diacritics / accents leaking into English text.
    2. Vietnamese words or phrases.
    3. Untranslated currency/units.
    4. Literal untranslated Vietnamese UI labels.
    5. Non-English stop words or gibberish.
    """

    def __init__(self, locale: str = "en-US") -> None:
        self.locale = locale

    def validate_prose(self, text: str) -> list[str]:
        if not text or not text.strip():
            return ["text is empty"]

        normalized = unicodedata.normalize("NFC", text)
        errors: list[str] = []

        # 1. Check for Vietnamese diacritic leaks
        leaked_diacritics = [ch for ch in normalized if ch in VIETNAMESE_DIACRITICS]
        if leaked_diacritics:
            sample = "".join(sorted(set(leaked_diacritics))[:5])
            errors.append(f"English text contains Vietnamese diacritics: {sample}")

        # 2. Extract words
        clean_text = re.sub(r"#\w+", "", normalized)
        clean_text = re.sub(r"https?://\S+", "", clean_text)
        words = [w.casefold() for w in _WORD_PATTERN.findall(clean_text) if not w.isnumeric()]
        if not words:
            return ["text contains no alphabetic words"]

        # 3. Check for Vietnamese word leaks
        leaked_vi = [w for w in words if w in VIETNAMESE_LEAK_WORDS]
        if leaked_vi:
            sample_words = ", ".join(sorted(set(leaked_vi))[:5])
            errors.append(f"English text contains Vietnamese words: {sample_words}")

        # 4. Check for untranslated Vietnamese currency formats
        for pattern in VIETNAM_CURRENCY_PATTERNS:
            match = pattern.search(clean_text)
            if match:
                errors.append(f"English text contains untranslated Vietnamese currency format: {match.group(0)}")

        # 5. Basic English prose ratio check
        # Must have valid ASCII characters primarily
        ascii_words = [w for w in words if w.isascii()]
        ascii_ratio = len(ascii_words) / len(words)
        if ascii_ratio < 0.90:
            errors.append(f"Text does not appear to be standard English prose (ASCII ratio {ascii_ratio:.0%})")

        # 6. Check for unidiomatic machine-translated patterns, calques and non-native tropes
        for pattern, msg in UNIDIOMATIC_ENGLISH_PATTERNS:
            match = pattern.search(clean_text)
            if match:
                errors.append(f"Cultural localization rejection: {msg} Found: '{match.group(0)}'")

        return errors

    def validate_metadata(
        self,
        title: str,
        description: str,
        tags: list[str] | None = None,
    ) -> list[str]:
        errors: list[str] = []
        if not title or not title.strip():
            errors.append("title is required")
        else:
            title_errors = self.validate_prose(title)
            if title_errors:
                errors.extend(f"title: {e}" for e in title_errors)

        if description:
            desc_errors = self.validate_prose(description)
            if desc_errors:
                errors.extend(f"description: {e}" for e in desc_errors)

        # Check tags
        if tags:
            for tag in tags:
                clean_tag = tag.lstrip("#").lower()
                if clean_tag in VIETNAMESE_LEAK_WORDS or any(ch in VIETNAMESE_DIACRITICS for ch in clean_tag):
                    errors.append(f"tags contain Vietnamese tag: {tag}")

        return errors


def get_language_validator(locale: str) -> LanguageValidator:
    """Return the appropriate LanguageValidator strategy for the locale."""
    if is_english_locale(locale):
        return EnglishLanguageValidator(locale)
    return VietnameseLanguageValidator()
