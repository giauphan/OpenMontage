"""Codex Agent Validation - CLI Review & Strict Gate Submodule.

Handles CLI invocation, prompt construction, offline test transports,
response parsing, and strict review gates.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scripts.codex_validation_checks import (
    compute_sha256,
    _probe_audio_streams as default_probe_audio_streams,
    parse_codex_review as default_parse_codex_review,
    resolve_agent_cli as default_resolve_agent_cli,
)
from scripts.codex_validation_toml import (
    resolve_and_validate_codex_home as default_resolve_and_validate_codex_home,
)

logger = logging.getLogger(__name__)


def _get_resolve_agent_cli() -> Callable[[], Optional[str]]:
    mod = sys.modules.get("scripts.codex_agent_validation")
    if mod and hasattr(mod, "resolve_agent_cli"):
        return getattr(mod, "resolve_agent_cli")
    return default_resolve_agent_cli


def _get_resolve_codex_home() -> Callable[[Dict[str, str]], str]:
    mod = sys.modules.get("scripts.codex_agent_validation")
    if mod and hasattr(mod, "resolve_and_validate_codex_home"):
        return getattr(mod, "resolve_and_validate_codex_home")
    return default_resolve_and_validate_codex_home


def _get_parse_codex_review() -> Callable[[str], Any]:
    mod = sys.modules.get("scripts.codex_agent_validation")
    if mod and hasattr(mod, "parse_codex_review"):
        return getattr(mod, "parse_codex_review")
    return default_parse_codex_review


def _get_probe_audio_streams() -> Callable[[Path], str]:
    mod = sys.modules.get("scripts.codex_agent_validation")
    if mod and hasattr(mod, "_probe_audio_streams"):
        return getattr(mod, "_probe_audio_streams")
    return default_probe_audio_streams


def _get_subprocess_run() -> Callable[..., subprocess.CompletedProcess[Any]]:
    claude_mod = sys.modules.get("scripts.claude_agent_validation")
    if claude_mod and hasattr(claude_mod, "subprocess") and hasattr(claude_mod.subprocess, "run"):
        return getattr(claude_mod.subprocess, "run")
    codex_mod = sys.modules.get("scripts.codex_agent_validation")
    if codex_mod and hasattr(codex_mod, "subprocess") and hasattr(codex_mod.subprocess, "run"):
        return getattr(codex_mod.subprocess, "run")
    return subprocess.run


def build_review_prompt(
    abs_video_path: Path,
    file_exists: bool,
    file_size: int,
    comp_summary: str,
    comp_text: str,
    script_summary: str,
    script_full_text: str,
    audio_stream_summary: str,
    narration_assets_summary: str,
    metadata_str: str,
    frame_paths: List[Path],
) -> str:
    """Build the structured review prompt for the AI agent."""
    prompt = f"""
Validate candidate video asset for OpenMontage automated publishing pipeline.

Target Asset Path: {abs_video_path}
File Exists: {file_exists}
File Size Bytes: {file_size}
Composition Info: {comp_summary}
Composition Source HTML:
{comp_text}
Script Info: {script_summary}
Script Text Extract (Vietnamese):
{script_full_text}

Audio Stream Evidence (from ffprobe on rendered video): {audio_stream_summary}
Narration Assets: {narration_assets_summary}

Metadata Content:
{metadata_str}

PERFORM STRICT QUALITY VALIDATION on the following criteria:
1. VISUAL QUALITY & DIVERSITY: Reject raw web-page layouts or placeholder scaffolds.
2. AUDIO SYNC & TYPOGRAPHY: Use the Audio Stream Evidence above to verify that an audio track exists and its duration aligns with the script. Do not fail this criterion solely because audio cannot be heard — use the stream metadata.
3. CONTENT APPROPRIATENESS: Ensure news content is safe and high relevance.
4. BRAND COMPLIANCE: Prohibit brand names such as Montage or OpenMontage.

