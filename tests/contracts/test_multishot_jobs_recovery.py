"""Durable lifecycle tests: real local media, fresh processes, offline HTTP only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dataclasses import replace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.multishot_jobs import (
    FakeProvider, JobScheduler, JobSpec, ProviderError, file_hash,
)
from lib.multishot_provider import KlingOfficialProvider
from tools._kling.client import KlingClient


def spec(shot_id="shot_001", **kwargs):
    return JobSpec(shot_id, "A cat walks across a kitchen.",
                   "sha256:" + hashlib.sha256(b"A cat walks across a kitchen.").hexdigest(),
                   duration_sec=1, cost_reservation_id="reservation-one", **kwargs)


def scheduler(provider, root, **kwargs):
    return JobScheduler(provider, state_dir=root / "state", dest_dir=str(root / "output"),
                        poll_interval=0, base_delay=0, sleep=lambda delay: None, **kwargs)


@pytest.fixture
def video(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real recovery acceptance requires ffmpeg and ffprobe")
    path = tmp_path / "fixture.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=64x64:r=10:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
    return path


class FixtureProvider(FakeProvider):
    def __init__(self, video, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.video = video
        self.downloads = []

    def download(self, handle, dest_dir):
        self.downloads.append(handle)
        path = Path(dest_dir) / "clip.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.video, path)
        return str(path)


def test_running_handle_survives_new_scheduler(tmp_path, video):
    provider = FixtureProvider(video, {("shot_001", 1): "slow"})
    first = scheduler(provider, tmp_path, max_polls=1).run_one(spec())
    assert first.status == "running"
    assert first.provider_job_id
    provider._script.clear()
    second = scheduler(provider, tmp_path, max_polls=1).run_one(spec())
    assert second.status == "completed"
    assert second.validation["decode_ok"]
    assert provider.submissions_for("shot_001") == [1]
    assert second.cost_reservation_id == "reservation-one"


def test_unverified_resume_is_not_completed(tmp_path, video):
    result = scheduler(FakeProvider(), tmp_path).run_all(
        [spec()], resume={"shot_001": {"file_path": str(video)}})
    assert result[0].status != "completed"


@pytest.mark.parametrize("damage", ["missing_content_hash", "missing_input_hash", "missing_validation"])
def test_resume_rechecks_ledger_corruption(tmp_path, video, damage):
    provider = FixtureProvider(video)
    first = scheduler(provider, tmp_path).run_one(spec())

    ledger_path = tmp_path / "state/jobs.json"
    data = json.loads(ledger_path.read_text())
    if damage == "missing_content_hash":
        data["jobs"]["shot_001-r1"]["content_hash"] = None
    elif damage == "missing_input_hash":
        data["jobs"]["shot_001-r1"]["input_hash"] = "sha256:changed"
    elif damage == "missing_validation":
        data["jobs"]["shot_001-r1"]["validation"] = None
    ledger_path.write_text(json.dumps(data))

    second = scheduler(provider, tmp_path).run_one(spec())

    if damage == "missing_input_hash":
        assert second.status == "blocked"
        assert second.error_code == "STALE_INPUT"
    else:
        assert second.status == "completed"
        assert second.content_hash == file_hash(video)
        assert len(provider.downloads) == 2
        assert len(provider.submissions) == 1

@pytest.mark.parametrize("damage", ["missing", "corrupt", "different-valid", "report"])
def test_resume_rechecks_hash_and_actual_file(tmp_path, video, damage):
    provider = FixtureProvider(video)
    first = scheduler(provider, tmp_path).run_one(spec())
    path = Path(first.file_path)
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"nonempty but not a video")
    elif damage == "different-valid":
        # The appended bytes leave the MP4 decodable but change its digest.
        with path.open("ab") as stream:
            stream.write(b"changed")
    else:
        ledger_path = tmp_path / "state/jobs.json"
        data = json.loads(ledger_path.read_text())
        data["jobs"]["shot_001-r1"]["validation"]["valid"] = False
        ledger_path.write_text(json.dumps(data))

    # Reloading to make sure it reads the modified jobs.json from disk
    second = scheduler(provider, tmp_path).run_one(spec())

    assert second.status == "completed"
    assert second.content_hash == file_hash(video)
    assert len(provider.downloads) == 2
    assert provider.submissions_for("shot_001") == [1]
    assert len(second.attempts) == 1


def test_valid_resume_reprobes_and_does_not_download(tmp_path, video, monkeypatch):
    provider = FixtureProvider(video)
    scheduler(provider, tmp_path).run_one(spec())
    import lib.multishot_jobs as media_jobs

    # Python closures over lists work natively. Let's make an explicit object to be 100% sure.
    class CallTracker:
        def __init__(self):
            self.calls = []

    tracker = CallTracker()
    original = media_jobs.validate_download
    def probe(path, sp):
        tracker.calls.append(path)
        return original(path, sp)

    monkeypatch.setattr(media_jobs, "validate_download", probe)

    # Wait, 'validate_download' in lib.multishot_jobs is right.
    # But if JobScheduler was imported before, it's bound.
    # JobScheduler takes download_validator keyword!

    outcome = JobScheduler(provider, dest_dir=str(tmp_path), state_dir=tmp_path / "state",
                        poll_interval=0, base_delay=0, sleep=lambda delay: None, download_validator=probe).run_one(spec())

    assert outcome.status == "completed"
    assert len(tracker.calls) == 1
    assert len(provider.downloads) == 1
    assert len(provider.submissions) == 1


def test_production_rejects_fake_bytes(tmp_path):
    provider = FakeProvider()
    result = scheduler(provider, tmp_path, max_attempts=2).run_one(spec())
    assert result.status == "failed"
    assert result.error_code == "CORRUPT_OUTPUT"
    assert provider.submissions_for("shot_001") == [1]
    record = scheduler(provider, tmp_path).get_record(spec())
    assert record["status"] == "DOWNLOADING"
    assert sum(t["status"] == "DOWNLOAD_STARTED" for t in record["transitions"]) == 2


@pytest.mark.parametrize("change", [dict(prompt="different"), dict(duration_sec=2),
                                   dict(model="different"), dict(settings={"mode": "pro"}),
                                   dict(reference_hashes=["sha256:changed"])])
def test_changed_inputs_cannot_reuse_or_resubmit_same_revision(tmp_path, video, change):
    provider = FixtureProvider(video)
    original = spec()
    scheduler(provider, tmp_path).run_one(original)
    outcome = scheduler(provider, tmp_path).run_one(replace(original, **change))
    assert outcome.status == "blocked"
    assert outcome.error_code == "STALE_INPUT"
    assert len(provider.submissions) == 1


def test_explicit_revision_preserves_prior_record_and_asset(tmp_path, video):
    provider = FixtureProvider(video)
    old = scheduler(provider, tmp_path).run_one(spec())
    new_spec = replace(spec(), revision=2, prompt="changed")
    new = scheduler(provider, tmp_path).run_one(new_spec)
    assert new.status == "completed"
    assert new.file_path != old.file_path
    assert Path(old.file_path).exists()
    assert scheduler(provider, tmp_path).get_record(spec())["status"] == "COMPLETED"


def test_twenty_jobs_bound_remote_lifetime_not_poll_threads(tmp_path, video):
    class Delayed(FixtureProvider):
        counts = {}
        completed = []
        def poll(self, handle):
            self.counts[handle] = self.counts.get(handle, 0) + 1
            shot_id, _ = self._parse_handle(handle)
            required = {0: 3, 1: 4, 2: 2}[int(shot_id[-3:]) % 3]
            if self.counts[handle] < required:
                return "running"
            self.completed.append(shot_id)
            return super().poll(handle)
    provider = Delayed(video)
    specs = [spec(f"shot_{i:03}") for i in range(1, 21)]
    outcomes = scheduler(provider, tmp_path, max_concurrency=3).run_all(specs)
    assert all(o.status == "completed" for o in outcomes)
    assert [o.shot_id for o in outcomes] == [s.shot_id for s in specs]
    assert provider.peak_concurrent() == 3
    assert len(provider.submissions) == 20
    assert provider.completed != [s.shot_id for s in specs]


def test_running_jobs_retain_capacity_across_calls_and_restart(tmp_path, video):
    provider = FixtureProvider(video, {(f"shot_{i:03}", 1): "slow" for i in range(1, 5)})
    first = scheduler(provider, tmp_path, max_polls=2, max_concurrency=3).run_all(
        [spec(f"shot_{i:03}") for i in range(1, 5)])
    assert [o.status for o in first] == ["running", "running", "running", "blocked"]
    second = scheduler(provider, tmp_path, max_polls=2, max_concurrency=3).run_one(spec("shot_004"))
    assert second.status == "blocked"
    assert provider.submissions_for("shot_004") == []
    assert provider.peak_concurrent() == 3


@pytest.mark.parametrize("code", ["RATE_LIMIT", "PROVIDER_5XX", "TIMEOUT"])
def test_transient_poll_errors_never_resubmit(tmp_path, video, code):
    class Flaky(FixtureProvider):
        calls = 0
        def poll(self, handle):
            self.calls += 1
            if self.calls < 3:
                raise ProviderError(code)
            return super().poll(handle)
    provider = Flaky(video)
    outcome = scheduler(provider, tmp_path).run_one(spec())
    assert outcome.status == "completed"
    assert provider.calls == 3
    assert len(outcome.attempts) == 1
    assert len(provider.submissions) == 1


def test_poll_auth_stops_without_releasing_remote_slot(tmp_path, video):
    class Auth(FixtureProvider):
        calls = 0
        def poll(self, handle):
            self.calls += 1
            raise ProviderError("AUTH_ERROR")
    provider = Auth(video)
    outcome = scheduler(provider, tmp_path).run_one(spec())
    assert outcome.status == "running"
    assert outcome.error_code == "AUTH_ERROR"
    assert provider.calls == 1
    assert outcome.provider_job_id


def test_unknown_submission_fails_closed_and_keeps_capacity(tmp_path):
    class Lost(FakeProvider):
        calls = 0
        def submit(self, spec, attempt, key):
            self.calls += 1
            raise TimeoutError("https://secret.example/?token=DO_NOT_LOG")
    provider = Lost()
    first = scheduler(provider, tmp_path, max_concurrency=1).run_one(spec())
    second = scheduler(provider, tmp_path, max_concurrency=1).run_one(spec())
    third = scheduler(provider, tmp_path, max_concurrency=1).run_one(spec("shot_002"))
    assert first.status == second.status == "submission_unknown"
    assert third.status == "blocked"
    assert provider.calls == 1
    assert "DO_NOT_LOG" not in (tmp_path / "state/jobs.json").read_text()


def test_eligibility_blocks_dispatch_and_reuse(tmp_path, video):
    provider = FixtureProvider(video)
    sched = scheduler(provider, tmp_path, eligibility=lambda s: False)
    assert sched.run_one(spec()).error_code == "INELIGIBLE"
    assert not provider.submissions
    scheduler(provider, tmp_path).run_one(spec())
    assert sched.run_one(spec()).error_code == "INELIGIBLE"
    assert len(provider.submissions) == 1


def test_corrupt_ledger_fails_closed(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "jobs.json").write_text('{"broken": true}')
    provider = FakeProvider()
    with pytest.raises(ValueError):
        scheduler(provider, tmp_path).run_one(spec())
    assert not provider.submissions


# This simulated remote service is separate from scheduler state and survives a
# hard process exit. Recovery must discover its persisted correlation/handle,
# not be handed a fabricated resume_handle by the test.
class DiskRemote(FakeProvider):
    def __init__(self, root, crash):
        super().__init__()
        self.root, self.crash = root, crash
        self.server = root / "remote.json"

    def submit(self, spec, attempt, key):
        data = json.loads(self.server.read_text()) if self.server.exists() else {}
        data[key] = f"handle-{spec.shot_id}-{attempt}"
        self.server.write_text(json.dumps(data))
        if self.crash == "after_submit":
            os._exit(73)
        return data[key]

    def reconcile(self, spec, key):
        data = json.loads(self.server.read_text()) if self.server.exists() else {}
        return data.get(key)

    def download(self, handle, dest_dir):
        target = Path(dest_dir) / "output.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.crash == "partial_download":
            target.with_suffix(".part").write_bytes(b"partial")
            os._exit(73)
        shutil.copyfile(self.root / "fixture.mp4", target)
        return str(target)


def worker(root, crash):
    provider = DiskRemote(root, crash)
    sched = scheduler(provider, root)
    save = sched._save
    def crash_save():
        save()
        statuses = [r["status"] for r in sched._records.values()]
        if ((crash == "after_intent" and "INTENT" in statuses)
                or (crash == "after_handle" and "SUBMITTED" in statuses)):
            os._exit(73)
    sched._save = crash_save
    result = sched.run_one(spec())
    (root / "result.json").write_text(json.dumps(result.to_dict()))


@pytest.mark.parametrize("crash", ["after_intent", "after_submit", "after_handle", "partial_download"])
def test_fresh_process_crash_recovery(tmp_path, video, crash):
    command = [sys.executable, str(Path(__file__).resolve()), "worker", str(tmp_path)]
    first = subprocess.run([*command, crash], cwd=ROOT, capture_output=True, timeout=30)
    assert first.returncode == 73, first.stderr.decode()
    prior = json.loads((tmp_path / "state/jobs.json").read_text())["jobs"]["shot_001-r1"]
    second = subprocess.run([*command, "none"], cwd=ROOT, capture_output=True, timeout=30)
    assert second.returncode == 0, second.stderr.decode()
    result = json.loads((tmp_path / "result.json").read_text())
    expected = "submission_unknown" if crash == "after_intent" else "completed"
    assert result["status"] == expected
    assert result["idempotency_key"] == prior["idempotency_key"]
    assert result["cost_reservation_id"] == prior["cost_reservation_id"] == "reservation-one"
    assert len(result["attempts"]) == 1
    remote = tmp_path / "remote.json"
    assert (len(json.loads(remote.read_text())) if remote.exists() else 0) == (0 if crash == "after_intent" else 1)
    if expected == "completed":
        assert result["content_hash"] == file_hash(video)
        assert result["validation"]["decode_ok"]
    if crash == "partial_download":
        record = scheduler(DiskRemote(tmp_path, "none"), tmp_path).get_record(spec())
        assert sum(t["status"] == "DOWNLOAD_STARTED" for t in record["transitions"]) == 2


class Response:
    def __init__(self, body, status=200, content=b""):
        self.body, self.status_code, self.content = body, status, content
    def json(self):
        return self.body


class Transport:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
    def _call(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    def post(self, url, **kwargs):
        return self._call("post", url, kwargs)
    def get(self, url, **kwargs):
        return self._call("get", url, kwargs)


def adapter(transport):
    return KlingOfficialProvider(client=KlingClient(api_key="offline-test-key", session=transport))


def kling_spec(**kwargs):
    return replace(spec(provider="kling_official", model="kling-v3"), duration_sec=5, **kwargs)


def test_real_adapter_payload_status_download_and_no_secret_handle(tmp_path, video):
    from PIL import Image
    reference = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), "red").save(reference)
    ref_hash = file_hash(reference)
    signed = "https://cdn.example/video.mp4?token=secret-result"
    completed = Response({"code": 0, "data": {"task_status": "succeed", "task_result": {
        "videos": [{"url": signed}]}}})
    transport = Transport([
        Response({"code": 0, "data": {"task_id": "remote-123"}}),
        Response({"code": 0, "data": {"task_status": "processing"}}), completed,
        completed, Response({}, content=video.read_bytes()),
    ])
    provider = adapter(transport)
    job = kling_spec(references=[{"path": str(reference), "sha256": ref_hash, "role": "first_frame"}],
                     reference_hashes=[ref_hash], settings={"mode": "pro", "sound": "off"})
    handle = provider.submit(job, 1, "stable-key")
    payload = transport.calls[0][2]["json"]
    assert payload["prompt"] == job.prompt
    assert payload["model_name"] == "kling-v3"
    assert payload["duration"] == "5"
    assert payload["mode"] == "pro"
    assert payload["external_task_id"] == "stable-key"
    assert payload["image"]
    assert provider.client.max_retries == 0
    assert provider.poll(handle) == "running"
    assert provider.poll(handle) == "completed"
    assert file_hash(provider.download(handle, str(tmp_path / "download"))) == file_hash(video)
    assert "secret" not in handle and "http" not in handle
    assert "headers" not in transport.calls[-1][2]  # No API key on CDN request.
    assert sum(c[0] == "post" for c in transport.calls) == 1


@pytest.mark.parametrize("body,http,code,rejected", [
    ({"code": 1302}, 200, "RATE_LIMIT", True),
    ({}, 429, "RATE_LIMIT", True),
    ({"code": 5001}, 200, "PROVIDER_5XX", False),
    ({}, 503, "PROVIDER_5XX", False),
    ({"code": 1001}, 200, "AUTH_ERROR", True),
    ({}, 401, "AUTH_ERROR", True),
    ({"code": 1301}, 200, "SAFETY_REFUSAL", True),
    ({"code": 1101}, 200, "QUOTA_EXCEEDED", True),
    ({"code": 1200}, 200, "INVALID_INPUT", True),
])
def test_adapter_error_mapping_never_retries_post(body, http, code, rejected):
    transport = Transport([Response(body, http)])
    with pytest.raises(ProviderError) as error:
        adapter(transport).submit(kling_spec(), 1, "key")
    assert error.value.code == code
    assert error.value.rejected == rejected
    assert len(transport.calls) == 1


def test_adapter_unknown_response_requires_reconciliation(tmp_path):
    transport = Transport([Response({"code": 0, "data": {}})])
    first = scheduler(adapter(transport), tmp_path).run_one(kling_spec())
    second = scheduler(adapter(transport), tmp_path).run_one(kling_spec())
    assert first.status == second.status == "submission_unknown"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("settings", [{"api_family": "turbo"}, {"resolution": "4k"},
                                      {"unknown": True}, {"mode": "invalid"}])
def test_unsupported_provider_settings_rejected_before_transport(settings):
    transport = Transport([])
    with pytest.raises(ProviderError) as error:
        adapter(transport).submit(kling_spec(settings=settings), 1, "key")
    assert error.value.code == "INVALID_INPUT"
    assert error.value.rejected
    assert not transport.calls


def test_real_adapter_scheduler_retries_rejection_and_download_not_generation(tmp_path, video):
    five_seconds = tmp_path / "five.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "4", "-i", str(video),
                    "-t", "5", "-c", "copy", str(five_seconds)], check=True, timeout=30)
    complete = Response({"code": 0, "data": {"task_status": "succeed", "task_result": {
        "videos": [{"url": "https://cdn.example/output?token=PRIVATE"}]}}})
    transport = Transport([
        Response({"code": 1302}, 429),
        Response({"code": 0, "data": {"task_id": "accepted-1"}}),
        Response({"code": 0, "data": {"task_status": "processing"}}), complete,
        complete, Response({}, 503),
        complete, Response({}, content=five_seconds.read_bytes()),
    ])
    provider = adapter(transport)
    outcome = scheduler(provider, tmp_path).run_one(kling_spec())
    assert outcome.status == "completed"
    assert outcome.validation["decode_ok"]
    assert [a.status for a in outcome.attempts] == ["failed", "completed"]
    assert outcome.attempts[0].error_code == "RATE_LIMIT"
    posts = [c for c in transport.calls if c[0] == "post"]
    assert len(posts) == 2  # Rejected request + exactly one accepted generation.
    assert posts[0][2]["json"]["external_task_id"] != posts[1][2]["json"]["external_task_id"]
    assert "PRIVATE" not in (tmp_path / "state/jobs.json").read_text()
    assert "offline-test-key" not in (tmp_path / "state/jobs.json").read_text()
    reloaded = scheduler(provider, tmp_path).run_one(kling_spec())
    assert reloaded.status == "completed"
    assert reloaded.to_dict() == outcome.to_dict()
    assert not transport.replies


def test_real_adapter_transport_timeout_no_automatic_retry(tmp_path):
    import requests
    transport = Transport([requests.Timeout("signed URL or API secret")])
    result = scheduler(adapter(transport), tmp_path).run_one(kling_spec())
    assert result.status == "submission_unknown"
    assert len(transport.calls) == 1
    assert "API secret" not in (tmp_path / "state/jobs.json").read_text()


@pytest.mark.parametrize("code,expected", [(1301, "SAFETY_REFUSAL"), (1101, "QUOTA_EXCEEDED"),
                                          (None, "JOB_FAILED")])
def test_adapter_terminal_failure_mapping(code, expected):
    transport = Transport([Response({"code": 0, "data": {
        "task_status": "failed", "task_status_code": code}})])
    handle = json.dumps({"path": "/v1/videos/text2video", "task_id": "known"})
    with pytest.raises(ProviderError) as error:
        adapter(transport).poll(handle)
    assert error.value.terminal
    assert error.value.code == expected


def test_forged_success_report_cannot_make_junk_valid(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"nonempty junk")
    inputs, digest = spec().fingerprint(), file_hash(junk)
    result = scheduler(FakeProvider(script={("shot_001", 1): "ok", ("shot_001", "download"): "ok"}), tmp_path).run_all([spec()], resume={"shot_001": {
        "file_path": str(junk), "input_hash": inputs, "content_hash": digest,
        "validation": {"valid": True, "input_hash": inputs, "content_hash": digest},
    }})[0]
    import sys
    print("TEST FORGED SUCCESS OUTPUT:", result, file=sys.stderr)
    assert result.status == "failed"
    assert result.error_code == "CORRUPT_OUTPUT"


def test_two_schedulers_cannot_submit_under_same_ledger_lock(tmp_path, video):
    class Competing(FixtureProvider):
        def submit(self, job, attempt, key):
            with pytest.raises(OSError):
                scheduler(FakeProvider(), tmp_path).run_one(spec("shot_002"))
            return super().submit(job, attempt, key)
    provider = Competing(video)
    assert scheduler(provider, tmp_path).run_one(spec()).status == "completed"
    assert len(provider.submissions) == 1


@pytest.mark.parametrize("kwargs", [{"max_polls": float("inf")}, {"max_concurrency": 1.5},
                                   {"max_attempts": 0}, {"deadline_seconds": float("inf")}])
def test_unbounded_configuration_rejected(tmp_path, kwargs):
    with pytest.raises(ValueError):
        scheduler(FakeProvider(), tmp_path, **kwargs)


def test_reference_content_change_prevents_dispatch(tmp_path):
    from PIL import Image
    path = tmp_path / "ref.png"
    Image.new("RGB", (16, 16), "red").save(path)
    digest = file_hash(path)
    job = kling_spec(references=[{"path": str(path), "sha256": digest}], reference_hashes=[digest])
    Image.new("RGB", (16, 16), "blue").save(path)
    transport = Transport([])
    with pytest.raises(ValueError):
        scheduler(adapter(transport), tmp_path).run_one(job)
    assert not transport.calls


@pytest.mark.parametrize("url", ["http://cdn.example/video", "https://127.0.0.1/video",
                                 "https://localhost/video", "https://user:password@cdn.example/video"])
def test_adapter_rejects_unsafe_download_url_before_get(tmp_path, url):
    transport = Transport([Response({"data": {"task_status": "succeed", "task_result": {
        "videos": [{"url": url}]}}})])
    provider = adapter(transport)
    handle = json.dumps({"path": "/v1/videos/text2video", "task_id": "known"})
    with pytest.raises(ProviderError):
        provider.download(handle, str(tmp_path))
    assert len(transport.calls) == 1  # Status lookup only, no unsafe download.


def test_adapter_bounds_download_bytes_and_removes_partial(tmp_path):
    complete = Response({"data": {"task_status": "succeed", "task_result": {
        "videos": [{"url": "https://cdn.example/video"}]}}})
    transport = Transport([complete, Response({}, content=b"too large")])
    provider = KlingOfficialProvider(client=KlingClient(api_key="test", session=transport),
                                     max_download_bytes=2)
    handle = json.dumps({"path": "/v1/videos/text2video", "task_id": "known"})
    with pytest.raises(ProviderError):
        provider.download(handle, str(tmp_path))
    assert not (tmp_path / "output.mp4").exists()
    assert not (tmp_path / "output.mp4.part").exists()
    assert transport.calls[-1][2]["allow_redirects"] is False


if __name__ == "__main__" and sys.argv[1] == "worker":
    worker(Path(sys.argv[2]), sys.argv[3])
