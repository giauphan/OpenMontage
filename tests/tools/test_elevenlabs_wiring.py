"""Unit and contract tests for ElevenLabs TTS wiring, voice aliases, and fallback in OpenMontage."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.audio.elevenlabs_tts import ElevenLabsTTS, is_elevenlabs_available
from tools.base_tool import ToolResult, ToolStatus
from lib.audio.narration_orchestrator import NarrationOrchestrator


def test_elevenlabs_api_key_resolution_and_status(monkeypatch):
    tool = ElevenLabsTTS()

    # None set
    monkeypatch.delenv("ELEVENLABS_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("XI_API_KEY", raising=False)
    assert tool.get_status() == ToolStatus.UNAVAILABLE
    assert is_elevenlabs_available() is False

    # ELEVENLABS_GATEWAY_API_KEY set
    monkeypatch.setenv("ELEVENLABS_GATEWAY_API_KEY", "gw_key_secret")
    assert tool.get_status() == ToolStatus.AVAILABLE
    assert tool._resolve_api_key() == "gw_key_secret"
    assert is_elevenlabs_available() is True

    # ELEVENLABS_API_KEY set
    monkeypatch.delenv("ELEVENLABS_GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_1")
    assert tool.get_status() == ToolStatus.AVAILABLE
    assert tool._resolve_api_key() == "test_key_1"
    assert is_elevenlabs_available() is True

    # XI_API_KEY set
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("XI_API_KEY", "test_key_2")
    assert tool.get_status() == ToolStatus.AVAILABLE
    assert tool._resolve_api_key() == "test_key_2"
    assert is_elevenlabs_available() is True

    # Explicit input override
    assert tool._resolve_api_key({"elevenlabs_gateway_api_key": "explicit_gw"}) == "explicit_gw"
    assert tool._resolve_api_key({"api_key": "explicit_key"}) == "explicit_key"
    assert tool._resolve_api_key({"xi_api_key": "explicit_xi"}) == "explicit_xi"


def test_elevenlabs_voice_aliases():
    tool = ElevenLabsTTS()
    assert tool.resolve_voice_id("rachel") == "21m00Tcm4TlvDq8ikWAM"
    assert tool.resolve_voice_id("Rachel") == "21m00Tcm4TlvDq8ikWAM"
    assert tool.resolve_voice_id("adam") == "pNInz6obpgDQGcFmaJgB"
    assert tool.resolve_voice_id("charlie") == "IKne3meq5aSn9XLyUdCD"
    assert tool.resolve_voice_id("custom_voice_id_12345") == "custom_voice_id_12345"
    assert tool.resolve_voice_id(None) == tool.DEFAULT_VOICE_ID


def test_elevenlabs_base_url_and_proxy(monkeypatch):
    tool = ElevenLabsTTS()
    monkeypatch.delenv("ELEVENLABS_BASE_URL", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_BASE", raising=False)
    monkeypatch.delenv("XI_API_BASE", raising=False)

    # Default
    assert "api.elevenlabs.io" in (
        os.environ.get("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io"
    )

    # Custom gateway proxy
    monkeypatch.setenv("ELEVENLABS_BASE_URL", "http://127.0.0.1:20129/elevenlabs")
    base_url = (
        os.environ.get("ELEVENLABS_BASE_URL")
        or os.environ.get("ELEVENLABS_API_BASE")
        or os.environ.get("XI_API_BASE")
        or "https://api.elevenlabs.io"
    ).rstrip("/")
    assert base_url == "http://127.0.0.1:20129/elevenlabs"


def test_elevenlabs_toolcase_gateway_speech_endpoint(tmp_path, monkeypatch):
    tool = ElevenLabsTTS()
    monkeypatch.setenv("ELEVENLABS_GATEWAY_API_KEY", "gw_key_secret_123")
    monkeypatch.setenv("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129")

    # Verify base URL and endpoint resolution
    base_url, endpoint, is_speech = tool._resolve_base_url_and_endpoint({}, "21m00Tcm4TlvDq8ikWAM")
    assert base_url == "http://127.0.0.1:20129"
    assert endpoint == "http://127.0.0.1:20129/v1/audio/speech"
    assert is_speech is True

    # Test HTTP execution against mocked gateway endpoint
    captured_req = {}

    def mock_post(url, headers, json, params, timeout):
        captured_req["url"] = url
        captured_req["headers"] = headers
        captured_req["json"] = json
        captured_req["params"] = params
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ID3\x03\x00\x00\x00\x00\x00#dummy_audio_bytes_content_payload"
        return mock_resp

    out_file = tmp_path / "gw_speech.mp3"
    with patch("requests.post", side_effect=mock_post):
        res = tool.execute({
            "text": "Hello via Toolcase gateway speech endpoint.",
            "voice_id": "rachel",
            "output_path": str(out_file),
            "speed": 1.05,
        })

    assert res.success is True
    assert captured_req["url"] == "http://127.0.0.1:20129/v1/audio/speech"
    assert captured_req["headers"]["Authorization"] == "Bearer gw_key_secret_123"
    assert captured_req["headers"]["xi-api-key"] == "gw_key_secret_123"
    assert captured_req["json"]["input"] == "Hello via Toolcase gateway speech endpoint."
    assert captured_req["json"]["text"] == "Hello via Toolcase gateway speech endpoint."
    assert captured_req["json"]["voice"] == "21m00Tcm4TlvDq8ikWAM"
    assert captured_req["json"]["speed"] == 1.05
    assert out_file.is_file()
    assert out_file.stat().st_size > 0


def test_orchestrator_fallback_on_elevenlabs_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("XI_API_KEY", raising=False)

    orch = NarrationOrchestrator(cache_dir=tmp_path / "cache", lock_path=tmp_path / "test.lock")
    out_audio = tmp_path / "test_fallback.mp3"

    # synthesize with provider="elevenlabs" and allow_fallback=True should cascade and succeed
    res = orch.synthesize(
        text="Testing automated fallback for ElevenLabs.",
        output_path=out_audio,
        locale="en-US",
        provider="elevenlabs",
        allow_fallback=True,
    )
    assert res["success"] is True
    assert res["provider"] in ("kokoro", "edge", "flite")
    assert out_audio.is_file()
    assert out_audio.stat().st_size > 0


def test_orchestrator_raises_when_allow_fallback_false(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("XI_API_KEY", raising=False)

    orch = NarrationOrchestrator(cache_dir=tmp_path / "cache", lock_path=tmp_path / "test.lock")
    out_audio = tmp_path / "test_strict.mp3"

    with pytest.raises(RuntimeError, match="No ElevenLabs API key"):
        orch.synthesize(
            text="Testing strict failure when fallback is disabled.",
            output_path=out_audio,
            locale="en-US",
            provider="elevenlabs",
            allow_fallback=False,
        )


def test_orchestrator_tech_candidates_include_elevenlabs(tmp_path, monkeypatch):
    monkeypatch.setenv("XI_API_KEY", "dummy_xi_key")
    orch = NarrationOrchestrator(cache_dir=tmp_path / "cache")

    def mock_synth(text, output_path, locale, provider, voice, settings, allow_fallback):
        return {"success": True, "duration_seconds": 70.0, "output_path": str(output_path)}

    with patch.object(orch, "synthesize", side_effect=mock_synth):
        res = orch.evaluate_tech_voice_fit(
            text="Testing voice candidate ranking.",
            target_seconds=70.0,
            locale="en-US",
        )
        assert res["best_fit"] is not None
        providers = [c["provider"] for c in res["evaluations"]]
        assert "elevenlabs" in providers
