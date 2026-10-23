"""OpenMontage Audio and Narration Orchestration Library."""

from lib.audio.narration_orchestrator import (
    NarrationOrchestrator,
    MediaCpuLock,
    safe_write_narration_text,
    probe_audio_duration,
)

__all__ = [
    "NarrationOrchestrator",
    "MediaCpuLock",
    "safe_write_narration_text",
    "probe_audio_duration",
]
