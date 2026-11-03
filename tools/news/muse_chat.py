"""Muse chat transport with durable, isolated conversation contexts."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID


class MuseChatError(RuntimeError):
    """Muse could not complete a request safely."""


def _post(url: str, payload: dict, timeout: float) -> dict:
    request = Request(url, data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise MuseChatError("Muse response exceeded size limit")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise MuseChatError("Muse returned invalid JSON") from exc


def _uuid(value: Any) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise MuseChatError("Muse returned an invalid thread identifier") from exc


class MuseChatClient:
    def __init__(self, base_url: str, state_path: Path, *, timeout: float = 390, transport: Callable = _post):
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Muse gateway must be an HTTP(S) origin without credentials or a path")
        self.url = base_url.rstrip("/") + "/muse-ai/v1/chat/completions"
        self.state_path = Path(state_path)
        self.timeout = timeout
        self.transport = transport

    def _load(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("not an object")
            return state
        except (OSError, ValueError) as exc:
            raise MuseChatError("Cannot read Muse thread state") from exc

    def _save(self, state: dict) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".muse-threads-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(state, out, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self.state_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _request(self, state: dict, context_key: str, payload: dict, thread: str | None) -> tuple[dict, str | None, dict | None]:
        try:
            return self.transport(self.url, payload, self.timeout), thread, state.get(context_key)
        except HTTPError as exc:
            if exc.code != 404 or not thread:
                raise MuseChatError(f"Muse gateway returned HTTP {exc.code}") from exc
        del state[context_key]
        self._save(state)
        payload = {key: value for key, value in payload.items() if key != "reply_thread_id"}
        try:
            return self.transport(self.url, payload, self.timeout), None, None
        except HTTPError as exc:
            raise MuseChatError(f"Muse gateway returned HTTP {exc.code}") from exc
        except OSError as exc:
            raise MuseChatError("Muse gateway request failed") from exc

    @staticmethod
    def _completion(result: dict) -> tuple[str, str]:
        if not isinstance(result, dict):
            raise MuseChatError("Muse returned a malformed response")
        next_thread = _uuid(result.get("reply_thread_id") or result.get("thread_id") or result.get("session_id"))
        try:
            choice = result["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
                raise ValueError("empty or incomplete completion")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MuseChatError("Muse returned an incomplete completion") from exc
        return next_thread, content

    def _persist_turn(self, state: dict, context_key: str, cached: dict | None, thread: str | None, next_thread: str, content: str) -> None:
        if thread and next_thread != thread:
            raise MuseChatError("Muse returned a different thread for a continuation")
        timestamp_ms = int(time.time() * 1000)
        old_turns = cached.get("turns", 0) if cached else 0
        if not isinstance(old_turns, int) or isinstance(old_turns, bool) or old_turns < 0:
            raise MuseChatError("Invalid Muse thread turn count")
        state[context_key] = {
            "thread_id": next_thread, "turns": old_turns + 1,
            "created_at": cached.get("created_at", timestamp_ms) if cached else timestamp_ms,
            "last_active_at": timestamp_ms, "last_summary": " ".join(content.split())[:200],
        }
        self._save(state)

    def chat(self, context_key: str, prompt: str) -> str:
        if not context_key or not prompt:
            raise ValueError("Muse context and prompt are required")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.state_path) + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._load()
            cached = state.get(context_key)
            if cached is not None and not isinstance(cached, dict):
                raise MuseChatError("Invalid Muse thread state")
            thread = _uuid(cached.get("thread_id")) if isinstance(cached, dict) else None
            payload = {"model": "muse", "messages": [{"role": "user", "content": prompt}]}
            if thread:
                payload["reply_thread_id"] = thread
            try:
                result, thread, cached = self._request(state, context_key, payload, thread)
            except OSError as exc:
                raise MuseChatError("Muse gateway request failed") from exc
            next_thread, content = self._completion(result)
            self._persist_turn(state, context_key, cached, thread, next_thread, content)
            return content
