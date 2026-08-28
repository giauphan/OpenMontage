"""Tests for copyright and platform policy checks on video music."""

import sys
from pathlib import Path

from lib.music_policy import (
    ALLOWED_LICENSES,
    SOCIAL_LOUDNESS_LUFS,
    URL_LICENSES,
    music_query_for,
    select_music_provider,
    validate_music_policy,
)

TESTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TESTS_DIR.parent))


def _manifest(music=None):
    return {"version": "1.0", "assets": music or []}


def test_no_music_passes():
    assert validate_music_policy(_manifest(), {"metadata": {}}) == []


def test_pixabay_music_needs_url():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "pixabay",
         "license": "Pixabay Content License", "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    errors = validate_music_policy(manifest, {"metadata": {}})
    assert any("original_url" in e for e in errors)


def test_pixabay_music_full_chain_passes():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "pixabay",
         "license": "Pixabay Content License", "original_url": "https://pixabay.com/music/x",
         "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    assert validate_music_policy(manifest, {"metadata": {}}) == []


def test_cc_by_needs_attribution():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "freesound", "license": "CC BY",
         "original_url": "https://freesound.org/s/1", "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    errors = validate_music_policy(manifest, {"metadata": {}})
    assert any("attribution_text" in e for e in errors)


def test_unknown_license_blocked():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "unknown", "license": "Unknown",
         "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    errors = validate_music_policy(manifest, {"metadata": {}})
    assert any("unsupported license" in e for e in errors)


def test_social_platforms_require_minus_14_lufs():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "elevenlabs", "license": "AI Generated Original",
         "license_url": "https://elevenlabs.io/terms", "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    edit = {"metadata": {"target_platforms": ["youtube", "tiktok", "instagram"], "loudnorm_target": -16}}
    errors = validate_music_policy(manifest, edit)
    assert any("loudnorm_target must be -14" in e for e in errors)


def test_social_platforms_accept_allowed_licenses():
    allowed = sorted(ALLOWED_LICENSES)
    assert "Pixabay Content License" in allowed
    assert "AI Generated Original" in allowed
    # Licenses that require a URL must be tracked.
    assert "Pixabay Content License" in URL_LICENSES


def test_social_platforms_allow_minus_14():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "elevenlabs", "license": "AI Generated Original",
         "license_url": "https://elevenlabs.io/terms", "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    edit = {
        "metadata": {"target_platforms": ["youtube", "tiktok", "instagram"]},
        "audio": {"music": {"ducking": {"enabled": True}}},
    }
    assert validate_music_policy(manifest, edit) == []


def test_social_platforms_require_ducking():
    manifest = _manifest([
        {"id": "m1", "type": "music", "provider": "elevenlabs", "license": "AI Generated Original",
         "license_url": "https://elevenlabs.io/terms", "acquired_at": "2026-08-28T00:00:00Z"},
    ])
    edit = {
        "metadata": {"target_platforms": ["youtube"], "loudnorm_target": SOCIAL_LOUDNESS_LUFS},
        "audio": {"music": {"ducking": False}},
    }
    errors = validate_music_policy(manifest, edit)
    assert any("ducking must be enabled" in e for e in errors)


def test_auto_select_prefers_pixabay_over_gen():
    tools = {"pixabay_music", "music_gen", "tts_selector"}
    result = select_music_provider(tools)
    assert result == ("pixabay_music", "Pixabay Content License")


def test_auto_select_skips_unavailable():
    tools = {"music_gen", "tts_selector"}  # pixabay not available
    result = select_music_provider(tools)
    assert result == ("music_gen", "AI Generated Original")


def test_auto_select_returns_none_when_no_music_tool():
    tools = {"tts_selector", "image_selector"}
    assert select_music_provider(tools) is None


def test_mood_query_maps_renderer_family():
    assert music_query_for("cinematic-trailer") == "epic cinematic tension instrumental"
    assert music_query_for("screen-demo") == "minimal light background instrumental"
    assert music_query_for(None) == "calm ambient background instrumental"
    assert music_query_for("unknown-family") == "calm ambient background instrumental"
