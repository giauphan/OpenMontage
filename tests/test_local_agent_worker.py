import base64
import hashlib
import json

import pytest


def _worker_module():
    try:
        from scripts import local_agent_worker
    except ImportError:
        pytest.fail("local agent worker is not implemented")
    return local_agent_worker


def test_selection_worker_returns_structured_result_without_server_cli(tmp_path):
    worker = _worker_module()
    seen = []
    def agent(prompt, cwd, images, model):
        seen.append((prompt, cwd, images, model))
        return '{"selected_candidate_id":"candidate-1","research_draft":{}}'
    request = {"request_id": "a" * 32, "kind": "news_selection", "payload": {"prompt": "select a topic"}}
    result = worker.process_request(request, tmp_path, "model-medium-hight", agent)
    assert result["selected_candidate_id"] == "candidate-1"
    assert seen[0][0] == "select a topic"
    assert seen[0][1].is_relative_to(tmp_path)
    assert seen[0][3] == "model-medium-hight"


def test_director_worker_returns_only_project_artifacts(tmp_path):
    worker = _worker_module()
    def agent(prompt, cwd, images, model):
        assert str(cwd) in prompt
        assert json.loads((cwd / "artifacts/research_brief.json").read_text())["title"] == "source"
        (cwd / "artifacts/script_vi.json").write_text("{}")
        (cwd / "hyperframes/index.html").write_text("full")
        (cwd / "hyperframes_reels/index.html").write_text("short")
        (cwd / "unrequested.txt").write_text("excluded")
        return "DIRECTOR_OK"
    request = {"request_id": "b" * 32, "kind": "director", "payload": {
        "project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": '{"title":"source"}',
        "prompt": "write /app/projects/cand_1", "system": "work in /app/projects/cand_1", "existing_files": {},
    }}
    result = worker.process_request(request, tmp_path, "model-medium-hight", agent)
    assert result["files"]["hyperframes/index.html"] == "full"
    assert "unrequested.txt" not in result["files"]


def test_director_worker_receives_captured_source_text(tmp_path):
    worker = _worker_module()
    def agent(prompt, cwd, images, model):
        assert "Evidence from official source" in prompt
        (cwd / "artifacts/script_vi.json").write_text("{}")
        (cwd / "hyperframes/index.html").write_text("full")
        (cwd / "hyperframes_reels/index.html").write_text("short")
        return "DIRECTOR_OK"
    request = {"request_id": "8" * 32, "kind": "director", "payload": {"project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": "{}", "prompt": "write", "system": "work", "existing_files": {}, "captured_source_text": "Evidence from official source"}}
    worker.process_request(request, tmp_path, "model-medium-hight", agent)


def test_quality_worker_attaches_verified_frames(tmp_path):
    worker = _worker_module()
    data = b"actual frame"
    def agent(prompt, cwd, images, model):
        assert len(images) == 1 and images[0].read_bytes() == data
        assert str(images[0]) in prompt
        return '{"overall_passed":false}'
    request = {"request_id": "c" * 32, "kind": "quality_review", "payload": {
        "prompt": "inspect /server/frame.png", "frames": [{"server_path": "/server/frame.png", "sha256": hashlib.sha256(data).hexdigest(), "content_base64": base64.b64encode(data).decode()}],
    }}
    assert worker.process_request(request, tmp_path, "model-medium-hight", agent) == {"overall_passed": False}


def test_worker_rejects_path_traversal_in_director_inputs(tmp_path):
    worker = _worker_module()
    request = {"request_id": "d" * 32, "kind": "director", "payload": {
        "project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": "{}",
        "prompt": "x", "system": "x", "existing_files": {"../../bad": "bad"},
    }}
    with pytest.raises(worker.WorkerError):
        worker.process_request(request, tmp_path, "model-medium-hight", lambda *args: pytest.fail("agent must not run"))


def test_supervisor_returns_failure_without_inventing_result(tmp_path):
    worker = _worker_module()
    request = {"request_id": "e" * 32, "request_sha256": "digest", "kind": "news_selection", "payload": {"prompt": "select"}}
    sent = []
    def fail_agent(*args):
        raise worker.WorkerError("unavailable")
    result = worker.process_pending([request], tmp_path, "model-medium-hight", fail_agent, sent.append)
    assert result == 1
    assert sent == [{"request_id": "e" * 32, "request_sha256": "digest", "status": "error", "result": {}}]


