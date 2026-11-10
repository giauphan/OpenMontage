"""Codex Agent Validation - CLI Review & Strict Gate Submodule.

Handles CLI invocation, prompt construction, offline test transports,
response parsing, and strict review gates.
"""

from __future__ import annotations

import json
import base64
import hashlib
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

CODEX_AGENT_VALIDATION_MODULE = "scripts.codex_agent_validation"
HYPERFRAMES_INDEX_HTML = "hyperframes/index.html"
CHECK_NAME_VISUAL_QUALITY = "Visual Quality"
SCRIPT_EN_US_JSON = "script_en_US.json"
CHECK_NAME_CODEX_GATE = "Codex Agent Review Gate"


def _get_resolve_agent_cli() -> Callable[[], Optional[str]]:
    mod = sys.modules.get(CODEX_AGENT_VALIDATION_MODULE)
    if mod and hasattr(mod, "resolve_agent_cli"):
        return getattr(mod, "resolve_agent_cli")
    return default_resolve_agent_cli


def _get_resolve_codex_home() -> Callable[[Dict[str, str]], str]:
    mod = sys.modules.get(CODEX_AGENT_VALIDATION_MODULE)
    if mod and hasattr(mod, "resolve_and_validate_codex_home"):
        return getattr(mod, "resolve_and_validate_codex_home")
    return default_resolve_and_validate_codex_home


def _get_parse_codex_review() -> Callable[[str], Any]:
    mod = sys.modules.get(CODEX_AGENT_VALIDATION_MODULE)
    if mod and hasattr(mod, "parse_codex_review"):
        return getattr(mod, "parse_codex_review")
    return default_parse_codex_review


def _get_probe_audio_streams() -> Callable[[Path], str]:
    mod = sys.modules.get(CODEX_AGENT_VALIDATION_MODULE)
    if mod and hasattr(mod, "_probe_audio_streams"):
        return getattr(mod, "_probe_audio_streams")
    return default_probe_audio_streams


def _get_subprocess_run() -> Callable[..., subprocess.CompletedProcess[Any]]:
    claude_mod = sys.modules.get("scripts.claude_agent_validation")
    if claude_mod and hasattr(claude_mod, "subprocess") and hasattr(claude_mod.subprocess, "run"):
        return getattr(claude_mod.subprocess, "run")
    codex_mod = sys.modules.get(CODEX_AGENT_VALIDATION_MODULE)
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
4. BRAND COMPLIANCE: Prohibit VISIBLE on-screen or spoken brand names such as Montage or OpenMontage. Internal HTML comments or CSS markers (such as `<!-- OPENMONTAGE_ASR_CAPTIONS_BEGIN -->`, `<!-- OPENMONTAGE_ASR_CAPTIONS_END -->`, `// OPENMONTAGE_CONTINUOUS_MOTION`, or `om-asr-caption`) are invisible pipeline markers and MUST NOT fail brand compliance.

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


def _resolve_comp_summary_and_text(project_dir: Path, video_path: Path) -> tuple[Optional[Path], str, str]:
    comp_path = project_dir / (
        "hyperframes_reels/index.html" if "reels" in video_path.name else HYPERFRAMES_INDEX_HTML
    )
    if not comp_path.is_file():
        comp_path = project_dir / HYPERFRAMES_INDEX_HTML
    if not comp_path.is_file():
        return None, "", ""
    try:
        comp_text = comp_path.read_text(encoding="utf-8").strip()
        scene_ids = set(re.findall(r'\bdata-scene-id=["\']([^"\']+)["\']', comp_text))
        scene_count = len(scene_ids) or len(
            re.findall(r'<(?:div|section)\b[^>]*\bclass=["\'][^"\']*\bscene\b[^"\']*["\']', comp_text)
        )
        comp_summary = f"Composition File: {comp_path.name}, Detected Scenes: {scene_count}"
        return comp_path, comp_summary, comp_text
    except OSError:
        return comp_path, "Composition: error reading", ""


