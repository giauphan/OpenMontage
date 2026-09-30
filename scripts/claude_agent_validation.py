#!/usr/bin/env python3
"""Compatibility shim delegating to codex_agent_validation."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import subprocess

from scripts.codex_agent_validation import (
    CLAUDEAgentValidator,
    CodexAgentValidator,
    ValidationResult,
    ValidationStatusLogger,
    parse_codex_review,
    resolve_claude_cli,
    resolve_codex_cli,
    resolve_ffprobe_ffmpeg,
)

def parse_claude_review(response_text: str) -> dict:
    try:
        return parse_codex_review(response_text)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Agent CLI error:"):
            raise ValueError(message.replace("Agent CLI error:", "Claude CLI error:", 1)) from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex Agent Strict Quality Validation")
    parser.add_argument("project_dir", type=Path, help="Project directory to validate")
    parser.add_argument("--strict", action="store_true", default=True, help="Enable strict mode")
    parser.add_argument("--no-strict", action="store_false", dest="strict", help="Disable strict mode")
    parser.add_argument("--retry", type=int, default=3, help="Maximum retry attempts")
    parser.add_argument("--ffprobe", type=str, default="ffprobe", help="Path to ffprobe binary")
    parser.add_argument("--ffmpeg", type=str, default="ffmpeg", help="Path to ffmpeg binary")

    args = parser.parse_args()
    project_dir = args.project_dir.resolve()

    if not project_dir.exists():
        print(f"ERROR: Project directory does not exist: {project_dir}", file=sys.stderr)
        return 1

    video_paths = [
        project_dir / "renders" / "final_full_vi_9x16.mp4",
        project_dir / "renders" / "final_reels_vi_9x16.mp4",
    ]
    metadata_path = project_dir / "publish_metadata.json"

    this_mod = sys.modules[__name__]
    validator_cls = getattr(this_mod, "CLAUDEAgentValidator", CodexAgentValidator)
    validator = validator_cls(project_dir=project_dir, strict_mode=args.strict)

    ff_resolver = getattr(this_mod, "resolve_ffprobe_ffmpeg", resolve_ffprobe_ffmpeg)
    ffprobe_bin, ffmpeg_bin = ff_resolver()
    if args.ffprobe != "ffprobe":
        ffprobe_bin = args.ffprobe
    if args.ffmpeg != "ffmpeg":
        ffmpeg_bin = args.ffmpeg

    validation_data = validator.execute_validation(
        video_paths=video_paths,
        metadata_path=metadata_path,
        ffprobe_bin=ffprobe_bin,
        ffmpeg_bin=ffmpeg_bin,
    )

    validator.print_validation_report(validation_data)

    logger_cls = getattr(this_mod, "ValidationStatusLogger", ValidationStatusLogger)
    if logger_cls is not None:
        logger_inst = logger_cls(project_dir=project_dir)
        from dataclasses import asdict
        serializable = dict(validation_data)
        res_list = serializable.get("results", [])
        serializable["results"] = [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in res_list]

        logger_inst.log_validation_result(
            project_id=project_dir.name,
            status=serializable["overall_status"],
            total_checks=serializable["total_checks"],
            passed=serializable["passed_checks"],
            failed=serializable["failed_checks"],
            details=serializable,
        )

    return 0 if validation_data.get("overall_status") == "PASS" else 1

if __name__ == "__main__":
    sys.exit(main())
