#!/usr/bin/env python3
"""Codex Agent Strict Quality Validation for Docker Pipeline.

This script implements strict quality validation using Codex agent (with Claude CLI
compatibility) to ensure videos meet all quality thresholds before platform publishing.
If CLI agents are rate-limited or offline, an autonomous evaluation agent validates
the visual, audio sync, content appropriateness, and brand compliance criteria.

Integration Points:
- Runs natively in Docker container on sandbox-video host
- Called after HyperFrames rendering in run_daily_news_pipeline.sh
- Provides 🟢 STRICT QUALITY PASS or 🔴 VALIDATION FAIL
- Supports retry mechanism (1-2 attempts)

Usage:
    python3 scripts/codex_agent_validation.py <project_dir> [--strict] [--retry 2]
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
import unicodedata as _ud

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.media_integrity import verify_image_integrity, verify_video_integrity

logger = logging.getLogger(__name__)

# Try to import pipeline monitoring
try:
    from scripts.pipeline_monitoring import log_pipeline_error, log_pipeline_success
except ImportError:
    log_pipeline_error = None
    log_pipeline_success = None

# Try to import validation status logger
try:
    from scripts.validation_status import ValidationStatusLogger
except ImportError:
    try:
        from validation_status import ValidationStatusLogger
    except ImportError:
        ValidationStatusLogger = None

# Re-exports from codex_validation_toml
from scripts.codex_validation_toml import (
    _TOML_INT_RE,
    _TOML_FLOAT_RE,
    _TOML_DATETIME_RE,
    _TOML_KEY_SEG_RE,
    _toml_close_quote,
    _toml_validate_basic_string_inner,
    _toml_rstrip_comment,
    _toml_valid_key,
    _toml_split_top,
    _toml_validate_scalar,
    _toml_validate_array,
    _toml_validate_inline_table,
    _strict_toml_validate,
    parse_and_validate_config_toml,
    _validate_profile_dir,
    resolve_and_validate_codex_home,
)

# Re-exports from codex_validation_checks
from scripts.codex_validation_checks import (
    MIN_DURATION,
    MAX_BLACK_RATIO,
    MIN_EDGE_DENSITY,
    MAX_STATIC_RATIO,
    SILENCE_THRESHOLD_DB,
    EXPECTED_EXTRACTED_FRAMES,
    MIN_FRAME_BYTES,
    REVIEW_KEYS,
    compute_sha256,
    is_network_available,
    resolve_ffprobe_ffmpeg,
    _probe_audio_streams,
    resolve_codex_cli,
    resolve_claude_cli,
    resolve_agent_cli,
    _json_values,
    _is_review_dict,
    _pick_review_dict,
    parse_codex_review,
    parse_claude_review,
    validate_technical_contract_helper,
    validate_content_quality_helper,
    validate_metadata_helper,
    extract_frames_helper,
    autonomous_quality_review_helper,
)

# Re-exports from codex_validation_review
from scripts.codex_validation_review import (
    build_review_prompt,
    execute_cli_review_helper,
    codex_agent_strict_review_helper,
)


@dataclass
class ValidationResult:
    """Represents the result of a single validation check."""

    check_name: str
    passed: bool
    message: str
    details: Dict = field(default_factory=dict)


class CodexAgentValidator:
    """Performs strict quality validation using Codex AI agent with fallback quality engine."""

    def __init__(
        self,
        project_dir: Path,
        strict_mode: bool = True,
        retry_count: int = 2,
        *,
        review_transport: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.strict_mode = strict_mode
        self.retry_count = retry_count
        # Test/rehearsal-only injection. None preserves the production CLI path.
        self._review_transport = review_transport
        self.results: List[ValidationResult] = []
        self._content_cache: Dict[tuple[str, str, str], tuple[ValidationResult, ...]] = {}

    def validate_technical_contract(
        self,
        video_path: Path,
        ffprobe_bin: Optional[str] = None,
        ffmpeg_bin: Optional[str] = None,
    ) -> List[ValidationResult]:
        """Validate technical video contract (exists, duration, codecs, dimensions)."""
        return validate_technical_contract_helper(
            video_path=video_path,
            result_factory=ValidationResult,
            ffprobe_bin=ffprobe_bin,
            ffmpeg_bin=ffmpeg_bin,
        )

    def validate_content_quality(
        self,
        video_path: Path,
        ffprobe_bin: str,
        ffmpeg_bin: str,
    ) -> List[ValidationResult]:
        """Run deterministic strict content checks before agent review."""
        return validate_content_quality_helper(
            validator_self=self,
            video_path=video_path,
            ffprobe_bin=ffprobe_bin,
            ffmpeg_bin=ffmpeg_bin,
            result_factory=ValidationResult,
        )

    def validate_metadata(self, metadata_path: Path) -> List[ValidationResult]:
        """Validate metadata quality."""
        return validate_metadata_helper(
            validator_self=self,
            metadata_path=metadata_path,
            result_factory=ValidationResult,
        )

    def _extract_frames(self, video_path: Path, out_dir: Path) -> List[Path]:
        """Extract representative frames for visual quality review."""
        return extract_frames_helper(video_path=video_path, out_dir=out_dir)

    def _autonomous_quality_review(
        self,
        video_path: Path,
        metadata_path: Path,
        prior_results: Optional[List[ValidationResult]] = None,
        frame_paths: Optional[List[Path]] = None,
    ) -> List[ValidationResult]:
        """Autonomous AI quality agent evaluation for visual, audio sync, content, and brand compliance."""
        return autonomous_quality_review_helper(
            validator_self=self,
            video_path=video_path,
            metadata_path=metadata_path,
            result_factory=ValidationResult,
            prior_results=prior_results,
            frame_paths=frame_paths,
        )

    def _execute_cli_review(
        self,
        agent_bin: str,
        video_path: Path,
        metadata_path: Path,
        prior_results: Optional[List[ValidationResult]] = None,
    ) -> List[ValidationResult]:
        """Execute review via CLI binary and parse result."""
        return execute_cli_review_helper(
            validator_self=self,
            agent_bin=agent_bin,
            video_path=video_path,
            metadata_path=metadata_path,
            result_factory=ValidationResult,
            prior_results=prior_results,
        )

    def codex_agent_strict_review(
        self,
        video_path: Path,
        metadata_path: Path,
        prior_results: Optional[List[ValidationResult]] = None,
    ) -> List[ValidationResult]:
        """Codex Agent review with strict enforcement and fail-closed security."""
        return codex_agent_strict_review_helper(
            validator_self=self,
            video_path=video_path,
            metadata_path=metadata_path,
            result_factory=ValidationResult,
            prior_results=prior_results,
        )

    claude_agent_strict_review = codex_agent_strict_review

    def execute_validation(
        self,
        video_paths: List[Path],
        metadata_path: Path,
        ffprobe_bin: str = "ffprobe",
        ffmpeg_bin: str = "ffmpeg",
    ) -> Dict:
        """Execute full validation pipeline."""
        all_results = []

        # Step 1: Technical Contract Validation
        for video_path in video_paths:
            tech_results = self.validate_technical_contract(video_path)
            all_results.extend(tech_results)

        # Step 2: Content Quality Validation
        for video_path in video_paths:
            content_results = self.validate_content_quality(video_path, ffprobe_bin, ffmpeg_bin)
            all_results.extend(content_results)

        # Step 3: Metadata Validation
        meta_results = self.validate_metadata(metadata_path)
        all_results.extend(meta_results)

        # Step 4: Codex Agent Review
        if self.strict_mode:
            deterministic_failed = any(not r.passed for r in all_results)
            if not deterministic_failed:
                for video_path in video_paths:
                    agent_results = self.codex_agent_strict_review(video_path, metadata_path, prior_results=all_results)
                    all_results.extend(agent_results)

        self.results = all_results

        failed_checks = [r for r in all_results if not r.passed]
        passed_checks = [r for r in all_results if r.passed]
        overall_passed = len(failed_checks) == 0

        return {
            "overall_status": "PASS" if overall_passed else "FAIL",
            "total_checks": len(all_results),
            "passed_checks": len(passed_checks),
            "failed_checks": len(failed_checks),
            "results": all_results,
            "color": "🟢" if overall_passed else "🔴",
            "strict_quality_pass": overall_passed,
        }

    def print_validation_report(self, validation_data: Dict) -> None:
        """Print validation report."""
        print("=" * 60)
        print("CODEX AGENT STRICT QUALITY VALIDATION REPORT")
        print("=" * 60)
        print(f"Overall Status: {validation_data['color']} {validation_data['overall_status']}")
        print(f"Total Checks: {validation_data['total_checks']}")
        print(f"Passed: {validation_data['passed_checks']}, Failed: {validation_data['failed_checks']}")
        print("-" * 60)
        print("DETAILED RESULTS:")
        print("-" * 60)
        for result in validation_data["results"]:
            icon = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{icon} | {result.check_name}")
            print(f"       └─ {result.message}")
            if result.details:
                for k, v in result.details.items():
                    print(f"       └─ {k}: {v}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Codex Agent Strict Quality Validation")
    parser.add_argument("project_dir", type=str, help="Project directory to validate")
    parser.add_argument("--strict", action="store_true", default=None, help="Enable strict mode")
    parser.add_argument("--no-strict", dest="strict", action="store_false", help="Disable strict mode")
    parser.add_argument("--retry", type=int, default=3, help="Maximum retry attempts")
    parser.add_argument("--ffprobe", type=str, default="ffprobe", help="Path to ffprobe binary")
    parser.add_argument("--ffmpeg", type=str, default="ffmpeg", help="Path to ffmpeg binary")
    parser.add_argument(
        "--test-review-reply", type=Path, default=None,
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()
    if args.test_review_reply is not None:
        if os.environ.get("OPENMONTAGE_REHEARSAL") != "1":
            parser.error("--test-review-reply is only allowed in rehearsal mode")
        project_root = Path(args.project_dir)
        project_marker = project_root / ".openmontage-test-only"
        release_marker = project_root / "OFFLINE_REHEARSAL_TEST_ONLY.json"
        if not project_marker.is_file() or not release_marker.is_file() or release_marker.is_symlink():
            parser.error("test reviewer transport requires both test-only markers, including the canonical release-blocking marker")
        try:
            marker_data = json.loads(release_marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            parser.error(f"invalid canonical test-only marker: {exc}")
        if marker_data != {"test_only": True, "purpose": "daily-news-rehearsal"}:
            parser.error("canonical test-only marker contents are invalid")
        try:
            reply_text = args.test_review_reply.read_text(encoding="utf-8")
            json.loads(reply_text)
        except (OSError, ValueError) as exc:
            parser.error(f"invalid frozen reviewer reply: {exc}")
        review_transport = lambda command, **kwargs: subprocess.CompletedProcess(
            args=command, returncode=0, stdout=reply_text, stderr=""
        )
    else:
        review_transport = None

    if args.strict is None:
        args.strict = True

    project_dir = Path(args.project_dir)
    if not project_dir.exists():
        print(f"Error: Project directory not found: {project_dir}")
        sys.exit(2)

    from lib.artifact_paths import resolve_project_locale, is_english_locale, resolve_render_paths
    locale = resolve_project_locale(project_dir)
    if is_english_locale(locale):
        fmt = None
        meta_file = project_dir / "publish_metadata.json"
        if meta_file.is_file():
            try:
                meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                fmt = meta_data.get("format")
            except Exception:
                pass
        if not fmt and (project_dir / "project.json").is_file():
            try:
                pcfg = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
                fmt = pcfg.get("format")
            except Exception:
                pass

        full_path, reels_path = resolve_render_paths(project_dir, locale=locale)
        if fmt in ("short", "shorts", "reels", "9x16"):
            video_paths = [reels_path]
        elif fmt in ("long", "longform", "16x9", "full"):
            video_paths = [full_path]
        else:
            existing = [p for p in (reels_path, full_path) if p.is_file()]
            video_paths = existing if existing else [reels_path]
    else:
        video_paths = [
            project_dir / "renders" / "final_full_vi_9x16.mp4",
            project_dir / "renders" / "final_reels_vi_9x16.mp4",
        ]
    metadata_path = project_dir / "publish_metadata.json"

    validator = CodexAgentValidator(
        project_dir=project_dir,
        strict_mode=args.strict,
        retry_count=args.retry,
        review_transport=review_transport,
    )

    ffprobe_bin, ffmpeg_bin = resolve_ffprobe_ffmpeg()
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

    if ValidationStatusLogger is not None:
        logger_inst = ValidationStatusLogger(project_dir=project_dir)
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

    if validation_data["overall_status"] == "PASS":
        if log_pipeline_success is not None:
            log_pipeline_success(
                stage="codex_validation",
                project_id=project_dir.name,
                message=f"Strict validation passed ({validation_data['passed_checks']}/{validation_data['total_checks']} checks)",
            )
        print(f"Result: {validation_data['color']} STRICT QUALITY PASS")
        sys.exit(0)
    else:
        if log_pipeline_error is not None:
            log_pipeline_error(
                stage="codex_validation",
                project_id=project_dir.name,
                error_type="VALIDATION_FAILED",
                message=f"Strict validation failed ({validation_data['failed_checks']}/{validation_data['total_checks']} checks failed)",
                details={"failed_checks": [r.message for r in validation_data["results"] if not r.passed]},
            )
        print(f"Result: {validation_data['color']} VALIDATION FAILED")
        deterministic_failed = any(
            not r.passed for r in validation_data.get("results", [])
            if r.check_name in (
                "Technical Contract", "Duration Check", "Stream Integrity",
                "Content Quality", "Metadata Validation", "Metadata Structure",
                "Metadata Language"
            )
        )
        sys.exit(2 if deterministic_failed else 1)


if __name__ == "__main__":
    main()

# Compatibility aliases
CLAUDEAgentValidator = CodexAgentValidator
claude_agent_strict_review = CodexAgentValidator.codex_agent_strict_review
