"""Contracts for the server-to-local-agent runtime handoff."""

import json
import threading
import time

import pytest


def _handoff_module():
    try:
        from lib import local_agent_handoff
    except ImportError:
        pytest.fail("local agent handoff is not implemented")
    return local_agent_handoff


def test_handoff_waits_for_response_bound_to_its_request(tmp_path):
    handoff = _handoff_module()
    received = []

    def local_worker():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            requests = list(tmp_path.glob("*/request.json"))
            if requests:
                request = json.loads(requests[0].read_text())
                received.append(request)
                response = {"request_id": request["request_id"], "request_sha256": request["request_sha256"],
                            "status": "ok", "result": {"selected_candidate_id": "candidate-1"}}
                temp = requests[0].parent / "response.tmp"
                temp.write_text(json.dumps(response))
                temp.replace(requests[0].parent / "response.json")
                return
            time.sleep(0.01)

    worker = threading.Thread(target=local_worker)
    worker.start()
    result = handoff.request_local_agent(tmp_path, "news_selection", {"candidates": ["candidate-1"]}, timeout_seconds=3, poll_seconds=0.01)
    worker.join(timeout=3)
    assert result == {"selected_candidate_id": "candidate-1"}
    assert received[0]["kind"] == "news_selection"
    assert received[0]["payload"]["candidates"] == ["candidate-1"]


def test_handoff_rejects_response_for_a_different_request(tmp_path):
    handoff = _handoff_module()

    def local_worker():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            requests = list(tmp_path.glob("*/request.json"))
            if requests:
                response = {"request_id": "wrong", "request_sha256": "wrong", "status": "ok", "result": {}}
                temp = requests[0].parent / "response.tmp"
                temp.write_text(json.dumps(response))
                temp.replace(requests[0].parent / "response.json")
                return
            time.sleep(0.01)

    worker = threading.Thread(target=local_worker)
    worker.start()
    with pytest.raises(handoff.HandoffError, match="does not match"):
        handoff.request_local_agent(tmp_path, "news_selection", {}, timeout_seconds=3, poll_seconds=0.01)
    worker.join(timeout=3)


def test_handoff_fails_closed_when_local_worker_is_unavailable(tmp_path):
    handoff = _handoff_module()
    with pytest.raises(handoff.HandoffError, match="timed out"):
        handoff.request_local_agent(tmp_path, "news_selection", {}, timeout_seconds=0.05, poll_seconds=0.01)


def test_server_news_selection_uses_handoff_without_starting_cli(tmp_path, monkeypatch):
    handoff = _handoff_module()
    from lib.codex_news_selector import CodexNewsSelector

    calls = []
    monkeypatch.setenv("OPENMONTAGE_REQUIRE_LOCAL_AGENT", "1")
    monkeypatch.setenv("OPENMONTAGE_AGENT_HANDOFF_DIR", str(tmp_path))
    monkeypatch.setattr(handoff, "request_local_agent", lambda root, kind, payload, **kw: calls.append((root, kind, payload)) or {"selected_candidate_id": "candidate-1", "research_draft": {}})
    def forbidden(*args, **kwargs):
        raise AssertionError("server attempted to launch a coding CLI")
    selector = CodexNewsSelector(transport=forbidden)
    result = selector._run_codex("selection prompt")
    assert result["selected_candidate_id"] == "candidate-1"
    assert calls == [(tmp_path, "news_selection", {"prompt": "selection prompt"})]


def test_server_news_selection_does_not_fallback_when_handoff_fails(tmp_path, monkeypatch):
    handoff = _handoff_module()
    from lib.codex_news_selector import CodexNewsSelector

    monkeypatch.setenv("OPENMONTAGE_REQUIRE_LOCAL_AGENT", "1")
    monkeypatch.setenv("OPENMONTAGE_AGENT_HANDOFF_DIR", str(tmp_path))
    def unavailable(*args, **kwargs):
        raise handoff.HandoffError("local worker unavailable")
    monkeypatch.setattr(handoff, "request_local_agent", unavailable)
    def forbidden(*args, **kwargs):
        raise AssertionError("server attempted to launch a coding CLI")
    with pytest.raises(handoff.HandoffError, match="unavailable"):
        CodexNewsSelector(transport=forbidden).select_and_research([{"candidate_id": "candidate-1", "title": "test"}])


