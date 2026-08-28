import unicodedata
from pathlib import Path

import pytest

from tools.narration_text import (
    localize_pronunciation,
    normalize_text,
    prepare_narration,
    validate_display_text,
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
        assert 'tools/narration_text.py" --in-file "$narration_text"' in source
        assert '"$narration.tmp"' in source
        assert 'mv "$narration.tmp" "$narration"' in source
        assert 'edge-tts unavailable and narration is missing/stale' in source
        assert "narration_duration <= 30" not in source


def test_ci_runs_narration_gate_suite():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "tests/tools/test_narration_text.py" in makefile
    assert "run: make test-gates" in workflow


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
