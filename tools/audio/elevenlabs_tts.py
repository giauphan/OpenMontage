"""ElevenLabs text-to-speech provider tool."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class ElevenLabsTTS(BaseTool):
    name = "elevenlabs_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "elevenlabs"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set the ELEVENLABS_GATEWAY_API_KEY or ELEVENLABS_API_KEY environment variable:\n"
        "  export ELEVENLABS_GATEWAY_API_KEY=your_key_here\n"
        "  export TOOLCASE_GATEWAY_URL=http://127.0.0.1:20129\n"
        "Or get a direct key at https://elevenlabs.io"
    )
    fallback = "openai_tts"
    fallback_tools = ["openai_tts", "piper_tts"]
    agent_skills = ["elevenlabs", "text-to-speech"]

    capabilities = [
        "text_to_speech",
        "voice_selection",
        "ssml_support",
        "pronunciation_control",
    ]
    supports = {
        "voice_cloning": True,
        "multilingual": True,
        "offline": False,
        "native_audio": True,
    }
    best_for = [
        "high-quality narration",
        "voice-sensitive spokesperson videos",
        "multilingual spoken delivery",
    ]
    not_good_for = [
        "fully offline production",
        "privacy-constrained local-only workflows",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "description": "Text to convert to speech"},
            "voice_id": {
                "type": "string",
                "description": "ElevenLabs voice ID (default: Rachel)",
            },
            "model_id": {
                "type": "string",
                "default": "eleven_multilingual_v2",
                "description": "TTS model to use",
            },
            "stability": {
                "type": "number",
                "default": 0.5,
                "minimum": 0,
                "maximum": 1,
            },
            "similarity_boost": {
                "type": "number",
                "default": 0.75,
                "minimum": 0,
                "maximum": 1,
            },
            "style": {
                "type": "number",
                "default": 0.0,
                "minimum": 0,
                "maximum": 1,
            },
            "speed": {
                "type": "number",
                "default": 1.0,
                "minimum": 0.7,
                "maximum": 1.2,
            },
            "use_speaker_boost": {
                "type": "boolean",
                "default": True,
            },
            "output_path": {"type": "string"},
            "output_format": {
                "type": "string",
                "default": "mp3_44100_128",
                "enum": ["mp3_44100_128", "mp3_44100_192", "pcm_16000", "pcm_24000"],
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = [
        "text",
        "voice_id",
        "model_id",
        "stability",
        "similarity_boost",
        "style",
        "speed",
        "use_speaker_boost",
    ]
    side_effects = ["writes audio file to output_path", "calls ElevenLabs API"]
    user_visible_verification = ["Listen to generated audio for natural speech quality"]

    DEFAULT_VOICE_ID = "IKne3meq5aSn9XLyUdCD"
    VOICE_ALIASES: dict[str, str] = {
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "adam": "pNInz6obpgDQGcFmaJgB",
        "charlie": "IKne3meq5aSn9XLyUdCD",
        "antoni": "ErXwobaYiN019PkySvjV",
        "bella": "EXAVITQu4vr4xnSDxMaL",
        "elli": "MF3mGyEYCl7XYWbV9V6O",
        "josh": "TxGEqnHWrfWFTfGW9XjX",
        "arnold": "VR6AewLTigWG4xSOukaG",
        "sam": "yoZ06aMxZJJ28mfd3POQ",
        "marcia": "05f19352e8f74b0392a8f411eba40de1",
        "george": "JBFqnCBsd6RMkjVDRZzb",
        "callum": "N2lVS1w4EtoT3dr4eOWO",
        "clyde": "2EiwWnXFnvU5JabPnv8n",
        "daniel": "onwK4e9ZLuTAKqWW03F9",
        "dave": "CYw3kZ02Hs0563khs1Fj",
        "emily": "LcfcDJNigLAnFtMwioal",
        "ethan": "g5CIjZEefAph4nQFvHAz",
        "fin": "D38z5TcIugrnNc5KGn07",
        "freya": "jsCqWAovK2LkecY7zXl4",
        "giovanni": "zcAOhNBS3c14rBihAFp1",
        "glinda": "z9fAnlkpzviPz146aGWa",
        "grace": "oWAxZDxUJnTXcrRwWoWW",
        "harry": "SOYHLrjzK2X1ezoPC6cr",
        "james": "ZQe5CZPfIWLOGTXjAcjT",
        "jeremy": "bVMeCyTHy58xNoL34h3p",
        "jessie": "t0jbNlBVZ17f02VDIeMI",
        "joseph": "Zlb1dXrM653N07WRdFW3",
        "liam": "TX3LPaxmHKxFdv7VOQHJ",
        "matilda": "XrExE9yKIg1WjnnlVkGX",
        "michael": "flq6f7yk4E4fJM5XTYuZ",
        "mimi": "zrHiDhphv9ZnVXBqCLjz",
        "nicole": "piTKgcLEGmPE4e6mEKli",
        "patrick": "ODq5zmih8GrVes37Dizd",
        "paul": "5Q0t7uMcjvnagumLfvZi",
        "serena": "pMsXgVXv3BLzUgSXRplE",
        "thomas": "GBv7mTt0atIp3Br8iCZE",
        "alice": "Xb7hH8MSUJpSbSDYk0k2",
        "bill": "pqHfZKP75CvOlQylNhV4",
        "brian": "nPczCjzI2devNBz1zQrb",
        "chris": "iP95p4xoKVk53GoZ742B",
        "eric": "cjVigY5qzO86Huf0OWal",
        "jessica": "cgSgspJ2msm6clMCkdW9",
        "laura": "FGY2WhTYpPnrIDTdsKH5",
        "lily": "pFZP5JQG7iQjIYeC4fwd",
        "sarah": "EXAVITQu4vr4xnSDxMaL",
        "will": "bIHbv24MWmeRgasZH58o",
    }

    @classmethod
    def resolve_voice_id(cls, voice: str | None) -> str:
        """Resolve friendly voice name to ElevenLabs voice ID or return raw voice ID."""
        if not voice:
            return cls.DEFAULT_VOICE_ID
        clean = str(voice).strip()
        return cls.VOICE_ALIASES.get(clean.lower(), clean)

    def _resolve_api_key(self, inputs: dict[str, Any] | None = None) -> str | None:
        if inputs:
            k = (
                inputs.get("api_key")
                or inputs.get("elevenlabs_gateway_api_key")
                or inputs.get("elevenlabs_api_key")
                or inputs.get("xi_api_key")
            )
            if k and str(k).strip():
                return str(k).strip()
        return (
            os.environ.get("ELEVENLABS_GATEWAY_API_KEY")
            or os.environ.get("ELEVENLABS_API_KEY")
            or os.environ.get("XI_API_KEY")
        )

    def _resolve_base_url_and_endpoint(
        self, inputs: dict[str, Any], voice_id: str
    ) -> tuple[str, str, bool]:
        """Resolve base URL and endpoint for ElevenLabs or Toolcase Gateway.

        Returns:
            (base_url, endpoint, is_audio_speech_protocol)
        """
        has_gateway_key = bool(
            inputs.get("elevenlabs_gateway_api_key")
            or os.environ.get("ELEVENLABS_GATEWAY_API_KEY")
        )
        gateway_url = (
            inputs.get("gateway_url")
            or os.environ.get("ELEVENLABS_GATEWAY_URL")
            or (os.environ.get("TOOLCASE_GATEWAY_URL") if has_gateway_key else None)
        )
        base_url = (
            inputs.get("base_url")
            or gateway_url
            or os.environ.get("ELEVENLABS_BASE_URL")
            or os.environ.get("ELEVENLABS_API_BASE")
            or os.environ.get("XI_API_BASE")
            or "https://api.elevenlabs.io"
        ).strip().rstrip("/")

        # Check if targeting Toolcase Gateway or an audio/speech endpoint
        is_toolcase = bool(
            gateway_url and base_url == gateway_url.strip().rstrip("/")
        )
        is_speech_ep = (
            is_toolcase
            or inputs.get("endpoint_type") == "speech"
            or "/v1/audio/speech" in base_url
            or "/audio/speech" in base_url
        )

        if is_speech_ep:
            if base_url.endswith("/v1/audio/speech"):
                endpoint = base_url
            elif base_url.endswith("/audio/speech"):
                endpoint = base_url
            elif base_url.endswith("/v1"):
                endpoint = f"{base_url}/audio/speech"
            else:
                endpoint = f"{base_url}/v1/audio/speech"
            return base_url, endpoint, True

        if "/v1" in base_url:
            endpoint = f"{base_url}/text-to-speech/{voice_id}"
        else:
            endpoint = f"{base_url}/v1/text-to-speech/{voice_id}"
        return base_url, endpoint, False

    def get_status(self) -> ToolStatus:
        if self._resolve_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return round(len(inputs.get("text", "")) * 0.0003, 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._resolve_api_key(inputs)
        if not api_key:
            return ToolResult(success=False, error="No ElevenLabs API key. " + self.install_instructions)

        start = time.time()
        try:
            result = self._generate(inputs, api_key)
        except Exception as exc:
            return ToolResult(success=False, error=f"TTS generation failed: {exc}")

        result.duration_seconds = round(time.time() - start, 2)
        result.cost_usd = self.estimate_cost(inputs)
        return result

    def _build_payload_and_params(
        self,
        is_speech: bool,
        text: str,
        model_id: str,
        voice_id: str,
        speed: float,
        voice_settings: dict[str, Any],
        output_format: str,
    ) -> tuple[dict[str, Any], dict[str, str] | None, str]:
        if is_speech:
            resolved_format = "mp3_44100_128"
            payload = {
                "model": model_id,
                "input": text,
                "text": text,
                "voice": voice_id,
                "voice_id": voice_id,
                "speed": speed,
                "response_format": "mp3",
                "voice_settings": voice_settings,
            }
            params = None
        else:
            resolved_format = output_format
            payload = {
                "text": text,
                "model_id": model_id,
                "voice_settings": voice_settings,
            }
            params = {"output_format": resolved_format}
        return payload, params, resolved_format

    def _post_with_fallbacks(
        self,
        requests_mod: Any,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        params: dict[str, str] | None,
        timeout: float,
        voice_id: str,
    ) -> tuple[Any, str, str]:
        try:
            response = requests_mod.post(
                endpoint,
                headers=headers,
                json=payload,
                params=params,
                timeout=timeout,
            )
        except requests_mod.exceptions.RequestException as req_err:
            raise RuntimeError(f"ElevenLabs connection error to {endpoint}: {req_err}") from req_err

        # Automatic gateway port resolution (20129 -> 20128) if 20129 has no audio/speech route
        if response.status_code in (400, 404) and ":20129" in endpoint:
            alt_ep = endpoint.replace(":20129", ":20128")
            try:
                alt_resp = requests_mod.post(alt_ep, headers=headers, json=payload, params=params, timeout=timeout)
                if alt_resp.status_code in (200, 402):
                    response = alt_resp
                    endpoint = alt_ep
            except Exception:
                pass

        # Automatic premade voice fallback for free-tier library voice restrictions
        if response.status_code == 402 and "library" in response.text.lower():
            premade_voice = "IKne3meq5aSn9XLyUdCD"  # Charlie (premade, universal)
            if voice_id != premade_voice:
                if "voice" in payload:
                    payload["voice"] = premade_voice
                if "voice_id" in payload:
                    payload["voice_id"] = premade_voice
                voice_id = premade_voice
                if "/text-to-speech/" in endpoint:
                    endpoint = endpoint.rsplit("/", 1)[0] + f"/{premade_voice}"
                try:
                    response = requests_mod.post(endpoint, headers=headers, json=payload, params=params, timeout=timeout)
                except Exception:
                    pass

        return response, endpoint, voice_id

    def _save_audio_file(self, raw_output: str, audio_bytes: bytes, output_format: str) -> Path:
        ext = "mp3" if "mp3" in output_format else "wav"
        output_str = raw_output or f"tts_output.{ext}"
        output_path = Path(output_str).expanduser().resolve()
        allowed_roots = (
            ROOT.resolve(),
            Path.cwd().resolve(),
            Path.home().resolve(),
            Path(tempfile.gettempdir()).resolve(),
        )
        if not any(output_path.is_relative_to(r) for r in allowed_roots if r != Path(r.anchor)):
            raise ValueError(f"Path traversal detected: {output_str}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        return output_path

    def _generate(self, inputs: dict[str, Any], api_key: str) -> ToolResult:
        import requests

        text = inputs["text"]
        voice_id = self.resolve_voice_id(inputs.get("voice_id"))
        model_id = inputs.get("model_id", "eleven_multilingual_v2")
        raw_speed = float(inputs.get("speed", 1.0))
        speed = max(0.7, min(1.2, raw_speed))
        voice_settings = {
            "stability": inputs.get("stability", 0.5),
            "similarity_boost": inputs.get("similarity_boost", 0.75),
            "style": inputs.get("style", 0.0),
            "speed": speed,
            "use_speaker_boost": inputs.get("use_speaker_boost", True),
        }

        _, endpoint, is_speech = self._resolve_base_url_and_endpoint(inputs, voice_id)

        headers = {
            "xi-api-key": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload, params, output_format = self._build_payload_and_params(
            is_speech, text, model_id, voice_id, speed, voice_settings, inputs.get("output_format", "mp3_44100_128")
        )

        timeout = float(inputs.get("timeout", 120))
        response, endpoint, voice_id = self._post_with_fallbacks(
            requests, endpoint, headers, payload, params, timeout, voice_id
        )

        if response.status_code != 200:
            err_msg = response.text[:300] if response.text else f"status {response.status_code}"
            raise RuntimeError(f"ElevenLabs TTS failed at {endpoint} with HTTP {response.status_code}: {err_msg}")

        audio_bytes = response.content
        if not audio_bytes or len(audio_bytes) < 10:
            raise RuntimeError(f"ElevenLabs returned empty or invalid audio payload ({len(audio_bytes)} bytes)")

        output_path = self._save_audio_file(str(inputs.get("output_path") or ""), audio_bytes, output_format)

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": model_id,
                "voice_id": voice_id,
                "voice_settings": voice_settings,
                "text_length": len(text),
                "output": str(output_path),
                "audio_path": str(output_path),
                "format": output_format,
                "endpoint": endpoint,
            },
            artifacts=[str(output_path)],
            model=model_id,
        )


def is_elevenlabs_available() -> bool:
    """Check if ElevenLabs TTS is available via environment variables."""
    key = (
        os.environ.get("ELEVENLABS_GATEWAY_API_KEY", "").strip()
        or os.environ.get("ELEVENLABS_API_KEY", "").strip()
        or os.environ.get("XI_API_KEY", "").strip()
    )
    return bool(key)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="ElevenLabs TTS Tool")
    parser.add_argument("text", nargs="?", default="Testing ElevenLabs text-to-speech integration in OpenMontage.", help="Text to synthesize")
    parser.add_argument("--voice", "-v", default="rachel", help="Voice alias (e.g. rachel, adam, charlie) or raw ElevenLabs voice ID")
    parser.add_argument("--output", "-o", default="elevenlabs_test.mp3", help="Output audio path")
    parser.add_argument("--model", "-m", default="eleven_multilingual_v2", help="Model ID")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed (0.7 - 1.2)")
    parser.add_argument("--api-key", default=None, help="Explicit API key override")
    args = parser.parse_args()

    tool = ElevenLabsTTS()
    status = tool.get_status()
    print(f"ElevenLabs tool status: {status.value}")

    req_inputs: dict[str, Any] = {
        "text": args.text,
        "voice_id": args.voice,
        "output_path": args.output,
        "model_id": args.model,
        "speed": args.speed,
    }
    if args.api_key:
        req_inputs["api_key"] = args.api_key

    result = tool.execute(req_inputs)
    if result.success:
        print(f"SUCCESS: Generated {args.output}")
        print(f"Duration: {result.duration_seconds}s, Voice ID: {result.data.get('voice_id')}")
        sys.exit(0)
    else:
        print(f"FAILED: {result.error}", file=sys.stderr)
        no_key = status == ToolStatus.UNAVAILABLE and not args.api_key
        sys.exit(0 if no_key else 1)

