import json
from urllib.error import HTTPError
from uuid import UUID

import pytest

from tools.news.muse_chat import MuseChatClient, MuseChatError


THREAD = "d6eeea7f-c5ab-4e23-bfe7-65df252329bd"
NEW_THREAD = "2b0b27df-c6b2-4544-b040-4f2c48a5bb8c"


def response(content, thread=THREAD):
    return {"reply_thread_id": thread, "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


def test_continues_persisted_context_across_client_instances(tmp_path):
    calls = []
    def transport(url, payload, timeout):
        calls.append((url, payload, timeout))
        return response("first" if len(calls) == 1 else "second")

    path = tmp_path / "threads.json"
    assert MuseChatClient("http://127.0.0.1:20129", path, transport=transport).chat("news", "first prompt") == "first"
    assert MuseChatClient("http://127.0.0.1:20129", path, transport=transport).chat("news", "second prompt") == "second"
    assert calls[0][0] == "http://127.0.0.1:20129/muse-ai/v1/chat/completions"
    assert "reply_thread_id" not in calls[0][1]
    assert calls[1][1]["reply_thread_id"] == THREAD
    saved = json.loads(path.read_text())["news"]
    assert UUID(saved["thread_id"]) == UUID(THREAD)
    assert saved["turns"] == 2
    assert saved["created_at"] <= saved["last_active_at"]
    assert saved["last_summary"] == "second"


def test_missing_thread_reseeds_once_but_approval_errors_do_not(tmp_path):
    path = tmp_path / "threads.json"
    path.write_text(json.dumps({"news": {"thread_id": THREAD}}))
    calls = []
    def expired(url, payload, timeout):
        calls.append(payload)
        if len(calls) == 1:
            raise HTTPError(url, 404, "missing thread", {}, None)
        return response("ok", NEW_THREAD)
    assert MuseChatClient("http://127.0.0.1:20129", path, transport=expired).chat("news", "prompt") == "ok"
    assert calls[0]["reply_thread_id"] == THREAD
    assert "reply_thread_id" not in calls[1]
    assert json.loads(path.read_text())["news"]["thread_id"] == NEW_THREAD

    def denied(url, payload, timeout):
        raise HTTPError(url, 409, "approval required", {}, None)
    with pytest.raises(MuseChatError, match="409"):
        MuseChatClient("http://127.0.0.1:20129", path, transport=denied).chat("news", "prompt")
    assert json.loads(path.read_text())["news"]["thread_id"] == NEW_THREAD


@pytest.mark.parametrize("bad", [{}, response("", THREAD), response("x", "not-a-uuid"), {"reply_thread_id": THREAD, "choices": [{"message": {"content": "x"}, "finish_reason": "length"}]}])
def test_malformed_response_fails_closed(tmp_path, bad):
    client = MuseChatClient("http://127.0.0.1:20129", tmp_path / "threads.json", transport=lambda *args: bad)
    with pytest.raises(MuseChatError):
        client.chat("news", "prompt")