def _resolve_script_summary_and_text(project_dir: Path) -> tuple[str, str]:
    artifacts_dir = project_dir / "artifacts"
    for candidate_name in (SCRIPT_EN_US_JSON, "script_vi.json", "script.json"):
        script_path = artifacts_dir / candidate_name
        if script_path.is_file():
            break
    else:
        script_path = artifacts_dir / SCRIPT_EN_US_JSON

    if not script_path.is_file():
        return "Script: not found", ""

    try:
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
        sections = script_data.get("sections", [])
        script_summary = f"Script Sections: {len(sections)}"
        script_full_text = "\n".join(
            str(s.get("text") or s.get("text_vi") or s.get("narration") or "")
            for s in sections
        ).strip()
        return script_summary, script_full_text
    except Exception:
        return "Script: error reading", ""


def _resolve_auth_file_api_key(resolved_home: str) -> Optional[str]:
    auth_file = Path(resolved_home) / "auth.json"
    if not auth_file.is_file():
        return None
    try:
        auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
        api_key = auth_data.get("OPENAI_API_KEY")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
    except Exception:
        pass
    return None


def _setup_codex_env_and_cmd(agent_bin: str, env: dict[str, str]) -> list[str]:
    try:
        resolve_home_fn = _get_resolve_codex_home()
        resolved_home = resolve_home_fn(env)
        env["CODEX_HOME"] = resolved_home
    except RuntimeError as e:
        raise RuntimeError(f"Configured CODEX_HOME resolution failed: {e}")

    if not env.get("OPENAI_API_KEY"):
        api_key = _resolve_auth_file_api_key(resolved_home)
        if api_key:
            env["OPENAI_API_KEY"] = api_key

    codex_model = env.get("CODEX_MODEL", "model-medium-hight")
    return [
        agent_bin,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "--config",
        f'model="{codex_model}"',
        "-",
    ]


def _setup_non_codex_env_and_cmd(agent_bin: str, env: dict[str, str]) -> list[str]:
    for var in ("CODEXCODE", "CODEX_CODE_ENTRYPOINT", "CODEX_CODE_SSE_PORT", "CODEX_SESSION_ID", "ANTHROPIC_MODEL"):
        env.pop(var, None)
    return [agent_bin, "-p", "--output-format", "json", "-"]


def _setup_agent_env_and_cmd(agent_bin: str) -> tuple[list[str], dict[str, str]]:
    is_codex = "codex" in Path(agent_bin).name.lower()
    env = os.environ.copy()
    cmd = _setup_codex_env_and_cmd(agent_bin, env) if is_codex else _setup_non_codex_env_and_cmd(agent_bin, env)
    return cmd, env


def _build_review_category_results(
    response_data: dict,
    result_factory: Any,
    reviewer_name: str,
    is_transport: bool,
    artifact_hash: str,
    ts: str,
) -> list[Any]:
    results = []
    checks = {
        CHECK_NAME_VISUAL_QUALITY: "visual_quality",
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
                    "review_mode": "offline_transport" if is_transport else ("local_handoff_frames" if reviewer_name == "local-codex-handoff" else "codex_cli"),
                    "test_only_transport": is_transport,
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
                    "review_mode": "offline_transport" if is_transport else ("local_handoff_frames" if reviewer_name == "local-codex-handoff" else "codex_cli"),
                    "test_only_transport": is_transport,
                    "inspected_artifact_hash": artifact_hash,
                    "timestamp": ts,
                },
            )
        )
    return results


def _extract_review_frames(validator_self: Any, abs_video_path: Path, file_exists: bool, file_size: int) -> List[Path]:
    frame_dir = Path(tempfile.mkdtemp(prefix="openmontage-review-"))
    if file_exists and file_size > 0:
        try:
            return validator_self._extract_frames(abs_video_path, frame_dir)
        except Exception:
            pass
    return []


def _resolve_review_metadata_str(metadata_path: Path) -> str:
    abs_metadata_path = Path(metadata_path).resolve()
    if abs_metadata_path.is_file():
        try:
            return abs_metadata_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return "{}"


