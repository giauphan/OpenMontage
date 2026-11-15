"""File-backed request/response boundary for an agent running on the local host.

Requests and responses are runtime state, not application source. A local
supervisor must transfer requests and submit responses using the request digest.
The absence of a supervisor never causes a server-side agent fallback.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from typing import Any


class HandoffError(RuntimeError):
    """A local-agent handoff could not be completed safely."""


def _validate_safe_root(root: Path | str) -> Path:
    if not root:
        raise HandoffError("empty handoff root directory")
    raw_str = str(root)
    if "\x00" in raw_str or raw_str.startswith("-"):
        raise HandoffError("invalid handoff root path")
    path = Path(root).resolve()
    if path.is_symlink():
        raise HandoffError("handoff root cannot be a symlink")
    return path


def _validate_safe_request_dir(root: Path, request_id: str) -> Path:
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise HandoffError("invalid local-agent request ID")
    safe_root = _validate_safe_root(root)
    unresolved_dir = safe_root / request_id
    if unresolved_dir.is_symlink():
        raise HandoffError("request directory cannot be a symlink")
    directory = unresolved_dir.resolve()
    try:
        directory.relative_to(safe_root)
    except ValueError:
        raise HandoffError("request directory escapes handoff root")
    if directory.is_symlink():
        raise HandoffError("request directory cannot be a symlink")
    return directory


def _read_request(root: Path, request_id: str) -> dict[str, Any]:
    directory = _validate_safe_request_dir(root, request_id)
    path = (directory / "request.json").resolve()
    try:
        path.relative_to(directory)
    except ValueError:
        raise HandoffError("request file escapes request directory")
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
            raise HandoffError("invalid local-agent request file")
        with open(path, "r", encoding="utf-8") as f:
            request = json.load(f)
        digest = request.pop("request_sha256")
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if request.get("request_id") != request_id or not isinstance(digest, str) or hashlib.sha256(encoded).hexdigest() != digest:
            raise HandoffError("local-agent request digest mismatch")
        request["request_sha256"] = digest
        return request
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HandoffError("invalid local-agent request") from exc


def list_pending_requests(root: Path) -> list[dict[str, Any]]:
    try:
        safe_root = _validate_safe_root(root)
    except HandoffError:
        return []
    if not safe_root.is_dir():
        return []
    pending = []
    for directory in sorted(safe_root.iterdir()):
        if not re.fullmatch(r"[0-9a-f]{32}", directory.name) or directory.is_symlink() or not directory.is_dir():
            continue
        if (directory / "terminal.json").exists() or (directory / "response.json").exists():
            continue
        try:
            pending.append(_read_request(safe_root, directory.name))
        except HandoffError:
            continue
    return pending


def submit_local_response(root: Path, request_id: str, request_sha256: str, result: dict[str, Any], *, status: str = "ok") -> None:
    directory = _validate_safe_request_dir(root, request_id)
    request = _read_request(root, request_id)
    if request_sha256 != request["request_sha256"] or not isinstance(result, dict) or status not in ("ok", "error"):
        raise HandoffError("local-agent response does not match request")
    lock_path = (directory / "response.lock").resolve()
    try:
        lock_path.relative_to(directory)
    except ValueError:
        raise HandoffError("lock file escapes request directory")
    if lock_path.is_symlink():
        raise HandoffError("lock file cannot be a symlink")
    lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if (directory / "terminal.json").exists() or (directory / "response.json").exists():
            raise HandoffError("local-agent request is no longer pending")
        _atomic_json(directory / "response.json", {"request_id": request_id, "request_sha256": request_sha256,
                                                   "status": status, "result": result})
    finally:
        os.close(lock_fd)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    p = Path(path)
    raw_str = str(p)
    if "\x00" in raw_str or raw_str.startswith("-") or p.is_symlink():
        raise HandoffError("invalid atomic json target path")
    parent_dir = p.parent
    if parent_dir.is_symlink():
        raise HandoffError("invalid atomic json parent directory")
    target_path = p.resolve()
    if target_path.is_symlink():
        raise HandoffError("invalid atomic json target path")
    resolved_parent = target_path.parent.resolve()
    if not resolved_parent.is_dir() or resolved_parent.is_symlink():
        raise HandoffError("invalid atomic json parent directory")
    try:
        target_path.relative_to(resolved_parent)
    except ValueError:
        raise HandoffError("target path escapes parent directory")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".handoff-", dir=resolved_parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request_local_agent(
    root: Path, kind: str, payload: dict[str, Any], *, timeout_seconds: float, poll_seconds: float = 0.5,
) -> dict[str, Any]:
    """Publish a request and wait for a matching local response, or fail closed."""
    if kind not in {"news_selection", "director", "quality_review"}:
        raise HandoffError("unsupported local-agent request kind")
    if not isinstance(payload, dict) or timeout_seconds <= 0 or poll_seconds <= 0:
        raise HandoffError("invalid local-agent request or timeout")
    safe_root = _validate_safe_root(root)
    safe_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_dir = (safe_root / request_id).resolve()
    request_dir.mkdir(mode=0o700)
    request = {"request_id": request_id, "kind": kind, "payload": payload}
    digest_input = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    request["request_sha256"] = hashlib.sha256(digest_input).hexdigest()
    _atomic_json(request_dir / "request.json", request)
    deadline = time.monotonic() + timeout_seconds
    response_path = (request_dir / "response.json").resolve()
    while time.monotonic() < deadline:
        if response_path.exists():
            try:
                if response_path.is_symlink() or response_path.stat().st_size > 5_000_000:
                    raise ValueError("invalid response file")
                with open(response_path, "r", encoding="utf-8") as f:
                    response = json.load(f)
                if not isinstance(response, dict) or response.get("request_id") != request_id or response.get("request_sha256") != request["request_sha256"]:
                    raise HandoffError("local-agent response does not match request")
                if response.get("status") != "ok" or not isinstance(response.get("result"), dict):
                    raise HandoffError("local agent returned an error or invalid result")
                _atomic_json(request_dir / "terminal.json", {"status": "completed"})
                return response["result"]
            except (OSError, ValueError, UnicodeError) as exc:
                raise HandoffError("invalid local-agent response") from exc
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    _atomic_json(request_dir / "terminal.json", {"status": "timed_out"})
    raise HandoffError("local-agent request timed out")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read and answer local-agent runtime requests")
    parser.add_argument("action", choices=("pending", "submit"))
    parser.add_argument("--root", default=os.environ.get("OPENMONTAGE_AGENT_HANDOFF_DIR") or str(Path(__file__).resolve().parents[1] / "data" / "local_agent_handoff"))
    args = parser.parse_args()
    try:
        if args.action == "pending":
            print(json.dumps(list_pending_requests(Path(args.root)), ensure_ascii=False))
        else:
            raw = sys.stdin.buffer.read(5_000_001)
            if len(raw) > 5_000_000:
                raise HandoffError("local-agent response is too large")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise HandoffError("invalid local-agent response")
            submit_local_response(Path(args.root), value.get("request_id"), value.get("request_sha256"), value.get("result"), status=value.get("status", "ok"))
            print('{"status":"accepted"}')
    except (HandoffError, OSError, ValueError, TypeError) as exc:
        print(f"local-agent handoff: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