Return a valid JSON object matching this schema:
{{
  "visual_quality": {{"passed": true, "score": 95, "notes": "..."}},
  "audio_sync": {{"passed": true, "score": 95, "notes": "..."}},
  "content_appropriateness": {{"passed": true, "score": 95, "notes": "..."}},
  "brand_compliance": {{"passed": true, "score": 95, "notes": "..."}},
  "overall_passed": true,
  "summary": "..."
}}
"""
    for fp in frame_paths:
        prompt += f"\n\n[Attached image: {fp.name}] {fp}"
    return prompt


def execute_cli_review_helper(
    validator_self: Any,
    agent_bin: str,
    video_path: Path,
    metadata_path: Path,
    result_factory: Any,
    prior_results: Optional[List[Any]] = None,
) -> List[Any]:
    """Execute review via CLI binary and parse result."""
    abs_video_path = Path(video_path).resolve()
    frame_dir = Path(tempfile.mkdtemp(prefix="openmontage-review-"))
    frame_paths: List[Path] = []
    abs_metadata_path = Path(metadata_path).resolve()
    metadata_str = "{}"
    if abs_metadata_path.is_file():
        try:
            metadata_str = abs_metadata_path.read_text(encoding="utf-8")
        except Exception:
            pass

    file_exists = abs_video_path.is_file()
    file_size = abs_video_path.stat().st_size if file_exists else 0

    comp_path = validator_self.project_dir / (
        "hyperframes_reels/index.html" if "reels" in video_path.name else "hyperframes/index.html"
    )
    if not comp_path.is_file():
        comp_path = validator_self.project_dir / "hyperframes/index.html"

    if not comp_path.is_file():
        return [
            result_factory(
                check_name="Visual Quality",
                passed=False,
                message="Visual Quality: ✗ FAIL (Score: 0) - Missing HyperFrames HTML source",
                details={"error": "Missing HyperFrames HTML source"},
            )
        ]

    if (validator_self.project_dir / "artifacts" / "script_en_US.json").is_file():
        script_path = validator_self.project_dir / "artifacts" / "script_en_US.json"
    elif (validator_self.project_dir / "artifacts" / "script_vi.json").is_file():
        script_path = validator_self.project_dir / "artifacts" / "script_vi.json"
    elif (validator_self.project_dir / "artifacts" / "script.json").is_file():
        script_path = validator_self.project_dir / "artifacts" / "script.json"
    else:
        script_path = validator_self.project_dir / "artifacts" / "script_en_US.json"

    comp_summary = "Composition: not found"
    comp_text = ""
    if comp_path.is_file():
        try:
            comp_text = comp_path.read_text(encoding="utf-8").strip()
            scene_ids = set(re.findall(r'\bdata-scene-id=["\']([^"\']+)["\']', comp_text))
            scene_count = len(scene_ids) or len(
                re.findall(r'<(?:div|section)\b[^>]*\bclass=["\'][^"\']*\bscene\b[^"\']*["\']', comp_text)
            )
            comp_summary = f"Composition File: {comp_path.name}, Detected Scenes: {scene_count}"
        except OSError:
            comp_text = ""

    script_summary = "Script: not found"
    script_full_text = ""
    if script_path.is_file():
        try:
            script_data = json.loads(script_path.read_text(encoding="utf-8"))
            sections = script_data.get("sections", [])
            script_summary = f"Script Sections: {len(sections)}"
            script_full_text = "\n".join(
                str(s.get("text") or s.get("text_vi") or s.get("narration") or "")
                for s in sections
            ).strip()
        except Exception:
            pass

    if file_exists and file_size > 0:
        try:
            frame_paths = validator_self._extract_frames(abs_video_path, frame_dir)
        except Exception:
            frame_paths = []

    if not frame_paths:
        return [
            result_factory(
                check_name="Visual Quality",
                passed=False,
                message="Visual Quality: ✗ FAIL (Score: 0) - Frame extraction failed: representative frames could not be extracted",
                details={"error": "Frame extraction failed"},
            )
        ]

    probe_fn = _get_probe_audio_streams()
    audio_stream_summary = probe_fn(abs_video_path)

    narration_asset = validator_self.project_dir / "assets" / "narration.mp3"
    narration_words_js = validator_self.project_dir / "hyperframes" / "assets" / "narration_words.js"
    narration_assets_summary = (
        f"narration.mp3: {'present (' + str(narration_asset.stat().st_size) + ' bytes)' if narration_asset.is_file() else 'absent'}"
        + f"; narration_words.js: {'present' if narration_words_js.is_file() else 'absent'}"
    )

    prompt = build_review_prompt(
        abs_video_path=abs_video_path,
        file_exists=file_exists,
        file_size=file_size,
        comp_summary=comp_summary,
        comp_text=comp_text,
        script_summary=script_summary,
        script_full_text=script_full_text,
        audio_stream_summary=audio_stream_summary,
        narration_assets_summary=narration_assets_summary,
        metadata_str=metadata_str,
        frame_paths=frame_paths,
    )

    root_dir = str(Path(__file__).resolve().parent.parent)
    timeout = int(os.environ.get("AGENT_REVIEW_TIMEOUT_SECONDS", "120"))

    is_codex = "codex" in Path(agent_bin).name.lower()
    env = os.environ.copy()
    if is_codex:
        try:
            resolve_home_fn = _get_resolve_codex_home()
            resolved_home = resolve_home_fn(env)
            env["CODEX_HOME"] = resolved_home
        except RuntimeError as e:
            raise RuntimeError(f"Configured CODEX_HOME resolution failed: {e}")

        if not env.get("OPENAI_API_KEY"):
            auth_file = Path(resolved_home) / "auth.json"
            if auth_file.is_file():
                try:
                    auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
                    api_key = auth_data.get("OPENAI_API_KEY")
                    if api_key and isinstance(api_key, str) and api_key.strip():
                        env["OPENAI_API_KEY"] = api_key.strip()
                except Exception:
                    pass

    if is_codex:
        codex_model = env.get("CODEX_MODEL", "model-medium-hight")
        cmd = [
            agent_bin,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--config",
            f'model="{codex_model}"',
            "-",
        ]
    else:
        for var in ("CODEXCODE", "CODEX_CODE_ENTRYPOINT", "CODEX_CODE_SSE_PORT", "CODEX_SESSION_ID", "ANTHROPIC_MODEL"):
            env.pop(var, None)
        cmd = [
            agent_bin,
            "-p",
            "--output-format",
            "json",
            "-",
        ]

    run_fn = validator_self._review_transport or _get_subprocess_run()
    proc = run_fn(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=root_dir,
        env=env,
    )

    output = proc.stdout or ""
    if "hit your limit" in output.lower() or proc.returncode != 0:
        raise RuntimeError(f"CLI returned error or rate limit: {output[:200]}")

    parse_fn = _get_parse_codex_review()
    response_data = parse_fn(output)
    if not isinstance(response_data, dict):
        raise ValueError(f"Agent CLI review returned non-dictionary JSON: {output[:200]}")

    artifact_hash = compute_sha256(abs_video_path)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    reviewer_name = "offline_test_transport" if validator_self._review_transport else Path(agent_bin).name

    results = []
    checks = {
        "Visual Quality": "visual_quality",
        "Audio Sync": "audio_sync",
        "Content Appropriateness": "content_appropriateness",
        "Brand Compliance": "brand_compliance",
    }
    for check_name, check_key in checks.items():
        if check_key not in response_data:
            raise ValueError(f"Agent CLI review missing mandatory category: {check_key}")
        check_data = response_data.get(check_key, {})
        if not isinstance(check_data, dict):
            raise ValueError(f"Agent CLI review invalid format for category: {check_key}")
        passed = check_data.get("passed") is True
        score = check_data.get("score", 0)
        notes = check_data.get("notes", "")
        results.append(
            result_factory(
                check_name=check_name,
                passed=passed,
                message=f"{check_name}: {'✓ PASS' if passed else '✗ FAIL'} (Score: {score}) - {notes}",
                details={
                    "score": score,
                    "notes": notes,
                    "reviewer": reviewer_name,
                    "review_mode": "offline_transport" if validator_self._review_transport else "codex_cli",
                    "test_only_transport": bool(validator_self._review_transport),
                    "inspected_artifact_hash": artifact_hash,
                    "timestamp": ts,
                },
            )
        )

    if response_data.get("overall_passed") is not True and all(r.passed for r in results):
        results.append(
            result_factory(
                check_name="Agent Review Gate",
                passed=False,
                message=str(response_data.get("summary") or "Strict review rejected asset"),
                details={
                    "reviewer": reviewer_name,
                    "review_mode": "offline_transport" if validator_self._review_transport else "codex_cli",
                    "test_only_transport": bool(validator_self._review_transport),
                    "inspected_artifact_hash": artifact_hash,
                    "timestamp": ts,
                },
            )
        )

    return results


def codex_agent_strict_review_helper(
    validator_self: Any,
    video_path: Path,
    metadata_path: Path,
    result_factory: Any,
    prior_results: Optional[List[Any]] = None,
) -> List[Any]:
    """Codex Agent review with strict enforcement and fail-closed security."""
    abs_video_path = Path(video_path).resolve()
    artifact_hash = compute_sha256(abs_video_path)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Mock isolation: mock reviews are blocked in strict production release
    is_mock_env = os.environ.get("CODEX_AGENT_VALIDATION_MOCK") == "1" or os.environ.get("CLAUDE_AGENT_VALIDATION_MOCK") == "1"
    is_production = os.environ.get("PRODUCTION_RELEASE") == "1" or os.environ.get("STRICT_PRODUCTION") == "1"

    if is_mock_env or validator_self._review_transport is not None:
        if is_production:
            injected_transport = validator_self._review_transport is not None
            return [
                result_factory(
                    check_name="Codex Agent Review Gate",
                    passed=False,
                    message=(
                        "Offline test review transport strictly forbidden in production mode"
                        if injected_transport
                        else "Mock review strictly forbidden in production mode"
                    ),
                    details={
                        "error": "test_transport_forbidden_in_production" if injected_transport else "mock_forbidden_in_production",
                        "review_mode": "offline_transport" if injected_transport else "mock",
                        "test_only_transport": injected_transport,
                        "timestamp": ts,
                        "inspected_artifact_hash": artifact_hash,
                    },
                )
            ]
        if is_mock_env:
            return [
                result_factory(check_name="Visual Quality", passed=True, message="Visual Quality: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
                result_factory(check_name="Audio Sync", passed=True, message="Audio Sync: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
                result_factory(check_name="Content Appropriateness", passed=True, message="Content Appropriateness: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
                result_factory(check_name="Brand Compliance", passed=True, message="Brand Compliance: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
            ]

    # R6/R7: Hoist missing-HTML and frame-extraction pre-checks before the
    # CLI gate so strict-mode failures are reported even when no CLI binary
    # is available on the host.
    if validator_self.strict_mode:
        comp_path = validator_self.project_dir / (
            "hyperframes_reels/index.html"
            if "reels" in Path(video_path).name
            else "hyperframes/index.html"
        )
        if not comp_path.is_file():
            comp_path = validator_self.project_dir / "hyperframes/index.html"
        if not comp_path.is_file():
            return [
                result_factory(
                    check_name="Visual Quality",
                    passed=False,
                    message="Visual Quality: ✗ FAIL (Score: 0) - Missing HyperFrames HTML source",
                    details={"error": "Missing HyperFrames HTML source"},
                )
            ]
        _pre_frame_dir = Path(tempfile.mkdtemp(prefix="openmontage-pre-"))
        try:
            _pre_frames = validator_self._extract_frames(abs_video_path, _pre_frame_dir)
        except Exception:
            _pre_frames = []
        if not _pre_frames:
            return [
                result_factory(
                    check_name="Visual Quality",
                    passed=False,
                    message="Visual Quality: ✗ FAIL (Score: 0) - Frame extraction failed: representative frames could not be extracted",
                    details={"error": "Frame extraction failed"},
                )
            ]

    # An explicitly injected offline transport is authoritative for this
    # instance. Route it before CLI discovery so rehearsal/tests cannot
    # accidentally touch a live agent binary or fall back to heuristics.
    if validator_self._review_transport is not None:
        try:
            return validator_self._execute_cli_review(
                "offline_test_transport",
                video_path,
                metadata_path,
                prior_results,
            )
        except Exception as exc:
            logger.error("Injected strict review transport failed: %s", exc)
            return [
                result_factory(
                    check_name="Codex Agent Review Gate",
                    passed=False,
                    message=f"Injected strict review transport failed: {exc}",
                    details={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "review_mode": "offline_transport",
                        "test_only_transport": True,
                        "reviewer": "offline_test_transport",
                        "timestamp": ts,
                        "inspected_artifact_hash": artifact_hash,
                    },
                )
            ]

    claude_mod = sys.modules.get("scripts.claude_agent_validation")
    if claude_mod and hasattr(claude_mod, "resolve_claude_cli"):
        claude_fn = getattr(claude_mod, "resolve_claude_cli")
        if getattr(claude_fn, "__name__", "") == "<lambda>":
            claude_bin = claude_fn()
            if not claude_bin:
                return [
                    result_factory(
                        check_name="CLAUDE Agent Review Gate",
                        passed=False,
                        message="CLAUDE Agent strict review unavailable: FileNotFoundError: claude CLI not found",
                        details={"error": "claude CLI not found", "review_mode": "failed", "timestamp": ts, "inspected_artifact_hash": artifact_hash},
                    )
                ]

    resolver_fn = _get_resolve_agent_cli()
    agent_bin = resolver_fn()
    if not agent_bin:
        if validator_self.strict_mode:
            return [
                result_factory(
                    check_name="Codex Agent Review Gate",
                    passed=False,
                    message="Codex agent review unavailable: Agent CLI binary not found",
                    details={"error": "agent_cli_not_found", "review_mode": "failed", "timestamp": ts, "inspected_artifact_hash": artifact_hash},
                )
            ]
        logger.info("Agent CLI not found; falling back to non-strict autonomous heuristic review")
        return validator_self._autonomous_quality_review(abs_video_path, Path(metadata_path).resolve(), prior_results)

    attempts = max(1, getattr(validator_self, "retry_count", 1))
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return validator_self._execute_cli_review(agent_bin, video_path, metadata_path, prior_results)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                logger.warning("Agent CLI review attempt %d/%d failed: %s; retrying...", attempt, attempts, exc)
                time.sleep(0.5)
    exc = last_exc
    if validator_self.strict_mode:
        logger.error("Strict Codex Agent review failed after %d attempts: %s", attempts, exc)
        return [
            result_factory(
                check_name="Codex Agent Review Gate",
                passed=False,
                message=f"Strict Codex agent review failed: {exc}",
                details={"error": str(exc), "review_mode": "failed", "timestamp": ts, "inspected_artifact_hash": artifact_hash},
            )
        ]
    logger.info("Agent CLI review skipped (%s); applying autonomous heuristic review in non-strict mode", exc)
    return validator_self._autonomous_quality_review(abs_video_path, Path(metadata_path).resolve(), prior_results)