def _build_narration_assets_summary(project_dir: Path) -> str:
    narration_asset = project_dir / "assets" / "narration.mp3"
    narration_words_js = project_dir / "hyperframes" / "assets" / "narration_words.js"
    return (
        f"narration.mp3: {'present (' + str(narration_asset.stat().st_size) + ' bytes)' if narration_asset.is_file() else 'absent'}"
        + f"; narration_words.js: {'present' if narration_words_js.is_file() else 'absent'}"
    )


def _run_cli_and_parse_response(validator_self: Any, agent_bin: str, prompt: str, frame_paths: Optional[List[Path]] = None) -> dict:
    if os.environ.get("OPENMONTAGE_REQUIRE_LOCAL_AGENT") == "1" and validator_self._review_transport is None:
        from lib.local_agent_handoff import request_local_agent

        root = Path(__file__).resolve().parent.parent
        handoff_root = Path(os.environ.get("OPENMONTAGE_AGENT_HANDOFF_DIR") or root / "data" / "local_agent_handoff")
        frames = []
        for frame in frame_paths or []:
            frame = Path(frame)
            if frame.is_symlink() or not frame.is_file() or frame.stat().st_size > 4_000_000:
                raise ValueError("invalid sampled review frame")
            data = frame.read_bytes()
            frames.append({"server_path": str(frame), "sha256": hashlib.sha256(data).hexdigest(),
                           "content_base64": base64.b64encode(data).decode("ascii")})
        if not frames:
            raise ValueError("local quality review requires sampled frames")
        prompt += ("\n\nThe video file is on the server and is not available to the local reviewer. "
                   "Inspect the attached sampled frames and supplied probe metadata only; do not claim "
                   "to have viewed or heard the full video, and fail any criterion lacking evidence.")
        return request_local_agent(handoff_root, "quality_review", {"prompt": prompt, "frames": frames},
                                   timeout_seconds=float(os.environ.get("OPENMONTAGE_AGENT_HANDOFF_TIMEOUT", "1800")))
    cmd, env = _setup_agent_env_and_cmd(agent_bin)
    timeout = int(os.environ.get("AGENT_REVIEW_TIMEOUT_SECONDS", "120"))
    root_dir = str(Path(__file__).resolve().parent.parent)

    run_fn = validator_self._review_transport or _get_subprocess_run()
    proc = run_fn(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=root_dir, env=env)

    output = proc.stdout or ""
    if "hit your limit" in output.lower() or proc.returncode != 0:
        raise RuntimeError(f"CLI returned error or rate limit: {output[:200]}")

    parse_fn = _get_parse_codex_review()
    response_data = parse_fn(output)
    if not isinstance(response_data, dict):
        raise ValueError(f"Agent CLI review returned non-dictionary JSON: {output[:200]}")
    return response_data


