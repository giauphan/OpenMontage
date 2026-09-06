import re
from pathlib import Path
import pytest

from tools.narration_text import prepare_narration, _DEFAULT_TERMS, _IPA_TERMS


def test_tts_terminology_pronunciation_lexicon():
    """Verify CPU, GPU, and CUDA are correctly mapped in Vietnamese TTS lexicon."""
    assert "CPU" in _DEFAULT_TERMS
    assert _DEFAULT_TERMS["CPU"] == "Xi-Pi-Yu"

    assert "GPU" in _DEFAULT_TERMS
    assert _DEFAULT_TERMS["GPU"] == "Ghi-Pi-Yu"

    assert "CUDA" in _DEFAULT_TERMS
    assert _DEFAULT_TERMS["CUDA"] == "Cu-đa"  # Updated to more accurate Vietnamese phonetics

    assert "CUDA" in _IPA_TERMS
    assert _IPA_TERMS["CUDA"] == "ˈkuː.də"


def test_all_lexicon_terms_have_valid_ipa():
    """Verify all default terms have an accurate, non-empty IPA mapping."""
    for term in _DEFAULT_TERMS:
        assert term in _IPA_TERMS, f"Missing IPA mapping for term: {term}"
        assert len(_IPA_TERMS[term]) > 0, f"Empty IPA mapping for term: {term}"



def test_prepare_narration_with_terminology():
    """Verify sentences with terminology produce expected phonetic transcriptions."""
    text = "Hệ thống AI chạy trên GPU với CUDA và CPU hiệu năng cao."

    # Vietnamese phonetic mode (default)
    prepared = prepare_narration(text)
    assert "Ghi-Pi-Yu" in prepared
    assert "Cu-đa" in prepared
    assert "Xi-Pi-Yu" in prepared
    assert "ây-ai" in prepared

    # True IPA SSML mode
    ssml = prepare_narration(text, use_ssml=True)
    assert '<phoneme alphabet="ipa" ph="ˈkuː.də">CUDA</phoneme>' in ssml
    assert '<phoneme alphabet="ipa" ph="ˌdʒiː piː ˈjuː">GPU</phoneme>' in ssml
    assert '<phoneme alphabet="ipa" ph="ˌsiː piː ˈjuː">CPU</phoneme>' in ssml
    assert ssml.startswith('<speak>') and ssml.endswith('</speak>')


def test_titled_video_tsx_prevents_text_overlap():
    """Verify TitledVideo.tsx styles use safe line-height and text wrapping for Vietnamese text."""
    titled_video_path = Path(__file__).resolve().parents[1] / "remotion-composer" / "src" / "TitledVideo.tsx"
    assert titled_video_path.is_file(), f"Expected {titled_video_path} to exist"

    content = titled_video_path.read_text(encoding="utf-8")

    # Verify line-height is at least 1.2 for Vietnamese diacritics
    line_height_match = re.search(r"lineHeight:\s*([0-9\.]+)", content)
    assert line_height_match is not None, "lineHeight style property not found in TitledVideo.tsx"
    line_height = float(line_height_match.group(1))
    assert line_height >= 1.2, f"Expected lineHeight >= 1.2 to prevent diacritic overlap, got {line_height}"

    # Verify text wrapping is enabled (no whiteSpace: 'nowrap')
    assert "whiteSpace: \"pre-wrap\"" in content or "whiteSpace: 'pre-wrap'" in content or "whiteSpace: \"normal\"" in content
    assert "flexWrap: \"wrap\"" in content or "flexWrap: 'wrap'" in content

    # Verify maxWidth constraint prevents edge overflowing
    assert "maxWidth:" in content
