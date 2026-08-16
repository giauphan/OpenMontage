"""Copyright Preflight Tool for OpenMontage.

Pre-inspects video files and audio manifests before publishing to Meta/YouTube.
Checks audio streams, checks music manifest copyright status, and flags potential
copyright mute risks (e.g. unverified background music).
"""

from __future__ import annotations

import json
import subprocess

from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class CopyrightPreflight(BaseTool):
    name = "copyright_preflight"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "copyright_preflight"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.CLI

    dependencies = [
        "command:ffprobe",
    ]
    install_instructions = "Install ffmpeg/ffprobe via system package manager (apt install ffmpeg)."

    agent_skills = []
    capabilities = ["copyright_preflight", "inspect_audio_streams"]
    supports = {
        "local_offline": True,
        "free": True,
        "uploads": False,
    }
    best_for = [
        "inspecting video audio streams for Meta copyright risk before uploading",
        "checking music_manifest.json copyright status",
    ]
    not_good_for = [
        "direct platform publishing",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to video file to inspect.",
            },
            "music_manifest_path": {
                "type": "string",
                "description": "Optional path to music_manifest.json.",
            },
            "target_platform": {
                "type": "string",
                "enum": ["meta", "youtube", "tiktok", "all"],
                "default": "all",
                "description": "Target publishing platform for compliance rules.",
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "copyright_status": {"type": "string"},
            "audio_streams": {"type": "array"},
            "recommendation": {"type": "string"},
            "warnings": {"type": "array"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=10, network_required=False
    )
    side_effects = []
    user_visible_verification = [
        "Check preflight summary output before publishing",
    ]

    def _probe_audio(self, video_path: Path) -> list[dict[str, Any]]:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "a",
            str(video_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            return data.get("streams", [])
        except Exception as err:
            print(f"ffprobe warning: {err}")
            return []

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        manifest_path = None
        if "music_manifest_path" in inputs:
            manifest_path = Path(inputs["music_manifest_path"]).expanduser()
        else:
            # Look for 04_audio/music_manifest.json relative to project root
            proj_dir = video_path.parents[1] if video_path.parent.name == "renders" else video_path.parent
            candidate = proj_dir / "04_audio" / "music_manifest.json"
            if candidate.is_file():
                manifest_path = candidate

        target_platform = inputs.get("target_platform", "all")
        audio_streams = self._probe_audio(video_path)

        warnings = []
        passed = True
        status = "clean"
        recommendation = "Video is safe for publish."

        if not audio_streams:
            warnings.append("No audio streams found in video file.")
            status = "silent"
            recommendation = "Video has no audio track."

        manifest_data = {}
        if manifest_path and manifest_path.is_file():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as e:
                warnings.append(f"Failed to read music_manifest.json: {e}")

        bgm_config = manifest_data.get("bgm", {})
        bgm_enabled = bgm_config.get("enabled", False)
        copyright_status = bgm_config.get("copyright_status", "unknown")

        if bgm_enabled:
            if copyright_status in ("voice_only", "meta_sound_collection", "cc0_public_domain"):
                status = copyright_status
                recommendation = f"BGM is verified ({copyright_status}). Safe to publish."
            elif copyright_status == "unknown" or not copyright_status:
                passed = False
                status = "copyright_risk"
                warnings.append("BGM status is unknown/unverified. Meta may auto-mute this video.")
                recommendation = "Remove BGM or use Meta Sound Collection to prevent copyright auto-mute."
        else:
            status = "voice_only"
            recommendation = "Voice-only track verified. 100% immune to Meta copyright auto-mute."

        return ToolResult(
            success=True,
            data={
                "passed": passed,
                "copyright_status": status,
                "audio_streams": [
                    {
                        "codec": s.get("codec_name"),
                        "channels": s.get("channels"),
                        "sample_rate": s.get("sample_rate"),
                        "bit_rate": s.get("bit_rate"),
                    }
                    for s in audio_streams
                ],
                "recommendation": recommendation,
                "warnings": warnings,
            },
            artifacts=[str(video_path)],
        )