def test_quality_review_handoff_includes_actual_sampled_frames(tmp_path, monkeypatch):
    import base64
    from types import SimpleNamespace
    from scripts.codex_validation_review import _run_cli_and_parse_response
    handoff = _handoff_module()

    frame = tmp_path / "sample.png"
    frame.write_bytes(b"frame bytes")
    captured = []
    monkeypatch.setenv("OPENMONTAGE_REQUIRE_LOCAL_AGENT", "1")
    monkeypatch.setenv("OPENMONTAGE_AGENT_HANDOFF_DIR", str(tmp_path / "requests"))
    monkeypatch.setattr(handoff, "request_local_agent", lambda root, kind, payload, **kw: captured.append((kind, payload)) or {"overall_passed": True})
    validator = SimpleNamespace(_review_transport=None)
    result = _run_cli_and_parse_response(validator, "forbidden-server-cli", "review prompt", frame_paths=[frame])
    assert result == {"overall_passed": True}
    assert captured[0][0] == "quality_review"
    assert base64.b64decode(captured[0][1]["frames"][0]["content_base64"]) == b"frame bytes"


def test_supervisor_can_list_and_complete_a_pending_request(tmp_path):
    handoff = _handoff_module()
    result = []
    worker = threading.Thread(target=lambda: result.append(
        handoff.request_local_agent(tmp_path, "news_selection", {"prompt": "select"}, timeout_seconds=3, poll_seconds=0.01)
    ))
    worker.start()
    deadline = time.monotonic() + 3
    requests = []
    while not requests and time.monotonic() < deadline:
        requests = handoff.list_pending_requests(tmp_path)
        time.sleep(0.01)
    assert len(requests) == 1
    request = requests[0]
    handoff.submit_local_response(tmp_path, request["request_id"], request["request_sha256"], {"selected_candidate_id": "p1"})
    worker.join(timeout=3)
    assert result == [{"selected_candidate_id": "p1"}]
    assert handoff.list_pending_requests(tmp_path) == []


def test_supervisor_cannot_submit_to_wrong_or_expired_request(tmp_path):
    handoff = _handoff_module()
    with pytest.raises(handoff.HandoffError, match="timed out"):
        handoff.request_local_agent(tmp_path, "news_selection", {}, timeout_seconds=0.05, poll_seconds=0.01)
    request_path = next(tmp_path.glob("*/request.json"))
    request = json.loads(request_path.read_text())
    with pytest.raises(handoff.HandoffError):
        handoff.submit_local_response(tmp_path, request["request_id"], request["request_sha256"], {})
    with pytest.raises(handoff.HandoffError):
        handoff.submit_local_response(tmp_path, "../../outside", "bad", {})


def test_local_worker_failure_is_reported_to_waiting_server(tmp_path):
    handoff = _handoff_module()
    failures = []
    def waiting_server():
        try:
            handoff.request_local_agent(tmp_path, "news_selection", {}, timeout_seconds=3, poll_seconds=0.01)
        except handoff.HandoffError as exc:
            failures.append(str(exc))
    server = threading.Thread(target=waiting_server)
    server.start()
    deadline = time.monotonic() + 3
    requests = []
    while not requests and time.monotonic() < deadline:
        requests = handoff.list_pending_requests(tmp_path)
        time.sleep(0.01)
    assert len(requests) == 1
    handoff.submit_local_response(tmp_path, requests[0]["request_id"], requests[0]["request_sha256"], {}, status="error")
    server.join(timeout=3)
    assert failures == ["local agent returned an error or invalid result"]


def test_quality_review_rejects_video_changed_during_local_handoff(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts import codex_validation_review as review

    project = tmp_path / "project"
    (project / "hyperframes").mkdir(parents=True)
    (project / "hyperframes/index.html").write_text("<main>scene</main>")
    video = project / "video.mp4"
    video.write_bytes(b"before")
    metadata = project / "metadata.json"
    metadata.write_text("{}")
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"frame")
    validator = SimpleNamespace(project_dir=project, _review_transport=None)
    monkeypatch.setenv("OPENMONTAGE_REQUIRE_LOCAL_AGENT", "1")
    monkeypatch.setattr(review, "_extract_review_frames", lambda *args: [frame])
    monkeypatch.setattr(review, "_get_probe_audio_streams", lambda: lambda _: "audio metadata")
    def change_video(*args, **kwargs):
        video.write_bytes(b"after")
        return {"overall_passed": True}
    monkeypatch.setattr(review, "_run_cli_and_parse_response", change_video)
    with pytest.raises(ValueError, match="changed during"):
        review.execute_cli_review_helper(validator, "local-codex-handoff", video, metadata, lambda **kwargs: kwargs)
