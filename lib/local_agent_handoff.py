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


def _read_request(root: Path, request_id: str) -> dict[str, Any]:
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise HandoffError("invalid local-agent request ID")
    directory = Path(root) / request_id
    path = directory / "request.json"
    try:
        if directory.is_symlink() or path.is_symlink() or path.stat().st_size > 20_000_000:
            raise HandoffError("invalid local-agent request file")
        request = json.loads(path.read_text(encoding="utf-8"))
        digest = request.pop("request_sha256")
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if request.get("request_id") != request_id or not isinstance(digest, str) or hashlib.sha256(encoded).hexdigest() != digest:
            raise HandoffError("local-agent request digest mismatch")
        request["request_sha256"] = digest
        return request
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HandoffError("invalid local-agent request") from exc


def list_pending_requests(root: Path) -> list[dict[str, Any]]:
    root = Path(root)
    if not root.is_dir():
        return []
    pending = []
    for directory in sorted(root.iterdir()):
        if not re.fullmatch(r"[0-9a-f]{32}", directory.name) or directory.is_symlink() or not directory.is_dir():
            continue
        if (directory / "terminal.json").exists() or (directory / "response.json").exists():
            continue
        try:
            pending.append(_read_request(root, directory.name))
        except HandoffError:
            continue
    return pending


def submit_local_response(root: Path, request_id: str, request_sha256: str, result: dict[str, Any], *, status: str = "ok") -> None:
    root = Path(root)
    request = _read_request(root, request_id)
    if request_sha256 != request["request_sha256"] or not isinstance(result, dict) or status not in ("ok", "error"):
        raise HandoffError("local-agent response does not match request")
    directory = root / request_id
    lock_fd = os.open(directory / "response.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if (directory / "terminal.json").exists() or (directory / "response.json").exists():
            raise HandoffError("local-agent request is no longer pending")
        _atomic_json(directory / "response.json", {"request_id": request_id, "request_sha256": request_sha256,
                                                   "status": status, "result": result})
    finally:
        os.close(lock_fd)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".handoff-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
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
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_dir = root / request_id
    request_dir.mkdir(mode=0o700)
    request = {"request_id": request_id, "kind": kind, "payload": payload}
    digest_input = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    request["request_sha256"] = hashlib.sha256(digest_input).hexdigest()
    _atomic_json(request_dir / "request.json", request)
    deadline = time.monotonic() + timeout_seconds
    response_path = request_dir / "response.json"
    while time.monotonic() < deadline:
        if response_path.exists():
            try:
                if response_path.is_symlink() or response_path.stat().st_size > 5_000_000:
                    raise ValueError("invalid response file")
                response = json.loads(response_path.read_text(encoding="utf-8"))
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
