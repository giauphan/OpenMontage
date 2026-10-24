"""Kokoro-82M Local Text-to-Speech provider tool.

Runs Kokoro-82M (Apache-2.0) on CPU using a pinned local endpoint or Python wrapper.
Restricts concurrency to 1 to protect 2-vCPU systems from CPU thrashing.
"""
from __future__ import annotations

import json
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


class KokoroLocalTTS(BaseTool):
    name = "kokoro_local_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "kokoro"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    agent_skills = ["text-to-speech"]
    capabilities = ["text_to_speech", "voice_selection", "local_cpu_inference"]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "description": "Text to convert to speech"},
            "voice_id": {"type": "string", "description": "Kokoro voice ID (e.g. am_michael, af_sarah)", "default": "am_michael"},
            "speed": {"type": "number", "minimum": 0.5, "maximum": 2.0, "default": 1.0},
            "output_path": {"type": "string", "description": "Target path for output mp3 audio file"},
            "service_url": {"type": "string", "description": "Local Kokoro service URL", "default": "http://127.0.0.1:8880/v1/audio/speech"},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "audio_path": {"type": "string"},
            "duration_seconds": {"type": "number"},
            "provider": {"type": "string"},
            "voice": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1,
        ram_mb=2048,
        vram_mb=0,
        disk_mb=500,
        network_required=False,
    )

    def get_status(self) -> ToolStatus:
        # Check if local Kokoro service is available
        service_url = os.environ.get("KOKORO_SERVICE_URL", "http://127.0.0.1:8880/v1/audio/speech")
        try:
            import urllib.request
            req = urllib.request.Request(service_url.replace("/audio/speech", "/models"), method="GET")
            with urllib.request.urlopen(req, timeout=0.5):
                return ToolStatus.AVAILABLE
        except Exception:
            pass

        # Check for python kokoro or kokoro_onnx module
        try:
            import kokoro  # type: ignore
            return ToolStatus.AVAILABLE
        except ImportError:
            pass

        try:
            import kokoro_onnx  # type: ignore
            return ToolStatus.AVAILABLE
        except ImportError:
            pass

        return ToolStatus.UNCONFIGURED

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        text = inputs.get("text", "").strip()
        if not text:
            return ToolResult(success=False, error="Narration text is empty or missing")

        voice_id = inputs.get("voice_id", "am_michael")
        speed = float(inputs.get("speed", 1.0))
        output_path = Path(inputs.get("output_path", "/tmp/kokoro_out.mp3")).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        service_url = inputs.get("service_url") or os.environ.get("KOKORO_SERVICE_URL", "http://127.0.0.1:8880/v1/audio/speech")

        success, duration, err = self._synthesize_kokoro(text, voice_id, speed, output_path, service_url)
        if not success:
            return ToolResult(success=False, error=err or "Kokoro synthesis failed")

        return ToolResult(
            success=True,
            data={
                "audio_path": str(output_path),
                "duration_seconds": round(duration, 3),
                "provider": self.provider,
                "voice": voice_id,
            }
        )

    def _synthesize_kokoro(
        self, text: str, voice_id: str, speed: float, output_path: Path, service_url: str
    ) -> tuple[bool, float, str | None]:
        from lib.audio.narration_orchestrator import probe_audio_duration

        # 1. Try local HTTP service if reachable
        try:
            import requests
            payload = {
                "model": "kokoro",
                "input": text,
                "voice": voice_id,
                "speed": speed,
                "response_format": "mp3",
            }
            resp = requests.post(service_url, json=payload, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 100:
                tmp_out = output_path.with_suffix(".tmp.mp3")
                tmp_out.write_bytes(resp.content)
                dur = probe_audio_duration(tmp_out)
                if dur > 0:
                    os.replace(tmp_out, output_path)
                    return True, dur, None
        except Exception:
            pass

        # 2. Try direct local kokoro_onnx inference with cached ONNX weights
        try:
            import kokoro_onnx
            import soundfile as sf
            import re
            import numpy as np
            for m_path, v_path in [
                ("/home/ubuntu/.cache/hyperframes/tts/models/kokoro-v1.0.onnx", "/home/ubuntu/.cache/hyperframes/tts/voices/voices-v1.0.bin"),
                (str(Path.home() / ".cache/hyperframes/tts/models/kokoro-v1.0.onnx"), str(Path.home() / ".cache/hyperframes/tts/voices/voices-v1.0.bin")),
            ]:
                if Path(m_path).is_file() and Path(v_path).is_file():
                    kokoro_model = kokoro_onnx.Kokoro(m_path, v_path)
                    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
                    if not sentences:
                        sentences = [text]
                    all_samples = []
                    sample_rate = 24000
                    for s in sentences:
                        s_samples, sr = kokoro_model.create(s, voice=voice_id, speed=speed)
                        sample_rate = sr
                        all_samples.append(s_samples)
                        # 0.2s pause between sentences
                        all_samples.append(np.zeros(int(sr * 0.2), dtype=np.float32))

                    combined = np.concatenate(all_samples)
                    tmp_wav = output_path.with_suffix(".tmp.wav")
                    sf.write(str(tmp_wav), combined, sample_rate)
                    subprocess.run(
                        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)],
                        check=True
                    )
                    if tmp_wav.exists():
                        tmp_wav.unlink()
                    dur = probe_audio_duration(output_path)
                    if dur > 0:
                        return True, dur, None
        except Exception:
            pass

        # 3. Try Python kokoro module directly if installed
        try:
            from kokoro import KPipeline
            import soundfile as sf

            pipeline = KPipeline(lang_code="a")
            generator = pipeline(text, voice=voice_id, speed=speed, split_pattern=r"\n+")
            all_audio = []
            sample_rate = 24000
            for _, _, audio in generator:
                all_audio.append(audio)

            if all_audio:
                import numpy as np
                combined = np.concatenate(all_audio)
                tmp_wav = output_path.with_suffix(".tmp.wav")
                sf.write(str(tmp_wav), combined, sample_rate)
                # Convert WAV to MP3 with ffmpeg
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)],
                    check=True
                )
                if tmp_wav.exists():
                    tmp_wav.unlink()
                dur = probe_audio_duration(output_path)
                if dur > 0:
                    return True, dur, None
        except Exception:
            pass

        return False, 0.0, "No Kokoro backend (HTTP service or library) could synthesize the requested audio"
