"""Tool wrapper for Muse-powered YouTube thumbnail generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from lib.news_visual.thumbnail_orchestrator import ThumbnailOrchestrator
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


class ThumbnailGenerator(BaseTool):
    """Generate high-converting YouTube and Shorts thumbnails using Muse Image Generation."""

    name = "thumbnail_generator"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "thumbnail_generation"
    provider = "muse"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    dependencies = ["pillow", "requests"]
    install_instructions = (
        "Requires Pillow and access to toolcase-gateway-rs running muse-image service."
    )
    agent_skills = []

    capabilities = [
        "generate_thumbnail",
        "youtube_thumbnail",
        "shorts_thumbnail",
        "headline_overlay",
    ]
    supports = {
        "aspect_ratio": True,
        "typography_overlay": True,
        "youtube_safe_zones": True,
    }
    best_for = [
        "generating YouTube 16:9 and Shorts 9:16 thumbnails via Muse",
        "high-contrast title and headline compositing",
    ]
    not_good_for = [
        "frame extraction from existing video (use video_analyzer instead)",
    ]

    input_schema = {
        "type": "object",
        "required": ["project_dir", "title"],
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "Path to the project workspace directory.",
            },
            "title": {
                "type": "string",
                "description": "Video title to extract context and headline from.",
            },
            "topic": {
                "type": "string",
                "description": "Optional topic summary for prompt crafting.",
            },
            "format": {
                "type": "string",
                "enum": ["short", "longform", "9:16", "16:9"],
                "default": "short",
                "description": "Video format (short for 9:16, longform for 16:9).",
            },
            "headline": {
                "type": "string",
                "description": "Optional custom short text to overlay on the thumbnail.",
            },
            "output_path": {
                "type": "string",
                "description": "Optional custom output image path.",
            },
            "add_headline_overlay": {
                "type": "boolean",
                "default": True,
                "description": "Whether to composite headline text overlay onto the thumbnail.",
            },
            "allow_fallback": {
                "type": "boolean",
                "default": True,
                "description": "Whether to generate stylized fallback if Muse Gateway is unreachable.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "network_error"])

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def execute(self, inputs: Dict[str, Any]) -> ToolResult:
        project_dir = inputs.get("project_dir")
        title = inputs.get("title")

        if not project_dir:
            return ToolResult(success=False, error="project_dir is required")
        if not title:
            return ToolResult(success=False, error="title is required")

        pdir = Path(project_dir).expanduser().resolve()
        if not pdir.is_dir():
            return ToolResult(success=False, error=f"project_dir does not exist: {pdir}")

        res = ThumbnailOrchestrator.generate_thumbnail(
            project_dir=pdir,
            title=title,
            topic=inputs.get("topic", ""),
            format_type=inputs.get("format", "short"),
            custom_headline=inputs.get("headline"),
            output_path=inputs.get("output_path"),
            add_headline_overlay=inputs.get("add_headline_overlay", True),
            allow_fallback=inputs.get("allow_fallback", True),
        )

        if not res.success:
            return ToolResult(
                success=False,
                error=res.error or "Failed to generate thumbnail",
                data={
                    "thumbnail_status": res.thumbnail_status,
                    "aspect_ratio": res.aspect_ratio,
                },
            )

        return ToolResult(
            success=True,
            data={
                "thumbnail_path": res.thumbnail_path,
                "thumbnail_status": res.thumbnail_status,
                "aspect_ratio": res.aspect_ratio,
                "metadata": res.metadata,
            },
            artifacts=[res.thumbnail_path] if res.thumbnail_path else [],
        )


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate YouTube thumbnail via Muse")
    parser.add_argument("--project", required=True, help="Project directory path")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--topic", default="", help="Topic summary")
    parser.add_argument("--format", default="short", choices=["short", "longform", "9:16", "16:9"])
    parser.add_argument("--headline", default=None, help="Custom headline text")
    parser.add_argument("--output", default=None, help="Custom output image path")
    args = parser.parse_args()

    tool = ThumbnailGenerator()
    out = tool.execute({
        "project_dir": args.project,
        "title": args.title,
        "topic": args.topic,
        "format": args.format,
        "headline": args.headline,
        "output_path": args.output,
    })

    if out.success:
        print(f"SUCCESS: Generated thumbnail at {out.data['thumbnail_path']}")
        sys.exit(0)
    else:
        print(f"ERROR: {out.error}", file=sys.stderr)
        sys.exit(1)
