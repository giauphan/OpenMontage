"""Contract tests for OpenMontage multishot gateway provider adapter."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib.multishot_generation import prepare_generation
from lib.multishot_gateway_provider import GatewayVideoProvider
from lib.multishot_jobs import JobScheduler, JobSpec, ProviderError
from tests.contracts.test_multishot_generation_execution import _setup


class FakeGatewayTransport:
    def __init__(self):
        self.calls = []
        self.status = "completed"
        self.body = {
            "id": "video-gateway-001",
            "status": "completed",
            "video_url": "https://cdn.example.test/video.mp4",
        }

    def post_json(self, path: str, payload: dict, headers: dict) -> dict:
        self.calls.append(("post", path, payload, headers))
        return dict(self.body)

    def get_json(self, path: str, headers: dict) -> dict:
        self.calls.append(("get", path, headers))
        return {"id": "video-gateway-001", "status": self.status}

    def download(self, url: str, dest: Path) -> None:
        self.calls.append(("download", url, dest.name))
        dest.write_bytes(b"gateway-video-bytes")


def _spec() -> JobSpec:
    return JobSpec(
        shot_id="shot_001",
        prompt="bright cartoon fox waves at camera",
        prompt_hash="sha256:" + "1" * 64,
        reference_hashes=["sha256:" + "2" * 64],
        provider="gateway",
        model="muse-video",
        duration_sec=5,
        settings={"aspect_ratio": "16:9"},
        references=[{"id": "ref1", "role": "character_master", "sha256": "sha256:" + "2" * 64}],
        revision=1,
    )


def test_gateway_provider_submit_poll_download_contract(tmp_path: Path):
    transport = FakeGatewayTransport()
    provider = GatewayVideoProvider(base_url="http://gateway.local", transport=transport)
    spec = _spec()

    handle = provider.submit(spec, attempt=1, idempotency_key="idem-1")
    assert handle == "gw:video-gateway-001"
    assert transport.calls[0][1] == "/muse-ai/v1/create-video"
    payload = transport.calls[0][2]
    assert payload["prompt"] == spec.prompt
    assert payload["model"] == "muse-video"
    assert payload["duration"] == 5
    assert payload["aspect_ratio"] == "16:9"
    assert transport.calls[0][3]["Idempotency-Key"] == "idem-1"

    assert provider.poll(handle) == "completed"
    out = provider.download(handle, str(tmp_path))
    assert Path(out).read_bytes() == b"gateway-video-bytes"


def test_gateway_provider_submission_transport_errors_become_unknown():
    class BrokenTransport(FakeGatewayTransport):
        def post_json(self, path: str, payload: dict, headers: dict) -> dict:
            raise TimeoutError("network interrupted after submit")

    provider = GatewayVideoProvider(base_url="http://gateway.local", transport=BrokenTransport())
    with pytest.raises(ProviderError) as exc:
        provider.submit(_spec(), attempt=1, idempotency_key="idem-1")
    assert exc.value.code == "SUBMISSION_UNKNOWN"
    assert exc.value.rejected is False
    assert exc.value.terminal is False


def test_gateway_provider_reconcile_uses_idempotency_lookup():
    class ReconcilingTransport(FakeGatewayTransport):
        def get_json(self, path: str, headers: dict) -> dict:
            self.calls.append(("get", path, headers))
            return {"id": "video-gateway-001", "status": "completed"}

    transport = ReconcilingTransport()
    provider = GatewayVideoProvider(base_url="http://gateway.local", transport=transport)
    assert provider.reconcile(_spec(), "idem-1") == "gw:video-gateway-001"
    assert transport.calls[0][1] == "/muse-ai/v1/create-video/idem-1"


def test_prepare_generation_accepts_gateway_provider(tmp_path: Path):
    _, shot_id, store, review = _setup(tmp_path)
    spec = prepare_generation(
        project_dir=tmp_path,
        shot_id=shot_id,
        provider="gateway",
        model="muse-video",
        settings={"aspect_ratio": "16:9"},
        spend_approved=True,
        budget_usd=10.0,
        estimated_usd=1.0,
        reference_store=store,
        reference_review=review,
    )
    assert spec.provider == "gateway"
    assert spec.model == "muse-video"


def test_gateway_unknown_submission_is_durable_and_reconciled(tmp_path: Path):
    spec = _spec()
    state_dir = tmp_path / "state"
    output_dir = tmp_path / "outputs"

    class UnknownOnce(FakeGatewayTransport):
        def __init__(self):
            super().__init__()
            self.submits = 0

        def post_json(self, path: str, payload: dict, headers: dict) -> dict:
            self.submits += 1
            raise TimeoutError("lost response")

        def get_json(self, path: str, headers: dict) -> dict:
            return {"id": "video-gateway-001", "status": "completed", "video_url": "https://cdn.example.test/video.mp4"}

    transport = UnknownOnce()
    provider = GatewayVideoProvider(base_url="http://gateway.local", transport=transport)
    validator = lambda path, spec: {"valid": True}
    runner = JobScheduler(provider, state_dir=state_dir, dest_dir=output_dir, max_attempts=1, poll_interval=0, download_validator=validator)
    result = runner.run_one(spec)
    assert result.status == "submission_unknown"
    assert transport.submits == 1

    recovered = JobScheduler(provider, state_dir=state_dir, dest_dir=output_dir, max_attempts=1, poll_interval=0, download_validator=validator).run_one(spec)
    assert recovered.status == "completed"
    assert transport.submits == 1
