"""OmniRoute text-to-speech provider tool.

Routes text-to-speech requests through an authorized OmniRoute proxy gateway
(OpenAI-compatible /v1/audio/speech interface) to ElevenLabs or other backends.
Does not alter direct ElevenLabs tool configurations.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

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


class OmniRouteTTS(BaseTool):
    name = "omniroute_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "omniroute"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    agent_skills = ["text-to-speech", "elevenlabs"]
    capabilities = ["text_to_speech", "voice_selection", "cloud_proxy"]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "description": "Text to convert to speech"},
            "voice_id": {"type": "string", "description": "Voice identifier (e.g. rachel, alloy)", "default": "rachel"},
            "model_id": {"type": "string", "description": "OmniRoute model alias (e.g. el/eleven_multilingual_v2)", "default": "el/eleven_multilingual_v2"},
            "output_path": {"type": "string", "description": "Target path for output mp3 audio file"},
            "speed": {"type": "number", "minimum": 0.25, "maximum": 4.0, "default": 1.0},
            "api_key": {"type": "string", "description": "Optional override for OMNIROUTE_API_KEY"},
            "base_url": {"type": "string", "description": "Optional override for OMNIROUTE_BASE_URL"},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "audio_path": {"type": "string"},
            "duration_seconds": {"type": "number"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1,
        ram_mb=512,
        vram_mb=0,
        disk_mb=100,
        network_required=True,
    )

    def get_status(self) -> ToolStatus:
        key = os.environ.get("OMNIROUTE_API_KEY")
        if not key:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        import requests

        text = inputs.get("text", "").strip()
        if not text:
            return ToolResult(success=False, error="Narration text is empty or missing")

        voice_id = inputs.get("voice_id", "rachel")
        model_id = inputs.get("model_id", "el/eleven_multilingual_v2")
        speed = float(inputs.get("speed", 1.0))
        output_path = Path(inputs.get("output_path", "/tmp/omniroute_out.mp3")).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        base_url = inputs.get("base_url") or os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
        api_key = inputs.get("api_key") or os.environ.get("OMNIROUTE_API_KEY", "")

        endpoint = f"{base_url.rstrip('/')}/audio/speech"
        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model_id,
            "input": text,
            "voice": voice_id,
            "response_format": "mp3",
            "speed": speed,
        }

        tmp_out = output_path.with_suffix(".tmp.mp3")
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=45)
            if resp.status_code != 200:
                return ToolResult(
                    success=False,
                    error=f"OmniRoute TTS request failed with HTTP {resp.status_code}: {resp.text[:300]}"
                )

            audio_bytes = resp.content
            if not audio_bytes or len(audio_bytes) < 10:
                return ToolResult(
                    success=False,
                    error=f"OmniRoute returned empty or invalid audio payload ({len(audio_bytes)} bytes)"
                )

            tmp_out.write_bytes(audio_bytes)

            from lib.audio.narration_orchestrator import probe_audio_duration
            duration = probe_audio_duration(tmp_out)
            if duration <= 0:
                if tmp_out.exists():
                    tmp_out.unlink()
                return ToolResult(success=False, error="Generated audio failed ffprobe duration check")

            os.replace(tmp_out, output_path)

            return ToolResult(
                success=True,
                data={
                    "audio_path": str(output_path),
                    "duration_seconds": round(duration, 3),
                    "provider": self.provider,
                    "model": model_id,
                    "voice": voice_id,
                }
            )
        except Exception as e:
            if tmp_out.exists():
                tmp_out.unlink()
            return ToolResult(success=False, error=f"OmniRoute TTS execution error: {e}")
