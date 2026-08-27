import unicodedata

import pytest

from tools.narration_text import (
    localize_pronunciation,
    normalize_text,
    prepare_narration,
    validate_display_text,
)


def test_technical_terms_localized():
    out = prepare_narration("Dùng API và TypeScript.")
    assert "API" not in out
    assert "TypeScript" not in out
    assert "Ây Pi Ây" in out


def test_ai_uses_single_vietnamese_pronunciation():
    out = prepare_narration("Cuộc chiến AI đang thay đổi.")
    assert "AI" not in out
    assert "ây-ai" in out
    assert "Ây Âi" not in out


def test_multiword_wins_over_component():
    out = prepare_narration("REST API rất tiện.")
    # "REST API" maps as a unit, not "API" alone leaving "REST" behind.
    assert "REST" not in out
    assert out.startswith("Rét Ây Pi Ây")


def test_idempotent():
    once = prepare_narration("API, TypeScript, PostgreSQL năm 2026.")
    twice = prepare_narration(once)
    assert once == twice


def test_unknown_english_preserved():
    out = prepare_narration("Công ty Foobar Widget hoạt động.")
    assert "Foobar Widget" in out


def test_nfc_normalization():
    decomposed = unicodedata.normalize("NFD", "Trí tuệ")
    assert normalize_text(decomposed) == unicodedata.normalize("NFC", "Trí tuệ")


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        prepare_narration("   \n\t ")


def test_case_insensitive_acronym_spelled():
    out = prepare_narration("Một sdk mới.")
    assert "Ét-Đi-Kây" in out


def test_validate_display_ok():
    assert validate_display_text("Công nghệ 2026") == []


def test_validate_display_rejects_replacement_and_zero_width():
    errors = validate_display_text("Xin ch​ào �")
    assert errors
    assert "U+200B" in errors[0]
    assert "U+FFFD" in errors[0]


def test_localize_leaves_plain_vietnamese():
    text = "Trí tuệ nhân tạo đang phát triển."
    assert localize_pronunciation(text) == text