def execute_cli_review_helper(
    validator_self: Any,
    agent_bin: str,
    video_path: Path,
    metadata_path: Path,
    result_factory: Any,
    **_kwargs: Any,
) -> List[Any]:
    """Execute review via CLI binary and parse result."""
    abs_video_path = Path(video_path).resolve()
    file_exists = abs_video_path.is_file()
    file_size = abs_video_path.stat().st_size if file_exists else 0
    hash_before_review = compute_sha256(abs_video_path) if file_exists and file_size > 0 else None

    comp_path, comp_summary, comp_text = _resolve_comp_summary_and_text(validator_self.project_dir, video_path)
    if comp_path is None:
        return [result_factory(
            check_name=CHECK_NAME_VISUAL_QUALITY,
            passed=False,
            message=f"{CHECK_NAME_VISUAL_QUALITY}: ✗ FAIL (Score: 0) - Missing HyperFrames HTML source",
            details={"error": "Missing HyperFrames HTML source"},
        )]

    frame_paths = _extract_review_frames(validator_self, abs_video_path, file_exists, file_size)
    if not frame_paths:
        return [result_factory(
            check_name=CHECK_NAME_VISUAL_QUALITY,
            passed=False,
            message=f"{CHECK_NAME_VISUAL_QUALITY}: ✗ FAIL (Score: 0) - Frame extraction failed: representative frames could not be extracted",
            details={"error": "Frame extraction failed"},
        )]

    script_summary, script_full_text = _resolve_script_summary_and_text(validator_self.project_dir)
    audio_stream_summary = _get_probe_audio_streams()(abs_video_path)
    narration_assets_summary = _build_narration_assets_summary(validator_self.project_dir)
    metadata_str = _resolve_review_metadata_str(metadata_path)

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

    response_data = _run_cli_and_parse_response(validator_self, agent_bin, prompt, frame_paths=frame_paths)
    artifact_hash = compute_sha256(abs_video_path)
    if not hash_before_review or artifact_hash != hash_before_review:
        raise ValueError("video changed during agent review")
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    reviewer_name = "offline_test_transport" if validator_self._review_transport else Path(agent_bin).name

    return _build_review_category_results(
        response_data=response_data,
        result_factory=result_factory,
        reviewer_name=reviewer_name,
        is_transport=bool(validator_self._review_transport),
        artifact_hash=artifact_hash,
        ts=ts,
    )