def test_worker_accepts_json_with_markdown_fences(tmp_path):
    worker = _worker_module()
    request = {"request_id": "f" * 32, "kind": "news_selection", "payload": {"prompt": "select"}}
    result = worker.process_request(request, tmp_path, "model-medium-hight", lambda *args: 'Here is the result:\n```json\n{"selected_candidate_id":"p1","research_draft":{}}\n```')
    assert result["selected_candidate_id"] == "p1"


def test_worker_accepts_templated_director_artifacts(tmp_path):
    worker = _worker_module()
    def agent(prompt, cwd, images, model):
        (cwd / "artifacts/script_vi.json").write_text("{}")
        (cwd / "artifacts/template_selection.json").write_text("{}")
        (cwd / "artifacts/template_content.json").write_text("{}")
        return "DIRECTOR_OK"
    request = {"request_id": "1" * 32, "kind": "director", "payload": {"project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": "{}", "prompt": "write", "system": "work", "existing_files": {}}}
    files = worker.process_request(request, tmp_path, "model-medium-hight", agent)["files"]
    assert "artifacts/template_selection.json" in files and "artifacts/template_content.json" in files


def test_worker_rejects_stale_director_artifacts(tmp_path):
    worker = _worker_module()
    old = {"artifacts/script_vi.json": "{}", "hyperframes/index.html": "old full", "hyperframes_reels/index.html": "old short"}
    request = {"request_id": "2" * 32, "kind": "director", "payload": {"project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": "{}", "prompt": "write", "system": "work", "existing_files": old}}
    with pytest.raises(worker.WorkerError, match="fresh"):
        worker.process_request(request, tmp_path, "model-medium-hight", lambda *args: "DIRECTOR_OK")


def test_worker_accepts_successful_director_repair(tmp_path):
    worker = _worker_module()
    old = {"artifacts/script_vi.json": "{}", "hyperframes/index.html": "old full", "hyperframes_reels/index.html": "old short"}
    request = {"request_id": "9" * 32, "kind": "director", "payload": {"project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": "{}", "prompt": "repair", "system": "work", "existing_files": old}}
    def agent(prompt, cwd, images, model):
        (cwd / "hyperframes/index.html").write_text("fixed full")
        return "DIRECTOR_REPAIR_OK project=cand_1"
    assert worker.process_request(request, tmp_path, "model-medium-hight", agent)["files"]["hyperframes/index.html"] == "fixed full"


def test_supervisor_continues_after_one_response_submission_fails(tmp_path):
    worker = _worker_module()
    requests = [{"request_id": char * 32, "request_sha256": "digest", "kind": "news_selection", "payload": {"prompt": "select"}} for char in ("3", "4")]
    sent = []
    def submit(response):
        sent.append(response["request_id"])
        if len(sent) == 1:
            raise worker.WorkerError("expired")
    failures = worker.process_pending(requests, tmp_path, "model-medium-hight", lambda *args: '{"selected_candidate_id":"p1","research_draft":{}}', submit)
    assert failures == 1
    assert sent == ["3" * 32, "4" * 32]


def test_supervisor_retries_submission_without_rerunning_agent(tmp_path):
    worker = _worker_module()
    request = {"request_id": "5" * 32, "request_sha256": "digest", "kind": "news_selection", "payload": {"prompt": "select"}}
    calls, sent, outbox = [], [], {}
    def agent(*args):
        calls.append(1)
        return '{"selected_candidate_id":"p1","research_draft":{}}'
    def submit(response):
        sent.append(response)
        if len(sent) == 1:
            raise worker.WorkerError("temporary failure")
    assert worker.process_pending([request], tmp_path, "model-medium-hight", agent, submit, outbox=outbox) == 1
    assert worker.process_pending([request], tmp_path, "model-medium-hight", agent, submit, outbox=outbox) == 0
    assert len(calls) == 1 and len(sent) == 2 and not outbox


