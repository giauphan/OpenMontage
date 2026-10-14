"""Dependency-injected offline transports still traverse production parsers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lib.codex_news_selector import CodexNewsSelector
from scripts.codex_agent_validation import CodexAgentValidator


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["fixture-agent"], returncode=returncode, stdout=stdout, stderr="")


def _review_payload(*, overall: bool = True) -> str:
    checks = {
        key: {"passed": True, "score": 4, "notes": "fixture-only response"}
        for key in ("visual_quality", "audio_sync", "content_appropriateness", "brand_compliance")
    }
    return json.dumps({**checks, "overall_passed": overall, "summary": "fixture review"})


def test_selector_injected_transport_parses_and_validates_reply():
    candidate = {"id": "topic-1", "title": "Fixture topic", "summary": "Fixture summary"}
    captured = {}

    def transport(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _completed(json.dumps({
            "selected_candidate_id": "topic-1",
            "research_draft": {"title": "Fixture research"},
        }))

    result = CodexNewsSelector(transport=transport).select_and_research([candidate])
    assert result["selected_candidate_id"] == "topic-1"
    assert result["research_draft"]["title"] == "Fixture research"
    assert captured["kwargs"]["timeout"] > 0
    assert captured["kwargs"]["stdin"] == subprocess.DEVNULL


def test_selector_injected_transport_unwraps_codex_json_event_stream():
    candidate = {"id": "topic-1", "title": "Fixture topic", "summary": "Fixture summary"}
    payload = {"selected_candidate_id": "topic-1", "research_draft": {"title": "Fixture research"}}
    event_stream = "\n".join([
        json.dumps({"type": "message", "message": {"content": [{"type": "output_text", "text": json.dumps(payload)}]}}),
        json.dumps({"type": "result", "result": json.dumps(payload)}),
    ])

    result = CodexNewsSelector(transport=lambda *args, **kwargs: _completed(event_stream)).select_and_research([candidate])

    assert result["selected_candidate_id"] == "topic-1"
    assert result["research_draft"]["title"] == "Fixture research"


def test_selector_injected_nonzero_malformed_and_timeout_fail_closed_to_existing_fallback():
    candidate = {"id": "topic-1", "title": "Fixture topic", "url": "https://example.test/a"}
    for reply in (_completed('{broken'), _completed("", returncode=7)):
        selector = CodexNewsSelector(transport=lambda *args, _reply=reply, **kwargs: _reply)
        fallback = selector.select_and_research([candidate])
        assert fallback["selected_candidate_id"] == "topic-1"
        assert fallback["research_status"] == "incomplete"

    invalid_schema = _completed('{"selected_candidate_id":"topic-1","research_draft":null}')
    assert CodexNewsSelector(transport=lambda *args, **kwargs: invalid_schema).select_and_research([candidate]) is None

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    fallback = CodexNewsSelector(transport=timeout).select_and_research([candidate])
    assert fallback["research_status"] == "incomplete"


def _reviewer(tmp_path: Path, transport) -> tuple[CodexAgentValidator, Path, Path]:
    project = tmp_path / "project"
    (project / "hyperframes").mkdir(parents=True)
    (project / "artifacts").mkdir()
    (project / "hyperframes" / "index.html").write_text("<main>fixture composition</main>")
    video = project / "fixture.mp4"
    video.write_bytes(b"fixture video bytes")
    metadata = project / "metadata.json"
    metadata.write_text("{}")
    validator = CodexAgentValidator(project, strict_mode=True, review_transport=transport)
    validator._extract_frames = lambda video_path, frame_dir: [Path(frame_dir) / "frame.png"]
    return validator, video, metadata


def test_reviewer_injected_transport_uses_actual_parser_and_labels_test_transport(tmp_path):
    validator, video, metadata = _reviewer(tmp_path, lambda *args, **kwargs: _completed(_review_payload()))
    results = validator._execute_cli_review("fixture-agent", video, metadata)
    assert len(results) == 4
    assert all(result.passed for result in results)
    assert all(result.details["review_mode"] == "offline_transport" for result in results)
    assert all(result.details["test_only_transport"] is True for result in results)
    assert all(result.details["reviewer"] == "offline_test_transport" for result in results)


def test_reviewer_injected_rejection_nonzero_malformed_and_timeout_are_not_passes(tmp_path):
    responses = [
        _completed(_review_payload(overall=False)),
        _completed('{"visual_quality": {}}'),
        _completed(_review_payload(), returncode=3),
    ]
    for index, response in enumerate(responses):
        validator, video, metadata = _reviewer(tmp_path / str(index), lambda *args, _response=response, **kwargs: _response)
        if index == 0:
            results = validator._execute_cli_review("fixture-agent", video, metadata)
            assert any(not result.passed for result in results)
        else:
            with pytest.raises((RuntimeError, ValueError)):
                validator._execute_cli_review("fixture-agent", video, metadata)

    validator, video, metadata = _reviewer(tmp_path / "timeout", lambda *args, **kwargs: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    ))
    with pytest.raises(subprocess.TimeoutExpired):
        validator._execute_cli_review("fixture-agent", video, metadata)


def _assert_public_review_does_not_discover_or_launch_agent(monkeypatch, validator):
    import scripts.codex_agent_validation as validation_module

    monkeypatch.setattr(validation_module, "resolve_agent_cli", lambda: pytest.fail("agent discovery must be skipped"))
    monkeypatch.setattr(validation_module, "_probe_audio_streams", lambda path: "fixture audio metadata")
    monkeypatch.setattr(validation_module.subprocess, "run", lambda *args, **kwargs: pytest.fail("subprocess must not run"))


def test_public_strict_review_uses_injected_transport_after_strict_frame_checks(tmp_path, monkeypatch):
    calls = []

    def transport(command, **kwargs):
        calls.append((command, kwargs))
        return _completed(_review_payload())

    validator, video, metadata = _reviewer(tmp_path, transport)
    _assert_public_review_does_not_discover_or_launch_agent(monkeypatch, validator)
    results = validator.codex_agent_strict_review(video, metadata)

    assert len(results) == 4
    assert all(result.passed for result in results)
    assert calls and calls[0][0][0] == "offline_test_transport"
    assert all(result.details["review_mode"] == "offline_transport" for result in results)
    assert all(result.details["test_only_transport"] is True for result in results)


@pytest.mark.parametrize(
    "response",
    [
        _completed('{"visual_quality": {}}'),
        _completed(_review_payload(), returncode=9),
    ],
)
def test_public_strict_review_malformed_or_nonzero_fails_without_cli(tmp_path, monkeypatch, response):
    validator, video, metadata = _reviewer(tmp_path, lambda *args, **kwargs: response)
    _assert_public_review_does_not_discover_or_launch_agent(monkeypatch, validator)

    results = validator.codex_agent_strict_review(video, metadata)

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].details["review_mode"] == "offline_transport"
    assert results[0].details["test_only_transport"] is True


def test_public_strict_review_timeout_fails_without_cli(tmp_path, monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    validator, video, metadata = _reviewer(tmp_path, timeout)
    _assert_public_review_does_not_discover_or_launch_agent(monkeypatch, validator)

    results = validator.codex_agent_strict_review(video, metadata)

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].details["error_type"] == "TimeoutExpired"
    assert results[0].details["review_mode"] == "offline_transport"
    assert results[0].details["test_only_transport"] is True


@pytest.mark.parametrize("production_flag", ["PRODUCTION_RELEASE", "STRICT_PRODUCTION"])
def test_public_strict_review_rejects_injected_transport_in_production(tmp_path, monkeypatch, production_flag):
    monkeypatch.setenv(production_flag, "1")
    validator, video, metadata = _reviewer(tmp_path, lambda *args, **kwargs: pytest.fail("transport must not run"))

    results = validator.codex_agent_strict_review(video, metadata)

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].details["error"] == "test_transport_forbidden_in_production"
    assert results[0].details["test_only_transport"] is True


def test_production_default_keeps_subprocess_transports_unset(tmp_path):
    assert CodexNewsSelector()._transport is None
    assert CodexAgentValidator(tmp_path)._review_transport is None