def _check_mock_review_policy(
    validator_self: Any,
    result_factory: Any,
    artifact_hash: str,
    ts: str,
) -> Optional[List[Any]]:
    is_mock_env = os.environ.get("CODEX_AGENT_VALIDATION_MOCK") == "1" or os.environ.get("CLAUDE_AGENT_VALIDATION_MOCK") == "1"
    is_production = os.environ.get("PRODUCTION_RELEASE") == "1" or os.environ.get("STRICT_PRODUCTION") == "1"

    if not (is_mock_env or validator_self._review_transport is not None):
        return None

    if is_production:
        injected = validator_self._review_transport is not None
        return [
            result_factory(
                check_name=CHECK_NAME_CODEX_GATE,
                passed=False,
                message=(
                    "Offline test review transport strictly forbidden in production mode"
                    if injected
                    else "Mock review strictly forbidden in production mode"
                ),
                details={
                    "error": "test_transport_forbidden_in_production" if injected else "mock_forbidden_in_production",
                    "review_mode": "offline_transport" if injected else "mock",
                    "test_only_transport": injected,
                    "timestamp": ts,
                    "inspected_artifact_hash": artifact_hash,
                },
            )
        ]
    if is_mock_env:
        return [
            result_factory(check_name=CHECK_NAME_VISUAL_QUALITY, passed=True, message=f"{CHECK_NAME_VISUAL_QUALITY}: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
            result_factory(check_name="Audio Sync", passed=True, message="Audio Sync: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
            result_factory(check_name="Content Appropriateness", passed=True, message="Content Appropriateness: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
            result_factory(check_name="Brand Compliance", passed=True, message="Brand Compliance: ✓ PASS (Mocked)", details={"score": 100, "review_mode": "mock", "timestamp": ts, "inspected_artifact_hash": artifact_hash}),
        ]
    return None


def _check_strict_pre_frames(
    validator_self: Any,
    video_path: Path,
    abs_video_path: Path,
    result_factory: Any,
) -> Optional[List[Any]]:
    comp_path = validator_self.project_dir / (
        "hyperframes_reels/index.html"
        if "reels" in Path(video_path).name
        else HYPERFRAMES_INDEX_HTML
    )
    if not comp_path.is_file():
        comp_path = validator_self.project_dir / HYPERFRAMES_INDEX_HTML
    if not comp_path.is_file():
        return [
            result_factory(
                check_name=CHECK_NAME_VISUAL_QUALITY,
                passed=False,
                message=f"{CHECK_NAME_VISUAL_QUALITY}: ✗ FAIL (Score: 0) - Missing HyperFrames HTML source",
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
                check_name=CHECK_NAME_VISUAL_QUALITY,
                passed=False,
                message=f"{CHECK_NAME_VISUAL_QUALITY}: ✗ FAIL (Score: 0) - Frame extraction failed: representative frames could not be extracted",
                details={"error": "Frame extraction failed"},
            )
        ]
    return None


def _check_claude_module_lambda(result_factory: Any, ts: str, artifact_hash: str) -> Optional[List[Any]]:
    claude_mod = sys.modules.get("scripts.claude_agent_validation")
    if claude_mod and hasattr(claude_mod, "resolve_claude_cli"):
        claude_fn = getattr(claude_mod, "resolve_claude_cli")
        if getattr(claude_fn, "__name__", "") == "<lambda>" and not claude_fn():
            return [
                result_factory(
                    check_name="CLAUDE Agent Review Gate",
                    passed=False,
                    message="CLAUDE Agent strict review unavailable: FileNotFoundError: claude CLI not found",
                    details={"error": "claude CLI not found", "review_mode": "failed", "timestamp": ts, "inspected_artifact_hash": artifact_hash},
                )
            ]
    return None


def _run_cli_review_with_retries(
    validator_self: Any,
    agent_bin: str,
    video_path: Path,
    metadata_path: Path,
    prior_results: Optional[List[Any]],
) -> tuple[Optional[List[Any]], Optional[Exception]]:
    attempts = max(1, getattr(validator_self, "retry_count", 1))
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return validator_self._execute_cli_review(agent_bin, video_path, metadata_path, prior_results), None
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                logger.warning("Agent CLI review attempt %d/%d failed: %s; retrying...", attempt, attempts, exc)
                time.sleep(0.5)
    return None, last_exc


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

    mock_res = _check_mock_review_policy(validator_self, result_factory, artifact_hash, ts)
    if mock_res is not None:
        return mock_res

    if validator_self.strict_mode:
        pre_err = _check_strict_pre_frames(validator_self, video_path, abs_video_path, result_factory)
        if pre_err is not None:
            return pre_err

    if validator_self._review_transport is not None:
        try:
            return validator_self._execute_cli_review(
                "offline_test_transport",
                video_path,
                metadata_path,
                prior_results,
            )
        except Exception as exc:
            logger.exception("Injected strict review transport failed: %s", exc)
            return [
                result_factory(
                    check_name=CHECK_NAME_CODEX_GATE,
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

    claude_res = _check_claude_module_lambda(result_factory, ts, artifact_hash)
    if claude_res is not None:
        return claude_res

    agent_bin = "local-codex-handoff" if os.environ.get("OPENMONTAGE_REQUIRE_LOCAL_AGENT") == "1" else _get_resolve_agent_cli()()
    if not agent_bin:
        if validator_self.strict_mode:
            return [
                result_factory(
                    check_name=CHECK_NAME_CODEX_GATE,
                    passed=False,
                    message="Codex agent review unavailable: Agent CLI binary not found",
                    details={"error": "agent_cli_not_found", "review_mode": "failed", "timestamp": ts, "inspected_artifact_hash": artifact_hash},
                )
            ]
        logger.info("Agent CLI not found; falling back to non-strict autonomous heuristic review")
        return validator_self._autonomous_quality_review(abs_video_path, Path(metadata_path).resolve(), prior_results)

    results, exc = _run_cli_review_with_retries(validator_self, agent_bin, video_path, metadata_path, prior_results)
    if results is not None:
        return results

    if validator_self.strict_mode:
        logger.error("Strict Codex Agent review failed after retry attempts: %s", exc)
        return [
            result_factory(
                check_name=CHECK_NAME_CODEX_GATE,
                passed=False,
                message=f"Strict Codex agent review failed: {exc}",
                details={"error": str(exc), "review_mode": "failed", "timestamp": ts, "inspected_artifact_hash": artifact_hash},
            )
        ]
    logger.info("Agent CLI review skipped (%s); applying autonomous heuristic review in non-strict mode", exc)
    return validator_self._autonomous_quality_review(abs_video_path, Path(metadata_path).resolve(), prior_results)