@pytest.mark.parametrize("fail", [False, True])
def test_worker_removes_temporary_workspace_after_request(tmp_path, fail):
    worker = _worker_module()
    request = {"request_id": "6" * 32, "kind": "news_selection", "payload": {"prompt": "select"}}
    def agent(*args):
        if fail:
            raise worker.WorkerError("failed")
        return '{"selected_candidate_id":"p1","research_draft":{}}'
    if fail:
        with pytest.raises(worker.WorkerError):
            worker.process_request(request, tmp_path, "model-medium-hight", agent)
    else:
        worker.process_request(request, tmp_path, "model-medium-hight", agent)
    assert list((tmp_path / "projects/.local-agent-work").iterdir()) == []


def test_supervisor_ssh_calls_only_remote_handoff_interface(monkeypatch):
    from types import SimpleNamespace
    worker = _worker_module()
    calls = []
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    assert worker.remote_handoff("pending") == []
    command = calls[0][0]
    assert command[0] == "ssh"
    assert "sandbox-video" in command
    assert "lib.local_agent_handoff pending" in command[-1]
    assert "codex" not in " ".join(command)


def test_local_codex_command_preserves_gateway_and_selected_model(tmp_path):
    worker = _worker_module()
    command = worker.codex_command("model-medium-hight", tmp_path, [])
    assert command[0:2] == ["codex", "exec"]
    assert command[command.index("-m") + 1] == "model-medium-hight"
    assert 'model_provider="omniroute"' in command
    assert 'model_providers.omniroute.base_url="http://127.0.0.1:20128/v1"' in command
    assert 'model_providers.omniroute.env_key="OPENAI_API_KEY"' in command


def test_gateway_credential_is_not_logged_or_in_command(monkeypatch, capsys):
    from types import SimpleNamespace
    worker = _worker_module()
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="fixture-private-value", stderr="")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    assert worker.remote_gateway_credential() == "fixture-private-value"
    assert "fixture-private-value" not in capsys.readouterr().out
    assert "fixture-private-value" not in " ".join(calls[0])
    assert "codex exec" not in " ".join(calls[0])


def test_three_stages_round_trip_through_handoff(tmp_path):
    import threading
    import time
    from lib import local_agent_handoff as handoff
    worker = _worker_module()
    request_root = tmp_path / "requests"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    frame = b"frame"
    stages = [
        ("news_selection", {"prompt": "select"}),
        ("director", {"project_id": "cand_1", "server_project_dir": "/app/projects/cand_1", "research_brief": "{}", "prompt": "write /app/projects/cand_1", "system": "work /app/projects/cand_1", "existing_files": {}}),
        ("quality_review", {"prompt": "inspect /server/frame.png", "frames": [{"server_path": "/server/frame.png", "sha256": hashlib.sha256(frame).hexdigest(), "content_base64": base64.b64encode(frame).decode()}]}),
    ]
    def agent(prompt, cwd, images, model):
        if images:
            assert images[0].read_bytes() == frame
            return '{"overall_passed":false}'
        if "write " in prompt:
            (cwd / "artifacts/script_vi.json").write_text("{}")
            (cwd / "hyperframes/index.html").write_text("full")
            (cwd / "hyperframes_reels/index.html").write_text("short")
            return "DIRECTOR_OK"
        return '{"selected_candidate_id":"cand_1","research_draft":{}}'
    for kind, payload in stages:
        result = []
        server = threading.Thread(target=lambda: result.append(handoff.request_local_agent(request_root, kind, payload, timeout_seconds=3, poll_seconds=0.01)))
        server.start()
        deadline = time.monotonic() + 3
        requests = []
        while not requests and time.monotonic() < deadline:
            requests = handoff.list_pending_requests(request_root)
            time.sleep(0.01)
        assert len(requests) == 1
        def submit(response):
            handoff.submit_local_response(request_root, response["request_id"], response["request_sha256"], response["result"], status=response["status"])
        assert worker.process_pending(requests, workspace, "model-medium-hight", agent, submit) == 0
        server.join(timeout=3)
        assert len(result) == 1
        if kind == "director":
            assert result[0]["files"]["hyperframes/index.html"] == "full"
        if kind == "quality_review":
            assert result[0]["overall_passed"] is False
