"""Strict bounded verification for the daily-news rehearsal contract."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SUITE = (
    "tests/test_daily_news_rehearsal_execution.py",
    "tests/contracts/test_daily_news_offline_rehearsal.py",
    "tests/test_daily_news_transport_injection.py",
    "tests/contracts/test_daily_news_failure_preservation.py",
    "tests/contracts/test_news_evidence_gate.py",
    "tests/contracts/test_news_release_gate.py",
    "tests/contracts/test_news_caption_installation.py",
    "tests/contracts/test_news_caption_timing.py",
    "tests/contracts/test_daily_news_caption_integration.py",
    "tests/tools/test_strict_publish_preflight.py",
    "tests/test_daily_news_rehearsal.py",
    "tests/test_publish_manual_video.py",
    "tests/test_schedule_today_native.py",
    "tests/test_strict_cron_retry.py",
    "tests/contracts/test_daily_news_acceptance_loop.py",
)
SOURCE_DIRS = ("lib", "scripts", "tools", "tests", "config", "schemas", "pipeline_defs",
               "docs", "skills", ".agents", "remotion-composer", "templates", "styles")
SOURCE_SUFFIXES = {".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
                   ".md", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".mjs", ".cjs",
                   ".txt", ".lock", ".xml"}
ROOT_SOURCE_FILES = ("pyproject.toml", "setup.py", "setup.cfg", "tox.ini", ".python-version",
                     "requirements.txt", "requirements-dev.txt", "requirements-gpu.txt",
                     "requirements-publish.txt", "package.json", "package-lock.json",
                     "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock", "Dockerfile",
                     "docker-compose.yml", "Makefile")
MARKER_NAME = ".openmontage-rehearsal-root.json"
MARKER_VALUE = {"test_only": True, "purpose": "daily-news-rehearsal"}
REPORT_REL = Path("logs/daily_news_rehearsal_report.json")
MAX_SOURCE_FILES = 30000
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_EVIDENCE_FILE_BYTES = 128 * 1024 * 1024
MAX_EVIDENCE_FILES_PER_PROJECT = 256
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_MARKER_BYTES = 16 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
TRANSIENT_OUTCOMES = {"runner_interrupted", "timeout"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"refusing symlink output path: {path}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_snapshot(path: Path, limit: int) -> tuple[bytes, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(f"input must be a bounded regular file: {path}")
        blocks = []
        remaining = limit + 1
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                break
            blocks.append(block)
            remaining -= len(block)
        content = b"".join(blocks)
        if len(content) > limit:
            raise ValueError(f"input exceeds byte limit: {path}")
        return content, hashlib.sha256(content).hexdigest()
    finally:
        os.close(fd)


def _has_symlink_component(path: Path) -> bool:
    absolute = path.expanduser().absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _contained_regular_file(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts:
        raise ValueError("evidence path must be a nonempty safe relative path")
    candidate = root / rel
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("evidence path traverses a symlink")
    resolved = candidate.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError("evidence must be a regular file inside its isolated root")
    if resolved.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
        raise ValueError("evidence file exceeds the configured size bound")
    return resolved


def source_fingerprint(root: Path, inputs: list[Path]) -> dict[str, str]:
    files: set[Path] = set()
    total_bytes = 0
    root_candidates = {root / name for name in ROOT_SOURCE_FILES}
    root_candidates.update(path for path in root.iterdir()
                           if path.is_file() and (path.name.startswith("requirements-")
                           or path.name.startswith("package-lock")))
    for candidate in root_candidates:
        if candidate.is_file() and not candidate.is_symlink():
            files.add(candidate)
            total_bytes += candidate.stat().st_size
    for dirname in SOURCE_DIRS:
        base = root / dirname
        if not base.is_dir():
            raise ValueError(f"required source directory missing: {dirname}")
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part in {"__pycache__", ".pytest_cache", "node_modules", ".git"} for part in path.parts):
                continue
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            files.add(path)
            total_bytes += path.stat().st_size
            if len(files) > MAX_SOURCE_FILES or total_bytes > MAX_SOURCE_BYTES:
                raise ValueError("source fingerprint exceeds configured safety bounds")
    files.update(inputs)
    if len(files) > MAX_SOURCE_FILES:
        raise ValueError("source and evidence fingerprint exceeds configured file-count bound")
    fingerprint_bytes = 0
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"fingerprint input is missing or symlinked: {path}")
        fingerprint_bytes += path.stat().st_size
        if fingerprint_bytes > MAX_SOURCE_BYTES:
            raise ValueError("source and evidence fingerprint exceeds configured byte bound")
    result = {}
    for path in sorted(files):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"fingerprint input is missing or symlinked: {path}")
        result[str(path.resolve())] = sha256(path)
    return result


def _hashes_from_records(records: list[dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for record in records:
        for path, digest in record.get("validated_hashes", {}).items():
            if path in hashes and hashes[path] != digest:
                raise ValueError(f"conflicting evidence snapshots for {path}")
            hashes[path] = digest
    return hashes


def verify_rehearsals(manifests: list[Path]) -> tuple[bool, list[dict[str, Any]], list[Path]]:
    """Validate reports and hash exactly the bytes parsed/read from bounded inputs."""
    records: list[dict[str, Any]] = []
    all_paths: list[Path] = []
    roots: set[Path] = set()
    ids_by_run: list[frozenset[str]] = []
    run_signatures: set[str] = set()
    valid = len(manifests) == 3
    for manifest in manifests:
        snapshot_hashes: dict[str, str] = {}
        run_paths: list[Path] = []
        try:
            if _has_symlink_component(manifest):
                raise ValueError("manifest path must not traverse symlinks")
            mpath = manifest.resolve(strict=True)
            manifest_bytes, manifest_hash = _read_snapshot(mpath, MAX_MANIFEST_BYTES)
            snapshot_hashes[str(mpath)] = manifest_hash
            run_paths.append(mpath)
            data = json.loads(manifest_bytes)
            raw_root = Path(data["isolated_root"])
            raw_report = Path(data["report"])
            if _has_symlink_component(raw_root) or _has_symlink_component(raw_report):
                raise ValueError("isolated root and report paths must not traverse symlinks")
            root = raw_root.resolve(strict=True)
            report = raw_report.resolve(strict=True)
            if not root.is_dir() or root in roots:
                raise ValueError("missing or repeated isolated root")
            roots.add(root)
            if (root / ".git").exists():
                raise ValueError("rehearsal root must not be a git checkout")
            if report != (root / REPORT_REL).resolve(strict=True):
                raise ValueError("report must be the canonical report inside its isolated root")
            marker_path = root / MARKER_NAME
            marker_bytes, marker_hash = _read_snapshot(marker_path, MAX_MARKER_BYTES)
            snapshot_hashes[str(marker_path)] = marker_hash
            run_paths.append(marker_path)
            if json.loads(marker_bytes) != MARKER_VALUE:
                raise ValueError("isolated root marker contents are invalid")
            report_bytes, report_hash = _read_snapshot(report, MAX_REPORT_BYTES)
            snapshot_hashes[str(report)] = report_hash
            run_paths.append(report)
            payload = json.loads(report_bytes)
            requested = payload.get("requested_project_ids")
            successful = payload.get("successful_project_ids")
            failed = payload.get("failed_project_ids")
            quarantined = payload.get("quarantined_project_ids")
            if (payload.get("test_only") is not True or payload.get("shell_executed") is not True
                    or payload.get("publication_enabled") is not False):
                raise ValueError("report does not establish test-only actual shell with publication disabled")
            if payload.get("terminal_exit_status") != 0 or payload.get("terminal_stage") != "completed":
                raise ValueError("daily entrypoint did not complete successfully")
            if (not isinstance(requested, list) or len(requested) != 3
                    or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", item)
                           for item in requested)
                    or len(set(requested)) != 3):
                raise ValueError("report must contain exactly three unique safe project IDs")
            if successful != requested or failed != [] or quarantined != []:
                raise ValueError("all three requested projects must succeed with no failed/quarantined IDs")
            if payload.get("n5_complete") is not False:
                raise ValueError("report must not claim N5/release completion")
            evidence = payload.get("stage_evidence_paths")
            if not isinstance(evidence, dict) or set(evidence) != set(requested):
                raise ValueError("stage evidence must be present per requested project")
            hashed_evidence: dict[str, list[dict[str, str]]] = {}
            for project_id in requested:
                rels = evidence[project_id]
                if not isinstance(rels, list) or not rels or len(rels) > MAX_EVIDENCE_FILES_PER_PROJECT:
                    raise ValueError("empty or over-limit per-project stage evidence")
                resolved_entries = []
                for rel in rels:
                    if not isinstance(rel, str):
                        raise TypeError("stage evidence path must be a string")
                    item = _contained_regular_file(root, rel)
                    _content, digest = _read_snapshot(item, MAX_EVIDENCE_FILE_BYTES)
                    snapshot_hashes[str(item)] = digest
                    run_paths.append(item)
                    resolved_entries.append({"path": rel, "sha256": digest})
                hashed_evidence[project_id] = resolved_entries
            failure_rel = data.get("failure_evidence")
            recovery_rel = data.get("recovery_evidence")
            if not isinstance(failure_rel, str) or not isinstance(recovery_rel, str) or failure_rel == recovery_rel:
                raise ValueError("manifest must identify distinct failure and recovery evidence files")
            failure_path = _contained_regular_file(root, failure_rel)
            recovery_path = _contained_regular_file(root, recovery_rel)
            _failure_bytes, failure_hash = _read_snapshot(failure_path, MAX_EVIDENCE_FILE_BYTES)
            _recovery_bytes, recovery_hash = _read_snapshot(recovery_path, MAX_EVIDENCE_FILE_BYTES)
            snapshot_hashes[str(failure_path)] = failure_hash
            snapshot_hashes[str(recovery_path)] = recovery_hash
            run_paths.extend((failure_path, recovery_path))
            ids = tuple(requested)
            ids_by_run.append(frozenset(requested))
            signature = hashlib.sha256(json.dumps({"report": report_hash,
                "stage_evidence": hashed_evidence, "failure": failure_hash, "recovery": recovery_hash},
                sort_keys=True).encode("utf-8")).hexdigest()
            run_signatures.add(signature)
            records.append({"isolated_root": str(root), "manifest": str(mpath),
                            "report": str(report), "report_sha256": report_hash,
                            "requested_project_ids": ids, "run_evidence_signature": signature,
                            "failure_evidence": {"path": failure_rel, "sha256": failure_hash},
                            "recovery_evidence": {"path": recovery_rel, "sha256": recovery_hash},
                            "stage_evidence": hashed_evidence,
                            "validated_hashes": snapshot_hashes})
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            valid = False
            records.append({"manifest": str(manifest), "error": str(exc),
                            "validated_hashes": snapshot_hashes})
        all_paths.extend(run_paths)
    valid = valid and len(roots) == 3 and len(ids_by_run) == 3 and len(set(ids_by_run)) == 3 and len(run_signatures) == 3
    return valid, records, list(dict.fromkeys(all_paths))


def _raise_keyboard_interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def execute(argv: list[str], cwd: Path, log: Path, timeout: float, junit: Path) -> dict[str, Any]:
    started = time.time()
    if log.exists() or log.is_symlink() or junit.exists() or junit.is_symlink():
        raise ValueError("attempt log/JUnit outputs must be new, nonsymlink paths")
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    with log.open("xb") as output:
        previous_term = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                    start_new_session=True, close_fds=True)
            try:
                code = proc.wait(timeout=timeout)
                outcome = "completed"
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                code, outcome = 124, "timeout"
            except BaseException:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise
        finally:
            signal.signal(signal.SIGTERM, previous_term)
    summary: dict[str, int] = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if junit.is_file():
        try:
            tree = ET.parse(junit)
            suites = [tree.getroot()] if tree.getroot().tag == "testsuite" else list(tree.getroot().iter("testsuite"))
            summary["tests"] = sum(int(s.attrib.get("tests", "0")) for s in suites)
            summary["failures"] = sum(int(s.attrib.get("failures", "0")) for s in suites)
            summary["errors"] = sum(int(s.attrib.get("errors", "0")) for s in suites)
            summary["skipped"] = sum(int(s.attrib.get("skipped", "0")) for s in suites)
        except (ET.ParseError, ValueError):
            summary["errors"] = 1
    else:
        summary["errors"] = 1
    passed = code == 0 and summary["tests"] > 0 and not any(summary[k] for k in ("failures", "errors", "skipped"))
    return {"argv": argv, "exit_code": code, "outcome": "passed" if passed else outcome if outcome != "completed" else "failed",
            "duration_seconds": round(time.time() - started, 3), "log": str(log),
            "log_sha256": sha256(log), "junit": str(junit), "junit_sha256": sha256(junit) if junit.is_file() else None,
            "junit_summary": summary}


class AcceptanceLoop:
    def __init__(self, root: Path, state_dir: Path, manifests: list[Path], max_attempts: int,
                 wall_seconds: float, suite_timeout: float):
        self.root, self.state_dir = root.resolve(), state_dir.expanduser().absolute()
        self.manifests = manifests
        self.max_attempts, self.wall_seconds, self.suite_timeout = max_attempts, wall_seconds, suite_timeout
        if max_attempts not in (1, 2) or not math.isfinite(wall_seconds) or not math.isfinite(suite_timeout) or wall_seconds <= 0 or suite_timeout <= 0:
            raise ValueError("attempts must be 1..2 and time bounds must be finite positive values")

    def run(self) -> int:
        cursor = Path(self.state_dir.anchor)
        for part in self.state_dir.parts[1:]:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(f"state directory traverses a symlink: {cursor}")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.state_dir.resolve(strict=True)
        if self.root == self.state_dir or self.root in self.state_dir.parents:
            raise ValueError("state directory must be outside the source checkout")
        lock_path = self.state_dir / "controller.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(lock_fd, "a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 73
            state_path = self.state_dir / "state.json"
            report_path = self.state_dir / "report.json"
            invocation_started_at = time.time()
            attempt_path = self.state_dir / "attempt.json"
            next_action_path = self.state_dir / "next-action.json"
            for output_path in (state_path, report_path, attempt_path, next_action_path):
                if output_path.is_symlink() or (output_path.exists() and not output_path.is_file()):
                    raise ValueError(f"state output must be a regular nonsymlink file: {output_path}")

            bundle_ok, rehearsal_records, _evidence_paths = verify_rehearsals(self.manifests)
            validated_hashes = _hashes_from_records(rehearsal_records)
            input_paths = [Path(path) for path in validated_hashes]
            try:
                fp = source_fingerprint(self.root, input_paths)
                input_fingerprint_error = None
            except (OSError, ValueError) as exc:
                input_fingerprint_error = str(exc)
                bundle_ok = False
                try:
                    fp = source_fingerprint(self.root, [])
                except (OSError, ValueError) as source_exc:
                    self._write_blocked(report_path, "blocked_invalid_inputs", str(source_exc))
                    return 2
            evidence_changed = input_fingerprint_error is not None or any(
                fp.get(path) != digest for path, digest in validated_hashes.items())
            if evidence_changed:
                bundle_ok = False
            if state_path.exists():
                try:
                    prior = json.loads(state_path.read_text(encoding="utf-8"))
                    if (not isinstance(prior, dict) or prior.get("schema") != 2
                            or not isinstance(prior.get("attempts"), list)
                            or not isinstance(prior.get("fingerprint"), dict)
                            or not isinstance(prior.get("total_attempt_count"), int)
                            or isinstance(prior.get("total_attempt_count"), bool)
                            or prior["total_attempt_count"] < len(prior["attempts"])
                            or prior["total_attempt_count"] > self.max_attempts
                            or not isinstance(prior.get("started_at"), (int, float))
                            or isinstance(prior.get("started_at"), bool)
                            or not math.isfinite(prior["started_at"])
                            or prior["started_at"] > time.time()
                            or any(not isinstance(item, dict) or not isinstance(item.get("status"), str)
                                   for item in prior["attempts"])):
                        raise ValueError("state schema/attempts/start time are malformed")
                    if prior.get("fingerprint") == fp:
                        state = prior
                    else:
                        state = {"schema": 2, "attempts": [], "fingerprint": fp,
                                 "started_at": prior["started_at"],
                                 "total_attempt_count": prior["total_attempt_count"],
                                 "fingerprint_changed": True,
                                 "superseded_fingerprints": prior.get("superseded_fingerprints", []) + [prior.get("fingerprint")],
                                 "superseded_attempts": prior.get("superseded_attempts", []) + prior["attempts"]}
                        atomic_json(state_path, state)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._write_blocked(report_path, "blocked_malformed_state", str(exc))
                    return 2
            else:
                state = {"schema": 2, "attempts": [], "fingerprint": fp, "started_at": invocation_started_at,
                         "total_attempt_count": 0, "fingerprint_changed": False,
                         "superseded_attempts": [], "superseded_fingerprints": []}
                atomic_json(state_path, state)
            attempts = state["attempts"]
            for unfinished in attempts:
                if isinstance(unfinished, dict) and unfinished.get("status") == "running":
                    unfinished.update(status="runner_interrupted", finished_at=time.time())
                    atomic_json(state_path, state)
            valid_prior = next((a for a in reversed(attempts) if self._valid_attempt(a, fp)), None)
            if valid_prior is None:
                retry_allowed = (state["total_attempt_count"] == 0 or
                                 (not attempts and state.get("fingerprint_changed") is True
                                  and state["total_attempt_count"] < self.max_attempts) or
                                 (attempts and attempts[-1].get("status") in TRANSIENT_OUTCOMES
                                  and state["total_attempt_count"] < self.max_attempts))
                if not retry_allowed:
                    latest = attempts[-1] if attempts else {}
                    status = "suite_timeout" if latest.get("status") == "timeout" else "acceptance_failed"
                    self._write_report(report_path, status, latest, rehearsal_records, fp)
                    return 2

                while valid_prior is None:
                    remaining = self.wall_seconds - (time.time() - state.get("started_at", time.time()))
                    timeout = min(self.suite_timeout, remaining)
                    if timeout <= 0:
                        latest = attempts[-1] if attempts else {}
                        status = "suite_timeout" if latest.get("status") == "timeout" else "blocked_wall_clock_limit"
                        self._write_report(report_path, status, latest, rehearsal_records, fp)
                        return 2
                    index = state["total_attempt_count"] + 1
                    generation = hashlib.sha256(json.dumps(fp, sort_keys=True).encode("utf-8")).hexdigest()[:12]
                    attempt_dir = self.state_dir / f"attempt-{generation}-{time.time_ns()}-{index}"
                    attempt_dir.mkdir(mode=0o700)
                    attempt = {"index": index, "status": "running", "fingerprint": fp,
                               "directory": str(attempt_dir), "started_at": time.time(),
                               "log": str(attempt_dir / "acceptance.log"),
                               "junit": str(attempt_dir / "junit.xml")}
                    attempts.append(attempt)
                    state["total_attempt_count"] = index
                    atomic_json(state_path, state)
                    atomic_json(attempt_path, attempt)
                    argv = [sys.executable, "-m", "pytest", "-q", "--strict-markers", "-o", "addopts=",
                            "--junitxml", attempt["junit"], *SUITE]
                    try:
                        result = execute(argv, self.root, Path(attempt["log"]), timeout, Path(attempt["junit"]))
                    except KeyboardInterrupt:
                        attempt.update(status="runner_interrupted", finished_at=time.time())
                        atomic_json(state_path, state)
                        atomic_json(attempt_path, attempt)
                        self._write_blocked(report_path, "runner_interrupted",
                                            "User interrupted the suite. Resume explicitly after review; this invocation will not retry cancellation.")
                        return 130
                    try:
                        after_fp = source_fingerprint(self.root, input_paths)
                    except (OSError, ValueError) as exc:
                        after_fp = None
                        attempt["post_run_fingerprint_error"] = str(exc)
                    attempt.update(result)
                    attempt["status"] = result["outcome"] if after_fp == fp else "source_changed_during_run"
                    attempt["finished_at"] = time.time()
                    atomic_json(state_path, state)
                    atomic_json(attempt_path, attempt)
                    valid_prior = attempt if self._valid_attempt(attempt, fp) else None
                    if after_fp != fp:
                        break
                    if valid_prior is None and attempt["status"] == "timeout":
                        remaining = self.wall_seconds - (time.time() - state["started_at"])
                        if state["total_attempt_count"] < self.max_attempts and remaining > 0:
                            continue
                    break
            verified_again, final_records, _final_paths = verify_rehearsals(self.manifests)
            final_hashes = _hashes_from_records(final_records)
            try:
                final_fp = source_fingerprint(self.root, [Path(path) for path in final_hashes])
            except (OSError, ValueError) as exc:
                final_fp = None
                final_fp_error = str(exc)
            else:
                final_fp_error = None
            if (validated_hashes != final_hashes
                    or any(fp.get(path) != digest for path, digest in validated_hashes.items())
                    or final_fp is None
                    or any(final_fp.get(path) != digest for path, digest in final_hashes.items())):
                evidence_changed = True
            if evidence_changed:
                for previous_attempt in attempts:
                    if previous_attempt.get("status") == "passed" and previous_attempt.get("fingerprint") == fp:
                        previous_attempt.update(status="evidence_changed", invalidated_at=time.time())
                atomic_json(state_path, state)
                self._write_blocked(report_path, "blocked_evidence_changed",
                                    "A manifest, rehearsal report, marker, or bound evidence file changed between verification snapshots.")
                return 2
            if final_fp is None or final_fp != fp:
                self._write_blocked(report_path, "blocked_source_changed_during_run",
                                    final_fp_error or "Source changed after the acceptance suite or during evidence revalidation.")
                return 2
            bundle_ok = bundle_ok and verified_again
            rehearsal_records = final_records

            if valid_prior is None:
                latest = attempts[-1] if attempts else {}
                if latest.get("status") == "timeout":
                    status = "suite_timeout"
                elif latest.get("status") not in (None, "passed"):
                    status = "acceptance_failed"
                else:
                    status = "blocked_missing_rehearsal_inputs" if not bundle_ok else "acceptance_failed"
                self._write_report(report_path, status, latest, rehearsal_records, fp)
                return 2
            # Evidence pass is not plan completion: external approval remains mandatory.
            if time.time() - state["started_at"] >= self.wall_seconds:
                self._write_blocked(report_path, "blocked_wall_clock_limit", "Durable wall-clock budget was exhausted.")
                return 2
            status = "blocked_missing_rehearsal_inputs" if not bundle_ok else "blocked_external_approval"
            self._write_report(report_path, status, valid_prior, rehearsal_records, fp)
            return 2

    def _valid_attempt(self, attempt: Any, fp: dict[str, str]) -> bool:
        if (not isinstance(attempt, dict) or attempt.get("status") != "passed"
                or attempt.get("fingerprint") != fp or attempt.get("exit_code") != 0):
            return False
        try:
            directory = Path(attempt["directory"])
            log, junit = Path(attempt["log"]), Path(attempt["junit"])
            if (directory.is_symlink() or directory.parent.resolve() != self.state_dir
                    or directory.resolve() != directory or log.parent != directory or junit.parent != directory
                    or any(path.is_symlink() or not path.is_file() for path in (log, junit))):
                return False
            expected = [sys.executable, "-m", "pytest", "-q", "--strict-markers", "-o", "addopts=",
                        "--junitxml", str(junit), *SUITE]
            if attempt.get("argv") != expected:
                return False
            if sha256(log) != attempt["log_sha256"] or sha256(junit) != attempt["junit_sha256"]:
                return False
            summary = self._junit_summary(junit)
            return (summary == attempt.get("junit_summary") and summary["tests"] > 0
                    and not any(summary[key] for key in ("failures", "errors", "skipped")))
        except (OSError, KeyError, TypeError, ValueError, ET.ParseError):
            return False

    @staticmethod
    def _junit_summary(junit: Path) -> dict[str, int]:
        tree = ET.parse(junit)
        suites = [tree.getroot()] if tree.getroot().tag == "testsuite" else list(tree.getroot().iter("testsuite"))
        summary = {key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
                   for key in ("tests", "failures", "errors", "skipped")}
        if any(value < 0 for value in summary.values()):
            raise ValueError("JUnit counters cannot be negative")
        return summary

    def _next_action(self, status: str, attempt: Any = None, rehearsals: Any = None,
                     detail: str | None = None) -> dict[str, Any]:
        if status == "acceptance_failed":
            log = attempt.get("log") if isinstance(attempt, dict) else None
            action = "Inspect the fixed-suite log/JUnit, fix the failing source locally, then synchronize and rerun; unchanged deterministic failures are not retried."
            return {"action": action, "log": log, "junit": attempt.get("junit") if isinstance(attempt, dict) else None}
        if status == "suite_timeout":
            return {"action": "Investigate runtime load, dependency setup, and the timeout log; resume only within the remaining durable wall-clock and attempt budgets.",
                    "log": attempt.get("log") if isinstance(attempt, dict) else None}
        if status == "blocked_missing_rehearsal_inputs":
            records = rehearsals if isinstance(rehearsals, list) else []
            invalid = [record for record in records if isinstance(record, dict) and record.get("error")]
            return {"action": "Supply three independent full-shell rehearsal manifests with distinct safe requested-ID sets, publication disabled, successful reports, and hashed in-root stage/failure/recovery evidence.",
                    "required_runs": 3, "supplied_manifests": len(self.manifests), "invalid_reports": invalid}
        if status == "blocked_external_approval":
            return {"action": "Obtain human sample approval and independently observe deployment authorization and live cron; this controller cannot attest these gates.",
                    "external_gates": ["human_sample_approval", "deployment", "live_cron_observation"]}
        if status == "runner_interrupted":
            return {"action": "User cancellation was recorded and will not be retried in this invocation. Review state/logs, then explicitly resume if appropriate."}
        if status == "blocked_wall_clock_limit":
            return {"action": "Inspect elapsed time and state; prepare required inputs and dependencies before a new bounded invocation."}
        if status == "blocked_evidence_changed":
            return {"action": "Freeze the three rehearsal roots and evidence, regenerate manifests if needed, then rerun verification; no report was accepted from mixed snapshots."}
        if status == "blocked_source_changed_during_run":
            return {"action": "Inspect the recorded source-fingerprint error/change, repair locally, then start a new bounded attempt."}
        return {"action": "Inspect the report/state and resolve the specific blocker before resuming.", "detail": detail}

    def _write_report(self, path: Path, status: str, attempt: Any, rehearsals: Any, fp: Any) -> None:
        next_action = self._next_action(status, attempt, rehearsals)
        report = {"status": status, "plan_complete": False, "attempt": attempt,
                  "rehearsals": rehearsals, "fingerprint": fp,
                  "external_gates": {"human_sample_approval": "unverified", "deployment": "unverified",
                                     "live_cron_observation": "unverified"},
                  "next_action": next_action}
        atomic_json(path, report)
        atomic_json(self.state_dir / "next-action.json", next_action)

    def _write_blocked(self, path: Path, status: str, detail: str) -> None:
        next_action = self._next_action(status, detail=detail)
        report = {"status": status, "plan_complete": False, "detail": detail,
                  "external_gates": {"human_sample_approval": "unverified", "deployment": "unverified",
                                     "live_cron_observation": "unverified"},
                  "next_action": next_action}
        atomic_json(path, report)
        atomic_json(self.state_dir / "next-action.json", next_action)
