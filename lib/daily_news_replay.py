"""Bounded, offline replay of the public daily-news selector and reviewer.

This does not run the daily shell or claim a complete pipeline rehearsal. Every
agent response is read from an explicit local fixture transport bundle; media
validation and frame extraction remain the production implementations.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from lib.codex_news_selector import CodexNewsSelector
from scripts.codex_agent_validation import CodexAgentValidator
from scripts.rehearse_daily_news_offline import _safe_stage_path, _sha256, validate_feed

MANIFEST_VERSION = 1
MAX_PROJECTS = 3
MAX_BUNDLE_FILES = 500
MAX_BUNDLE_ENTRIES = 1_000
MAX_BUNDLE_BYTES = 2_000_000_000
TEST_ONLY_MARKER = "OFFLINE_REHEARSAL_TEST_ONLY.json"
_SECRET_FILE_NAMES = {
    "credentials", "credentials.json", "secrets", "secrets.json", "auth.json",
    "token", "token.json", "id_rsa", "id_ed25519", "identity", ".netrc",
    ".npmrc", ".pypirc", "service-account.json", "service_account.json",
}
_SECRET_DIR_NAMES = {
    ".aws", ".azure", ".config", ".docker", ".gnupg", ".kube", ".ssh",
    ".codex", ".claude", ".npm", ".pki", ".env", ".git", ".venv",
    ".cache", "node_modules", "__pycache__", "venv", "config", "configs",
    "credentials", "secrets", "tokens",
}


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _manifest_path(base: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty manifest-relative path")
    relative = Path(raw)
    if (relative.is_absolute() or PureWindowsPath(raw).is_absolute()
            or PureWindowsPath(raw).drive or any(part == ".." for part in relative.parts)):
        raise ValueError(f"{label} must be a relative path without parent traversal")
    candidate = base / relative
    if _has_symlink_component(candidate):
        raise ValueError(f"{label} path must not traverse symlinks")
    resolved = candidate.resolve(strict=True)
    if base not in resolved.parents:
        raise ValueError(f"{label} must remain inside the manifest directory")
    return resolved


def _project_file(project_root: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty project-relative path")
    relative = Path(raw)
    if (relative.is_absolute() or PureWindowsPath(raw).is_absolute()
            or PureWindowsPath(raw).drive or any(part == ".." for part in relative.parts)):
        raise ValueError(f"{label} must be a relative path without parent traversal")
    candidate = project_root / relative
    if _has_symlink_component(candidate):
        raise ValueError(f"{label} must not traverse symlinks")
    resolved = candidate.resolve(strict=True)
    if project_root not in resolved.parents or not resolved.is_file():
        raise ValueError(f"{label} must be a file inside the staged project bundle")
    return resolved


def _load_json(path: Path, label: str) -> Any:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        if path.stat().st_size > 10_000_000:
            raise ValueError(f"{label} exceeds the 10 MB JSON limit")
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc


def _copy_project_bundle(
    source: Path,
    destination: Path | None,
    *,
    allow_existing_destination: bool = False,
) -> dict[str, str]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("project bundle must be a non-symlink directory")

    entries: list[tuple[Path, Path, bool, int]] = []
    stack = [(source, Path())]
    total_bytes = 0
    file_count = 0
    while stack:
        directory, relative_dir = stack.pop()
        with os.scandir(directory) as iterator:
            for item in iterator:
                relative = relative_dir / item.name
                if len(entries) >= MAX_BUNDLE_ENTRIES:
                    raise ValueError("project bundle exceeds entry-count limit")
                if item.is_symlink():
                    raise ValueError("project bundle contains a symlink")
                if item.is_dir(follow_symlinks=False):
                    if item.name.lower() in _SECRET_DIR_NAMES or item.name.lower().startswith(".env"):
                        raise ValueError(f"project bundle contains a forbidden credential/config directory: {relative}")
                    entries.append((Path(item.path), relative, True, 0))
                    stack.append((Path(item.path), relative))
                elif item.is_file(follow_symlinks=False):
                    lowered_name = item.name.lower()
                    if (lowered_name in _SECRET_FILE_NAMES or lowered_name.startswith((
                            ".env", "credentials", "auth", "secret", "api_key", "api-key", "apikey",
                            "private_key", "private-key", "password", "passwd", "access_key", "access-key"))
                            or any(token in lowered_name for token in (
                                "secret", "credential", "private_key", "private-key", "password", "passwd",
                                "access_key", "access-key", "api-key", "token"))
                            or lowered_name.endswith((".pem", ".p12", ".pfx", ".key"))):
                        raise ValueError(f"project bundle contains a forbidden credential file: {relative}")
                    size = item.stat(follow_symlinks=False).st_size
                    total_bytes += size
                    if total_bytes > MAX_BUNDLE_BYTES:
                        raise ValueError("project bundle exceeds byte limit")
                    file_count += 1
                    if file_count > MAX_BUNDLE_FILES:
                        raise ValueError("project bundle exceeds file-count limit")
                    entries.append((Path(item.path), relative, False, size))
                else:
                    raise ValueError(f"project bundle contains a non-regular entry: {relative}")

    if destination is None:
        return {}

    if allow_existing_destination:
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("pre-marked copy destination must be a non-symlink directory")
        marker = destination / TEST_ONLY_MARKER
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("pre-marked copy destination lacks its release-blocking marker")
        if set(destination.iterdir()) != {marker}:
            raise ValueError("pre-marked copy destination must contain only its release-blocking marker")
        try:
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("pre-marked copy destination has an invalid release-blocking marker") from exc
        if marker_data != {"test_only": True, "purpose": "daily-news-rehearsal"}:
            raise ValueError("pre-marked copy destination has an invalid release-blocking marker")
        if any(relative == Path(TEST_ONLY_MARKER) for _, relative, _, _ in entries):
            raise ValueError("project bundle may not replace the release-blocking marker")
    else:
        destination.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for source_path, relative, is_dir, expected_size in sorted(entries, key=lambda item: (len(item[1].parts), item[1].as_posix())):
        target = destination / relative
        if is_dir:
            target.mkdir(exist_ok=True)
            continue
        current = source_path.lstat()
        if not stat.S_ISREG(current.st_mode) or current.st_size != expected_size:
            raise ValueError(f"project bundle changed while staging: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        hashes[relative.as_posix()] = _sha256(target)
    return hashes


def _completed_transport(reply: Any, label: str):
    """Return an inert transport that cannot launch subprocesses or go online."""
    payload = json.dumps(reply, ensure_ascii=False)

    def transport(command, **kwargs):
        if kwargs.get("timeout", 0) <= 0 or kwargs.get("capture_output") is not True:
            raise RuntimeError(f"{label} transport received unexpected subprocess contract")
        if kwargs.get("stdin") is not subprocess.DEVNULL and "stdin" in kwargs:
            raise RuntimeError(f"{label} transport must not receive interactive stdin")
        return subprocess.CompletedProcess(args=["fixture:" + label], returncode=0, stdout=payload, stderr="")

    return transport


def _result_dict(result: Any) -> dict[str, Any]:
    return {
        "check_name": result.check_name,
        "passed": bool(result.passed),
        "message": result.message,
        "details": result.details,
    }


def execute_replay(manifest_path: Path, stage_dir: str, max_source_age_hours: float) -> dict[str, Any]:
    """Run selector and strict reviewer over a frozen, copied fixture bundle."""
    if os.environ.get("PRODUCTION_RELEASE") == "1" or os.environ.get("STRICT_PRODUCTION") == "1":
        raise ValueError("offline fixture replay is forbidden in production mode")
    if os.environ.get("CODEX_AGENT_VALIDATION_MOCK") == "1" or os.environ.get("CLAUDE_AGENT_VALIDATION_MOCK") == "1":
        raise ValueError("global mock review mode is forbidden; use the explicit fixture transport")
    manifest_file = _regular_file(manifest_path, "manifest")
    base = manifest_file.parent
    manifest = _load_json(manifest_file, "replay manifest")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_VERSION:
        raise ValueError(f"manifest schema_version must be {MANIFEST_VERSION}")
    allowed_manifest_keys = {"schema_version", "fixture_bundle", "feed", "selection_reply", "review_reply", "projects"}
    if set(manifest) != allowed_manifest_keys:
        raise ValueError(f"manifest keys must be exactly {sorted(allowed_manifest_keys)}")
    if manifest.get("fixture_bundle") is not True:
        raise ValueError("manifest must explicitly set fixture_bundle to true")
    feed = _manifest_path(base, manifest.get("feed"), "feed")
    selection_reply_path = _manifest_path(base, manifest.get("selection_reply"), "selection_reply")
    review_reply_path = _manifest_path(base, manifest.get("review_reply"), "review_reply")
    feed_info = validate_feed(feed, max_source_age_hours)
    candidates = _load_json(feed, "frozen feed")
    if not isinstance(candidates, list):
        raise ValueError("frozen feed must be a JSON array")
    selection_reply = _load_json(selection_reply_path, "selector fixture reply")
    review_reply = _load_json(review_reply_path, "reviewer fixture reply")
    projects = manifest.get("projects")
    if not isinstance(projects, list) or not 1 <= len(projects) <= MAX_PROJECTS:
        raise ValueError(f"manifest projects must contain between one and {MAX_PROJECTS} entries")

    destination = _safe_stage_path(stage_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "mode": "offline_public_component_replay",
        "test_only": True,
        "publication_enabled": False,
        "cost_usd": 0,
        "n5_complete": False,
        "shell_executed": False,
        "execution_policy": {
            "egress_isolation": "not_enforced_by_harness",
            "supervisor_wall_clock_timeout_required": True,
            "supervisor_process_group_termination_required": True,
        },
        "staging_directory": str(destination),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "harness_sha256": _sha256(Path(__file__).resolve()),
        "manifest_sha256": _sha256(manifest_file),
        "frozen_feed": feed_info,
        "stage_outcomes": [],
        "staged_files": {},
        "blockers": [
            "The daily shell was not executed: its director/provider boundaries are not comprehensively injected.",
            "Fixture selector/reviewer replies are deterministic test inputs, not evidence of factual verification or human approval.",
            "This component replay does not establish end-to-end rendering, subtitles, publish-state mutation, recovery, or scheduled-run acceptance.",
            "The supervisor must enforce a wall-clock timeout, process-group termination, and outbound egress denial; the harness does not enforce them.",
        ],
    }
    active_stage = "staging_fixture_bundle"
    try:
        inputs_dir = destination / "inputs"
        inputs_dir.mkdir()
        staged_feed = inputs_dir / "newsnow_feed.json"
        shutil.copyfile(feed, staged_feed)
        report["staged_files"]["inputs/newsnow_feed.json"] = _sha256(staged_feed)
        staged_shell = destination / "scripts" / "run_daily_news_pipeline.sh"
        staged_shell.parent.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts" / "run_daily_news_pipeline.sh", staged_shell)
        os.chmod(staged_shell, 0o700)
        report["staged_files"]["scripts/run_daily_news_pipeline.sh"] = _sha256(staged_shell)
        staged_selection_reply = inputs_dir / "selection_reply.json"
        staged_review_reply = inputs_dir / "review_reply.json"
        shutil.copyfile(selection_reply_path, staged_selection_reply)
        shutil.copyfile(review_reply_path, staged_review_reply)
        report["staged_files"]["inputs/selection_reply.json"] = _sha256(staged_selection_reply)
        report["staged_files"]["inputs/review_reply.json"] = _sha256(staged_review_reply)

        report["stage_outcomes"].append({"stage": "frozen_feed", "status": "passed", "item_count": len(candidates)})
        active_stage = "public_selector"
        candidate_ids = {item.get("id") or item.get("candidate_id") for item in candidates if isinstance(item, dict)}
        supplied_selection_id = selection_reply.get("selected_candidate_id") if isinstance(selection_reply, dict) else None
        if supplied_selection_id not in candidate_ids:
            raise ValueError("selector fixture selected_candidate_id is not present in the frozen feed")
        selection = CodexNewsSelector(transport=_completed_transport(selection_reply, "selector")).select_and_research(candidates)
        if not isinstance(selection, dict):
            raise ValueError("public selector rejected fixture response")
        if selection.get("selected_candidate_id") not in candidate_ids or selection.get("selected_candidate_id") != supplied_selection_id:
            raise ValueError("public selector returned an ID outside the frozen-feed fixture selection")
        research_status = selection.get("research_status")
        if isinstance(research_status, str) and research_status.strip().casefold() == "incomplete":
            raise ValueError("public selector returned incomplete research; refusing fallback success")
        report["selection"] = {
            "selected_candidate_id": selection.get("selected_candidate_id"),
            "research_status": selection.get("research_status", "fixture_response"),
            "response_sha256": hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest(),
        }
        report["stage_outcomes"].append({"stage": "public_selector", "status": "passed", "transport": "fixture"})
        active_stage = "project_bundle_validation"

        for index, entry in enumerate(projects):
            if not isinstance(entry, dict):
                raise ValueError(f"projects[{index}] must be an object")
            if set(entry) != {"id", "bundle", "video", "metadata"}:
                raise ValueError(f"projects[{index}] keys must be exactly id, bundle, video, metadata")
            project_id = entry.get("id")
            if not isinstance(project_id, str) or not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in project_id):
                raise ValueError(f"projects[{index}].id must be a safe identifier")
            source_dir = _manifest_path(base, entry.get("bundle"), f"projects[{index}].bundle")
            project_dir = destination / "projects" / project_id
            project_dir.parent.mkdir(parents=True, exist_ok=True)
            hashes = _copy_project_bundle(source_dir, project_dir)
            marker_path = project_dir / TEST_ONLY_MARKER
            marker_path.write_text(json.dumps({
                "test_only": True,
                "artifact_kind": "offline_rehearsal_fixture",
                "manifest_sha256": report["manifest_sha256"],
                "source_bundle_sha256": hashlib.sha256("".join(sorted(hashes.values())).encode()).hexdigest(),
            }, indent=2) + "\n", encoding="utf-8")
            os.chmod(marker_path, 0o400)
            hashes[TEST_ONLY_MARKER] = _sha256(marker_path)
            report["staged_files"].update({f"projects/{project_id}/{name}": digest for name, digest in hashes.items()})
            video_path = _project_file(project_dir, entry.get("video"), f"projects[{index}].video")
            metadata_path = _project_file(project_dir, entry.get("metadata"), f"projects[{index}].metadata")
            video_hash = _sha256(video_path)
            validator = CodexAgentValidator(project_dir, strict_mode=True, retry_count=0,
                                            review_transport=_completed_transport(review_reply, "reviewer"))
            active_stage = f"technical_validation:{project_id}"
            technical = [_result_dict(item) for item in validator.validate_technical_contract(video_path)]
            technical_passed = bool(technical) and all(item["passed"] for item in technical)
            report["stage_outcomes"].append({
                "stage": f"technical_validation:{project_id}",
                "status": "passed" if technical_passed else "failed",
                "video_sha256": video_hash,
                "checks": technical,
            })
            active_stage = f"public_strict_review:{project_id}"
            strict = [_result_dict(item) for item in validator.codex_agent_strict_review(video_path, metadata_path)]
            strict_passed = bool(strict) and all(item["passed"] for item in strict)
            report["stage_outcomes"].append({
                "stage": f"public_strict_review:{project_id}",
                "status": "passed" if strict_passed else "failed",
                "transport": "fixture",
                "video_sha256": video_hash,
                "checks": strict,
            })
            active_stage = "project_bundle_validation"
        passed = all(item["status"] == "passed" for item in report["stage_outcomes"])
        report["status"] = "component_replay_passed" if passed else "component_replay_failed"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(destination, report)
        return report
    except Exception as exc:
        report["status"] = "component_replay_failed"
        error = f"{type(exc).__name__}: {exc}"
        if not any(item["stage"] == active_stage for item in report["stage_outcomes"]):
            report["stage_outcomes"].append({"stage": active_stage, "status": "failed", "error": error})
        report["error"] = error
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(destination, report)
        raise


def _write_report(destination: Path, report: dict[str, Any]) -> None:
    path = destination / "rehearsal-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
