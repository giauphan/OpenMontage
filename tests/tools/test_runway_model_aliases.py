"""Tests for Runway model aliases and capability consistency."""

from __future__ import annotations

import pytest

from tools.video.runway_video import RunwayVideo, _DEFAULT_MODEL


def test_runway_accepts_official_and_legacy_models():
    tool = RunwayVideo()
    models = tool.input_schema["properties"]["model"]["enum"]

    # Official identifiers
    assert "seedance2" in models
    assert "seedance2_fast" in models
    assert "gen4.5" in models
    assert "gen4_turbo" in models

    # Legacy identifiers
    assert "seedance_2.0" in models
    assert "seedance_2.0_fast" in models


def test_runway_model_cost_and_runtime_estimates():
    tool = RunwayVideo()

    # Seedance 2.0 and seedance2 parity
    cost_legacy = tool.estimate_cost({"model": "seedance_2.0", "duration": 5})
    cost_official = tool.estimate_cost({"model": "seedance2", "duration": 5})
    assert cost_legacy == pytest.approx(cost_official)

    # gen4.5 estimate
    cost_gen45 = tool.estimate_cost({"model": "gen4.5", "duration": 5})
    assert cost_gen45 == pytest.approx(0.12 * 5)


def test_runway_payload_uses_exact_model_identifier(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNWAY_API_KEY", "test-key")
    posted = {}

    class JsonResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class DownloadResponse:
        content = b"fake-video"

        def raise_for_status(self):
            return None

    def fake_post(url, *, headers, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return JsonResponse({"id": "task-1"})

    def fake_get(url, *, headers=None, timeout):
        if url == "https://example.invalid/out.mp4":
            return DownloadResponse()
        return JsonResponse({"status": "SUCCEEDED", "output": ["https://example.invalid/out.mp4"]})

    import requests
    import tools.video._shared as shared

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr(shared, "probe_output", lambda _: {"duration_sec": 5.0, "width": 1280, "height": 720})

    output_path = tmp_path / "runway-test.mp4"
    result = RunwayVideo().execute({
        "prompt": "A fox waves.",
        "model": "gen4.5",
        "duration": 5,
        "output_path": str(output_path),
    })

    assert posted["json"]["model"] == "gen4.5"
    assert result.success is True
    assert output_path.read_bytes() == b"fake-video"
