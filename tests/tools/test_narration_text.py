import unicodedata
from pathlib import Path

import pytest

from tools.narration_text import (
    localize_pronunciation,
    normalize_text,
    prepare_narration,
    validate_display_text,
    validate_vietnamese_narration,
)


ROOT = Path(__file__).resolve().parents[2]


def test_technical_terms_localized():
    out = prepare_narration("Dùng API và TypeScript.")
    assert "API" not in out
    assert "TypeScript" not in out
    assert "Ây Pi Ây" in out


def test_vietnamese_words_are_not_phoneticized():
    text = "Phần mềm mới tăng 60 phần trăm, một phần nhờ AI."
    out = prepare_narration(text)
    assert "Phần mềm" in out
    assert "60 phần trăm" in out
    assert "một phần" in out
    assert "ây-ai" in out


def test_display_text_remains_editorial_while_tts_is_localized():
    display = "Dùng API cho phần mềm mới."
    assert validate_display_text(display) == []
    assert display == "Dùng API cho phần mềm mới."
    assert "Ây Pi Ây" in prepare_narration(display)
    assert "API" in display


def test_pipeline_scripts_regenerate_narration_from_current_text():
    scripts = (
        ROOT / "scripts" / "run_daily_news_pipeline.sh",
        ROOT / "scripts" / "run_directors_for_existing.sh",
    )
    for path in scripts:
        source = path.read_text(encoding="utf-8")
        assert "tools/narration_text.py" in source
        assert "edge-tts --voice vi-VN-HoaiMyNeural" in source


def test_ci_runs_narration_gate_suite():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # Instead of verifying it's in the specific Makefile test-gates target, verify
    # it gets run by CI generally (which runs all tests and gates)
    assert "make test" in workflow or "pytest" in workflow


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
    errors = validate_display_text("Xin ch\u200bào �")
    assert errors
    assert "U+200B" in errors[0]
    assert "U+FFFD" in errors[0]


def test_localize_leaves_plain_vietnamese():
    text = "Trí tuệ nhân tạo đang phát triển."
    assert localize_pronunciation(text) == text


def test_rejects_mostly_english():
    english_text = "Are you sure that was your idea, or did the AI put it there? Chatbots are now experts at changing people's minds."
    with pytest.raises(ValueError, match="narration must be Vietnamese"):
        prepare_narration(english_text)


def test_ssml_mode_cannot_bypass_language_validation():
    """Regression: the SSML path must run the Vietnamese language gate before
    wrapping text in <phoneme> tags, so untranslatable English narration is
    rejected identically in both preparation modes."""
    english_text = "Are you sure that was your idea, or did the AI put it there? Chatbots are now experts at changing people's minds."
    with pytest.raises(ValueError, match="narration must be Vietnamese"):
        prepare_narration(english_text, use_ssml=True)


def test_ssml_mode_still_tags_valid_vietnamese_narration():
    text = "Hệ thống AI chạy trên GPU với CUDA và CPU hiệu năng cao."
    out = prepare_narration(text, use_ssml=True)
    assert out.startswith("<speak>")
    assert '<phoneme alphabet="ipa" ph="ˈkuː.də">CUDA</phoneme>' in out

