"""Provider-neutral, durable multi-shot jobs (technical lifecycle, not creative policy).

``state_dir`` opts into crash recovery. One ledger owns the remote concurrency
budget; use the same directory for every caller sharing that budget. A process
lock prevents competing writers, including after a crash. Unknown submissions
occupy a slot until reconciled; a timeout is never permission to resubmit.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from lib.multishot_schemas import MultishotValidationError

ERROR_CODES = frozenset({
    "AUTH_ERROR", "RATE_LIMIT", "QUOTA_EXCEEDED", "INVALID_INPUT",
    "SAFETY_REFUSAL", "PROVIDER_5XX", "TIMEOUT", "JOB_FAILED",
    "DOWNLOAD_FAILED", "CORRUPT_OUTPUT", "UNKNOWN_PROVIDER_ERROR",
    "SUBMISSION_UNKNOWN", "STALE_INPUT", "INELIGIBLE", "CAPACITY",
})
RETRYABLE_ERRORS = frozenset({
    "RATE_LIMIT", "PROVIDER_5XX", "TIMEOUT", "DOWNLOAD_FAILED", "JOB_FAILED",
})
PERMANENT_ERRORS = frozenset({
    "AUTH_ERROR", "QUOTA_EXCEEDED", "INVALID_INPUT", "SAFETY_REFUSAL",
})
_ACTIVE = {"INTENT", "SUBMISSION_UNKNOWN", "SUBMITTED", "RUNNING"}
_SECRET = re.compile(r"api.?key|authorization|password|secret|token", re.I)


def is_retryable(code: Optional[str]) -> bool:
    return code in RETRYABLE_ERRORS


class ProviderError(Exception):
    """Only ``rejected`` proves no job was created; ``terminal`` proves it ended.

    Transport failures default to neither. Never infer either fact merely from
    a transient error code, especially a timeout or HTTP 5xx during submission.
    Messages are not copied to durable records or outcomes.
    """
    def __init__(self, code: str, message: str = "", *, retry_after=None,
                 rejected: bool = False, terminal: bool = False):
        super().__init__(f"{code}: {message}")
        self.code = code if code in ERROR_CODES else "UNKNOWN_PROVIDER_ERROR"
        self.message = message
        self.retry_after = retry_after
        self.rejected = rejected
        self.terminal = terminal


class VideoProvider(Protocol):
    def submit(self, spec: JobSpec, attempt: int, idempotency_key: str) -> str: ...
    def poll(self, handle: str) -> str: ...
    def download(self, handle: str, dest_dir: str) -> str: ...
    def reconcile(self, spec: JobSpec, idempotency_key: str) -> Optional[str]: ...


@dataclass
class _AttemptRecord:
    attempt: int
    started_at: float
    finished_at: float
    status: str
    error_code: Optional[str] = None


class FakeProvider:
    """Legacy scripted *terminal* outcomes; fake bytes require a test validator.

    Real transport retry behavior is tested separately: these scripted errors
    describe failed jobs, not a failed GET against a still-running remote job.
    ``submit(shot_id, attempt, prompt_hash)`` remains usable by older tests.
    """
    def __init__(self, script=None, *, sleep=time.sleep, retry_after_map=None):
        self._script = dict(script or {})
        self._sleep = sleep
        self._retry_after = dict(retry_after_map or {})
        self.submissions = []
        self._lock = threading.Lock()
        self._active = set()
        self._peak_concurrent = 0
        self._keys = {}

    def submit(self, spec, attempt: int, idempotency_key: str) -> str:
        shot_id = spec.shot_id if isinstance(spec, JobSpec) else spec
        handle = f"handle-{shot_id}-{attempt}"
        with self._lock:
            self.submissions.append((shot_id, attempt))
            self._active.add(handle)
            self._peak_concurrent = max(self._peak_concurrent, len(self._active))
            self._keys[idempotency_key] = handle
        return handle

    def reconcile(self, spec, idempotency_key):
        return self._keys.get(idempotency_key)

    def poll(self, handle: str) -> str:
        shot_id, attempt = self._parse_handle(handle)
        outcome = self._script.get((shot_id, attempt), "ok")
        if outcome == "slow":
            self._sleep(0)
            return "running"
        with self._lock:
            self._active.discard(handle)
        if outcome in ERROR_CODES:
            raise ProviderError(outcome, retry_after=self._retry_after.get((shot_id, attempt)),
                                terminal=True)
        return "completed"

    def download(self, handle: str, dest_dir: str) -> str:
        shot_id, _ = self._parse_handle(handle)
        outcome = self._script.get((shot_id, "download"), "ok")
        if outcome in ERROR_CODES:
            raise ProviderError(outcome)
        path = Path(dest_dir) / f"{shot_id}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-video-bytes")
        return str(path)

    @staticmethod
    def _parse_handle(handle):
        base, attempt = handle.rsplit("-", 1)
        return base[len("handle-"):], int(attempt)

    def peak_concurrent(self):
        return self._peak_concurrent

    def submissions_for(self, shot_id):
        return [a for s, a in self.submissions if s == shot_id]


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_input_hash(*, provider: str, model: str, settings: dict,
                         prompt: str, reference_hashes: Sequence[str]) -> str:
    # Preserve the legacy unordered-reference helper. JobSpec.input_hash also
    # binds ordered reference roles, duration and revision (all render inputs).
    return _digest(dict(provider=provider, model=model, settings=settings,
                        prompt=prompt, reference_hashes=sorted(reference_hashes)))


@dataclass
class JobSpec:
    shot_id: str
    prompt: str
    prompt_hash: str
    reference_hashes: list = field(default_factory=list)
    provider: str = "fake"
    model: str = "fake"
    duration_sec: float = 5.0
    settings: dict = field(default_factory=dict)
    references: list[dict] = field(default_factory=list)
    revision: int = 1
    input_hash: Optional[str] = None
    cost_reservation_id: Optional[str] = None
    eligible: bool = True

    def fingerprint(self) -> str:
        payload = asdict(self)
        for key in ("input_hash", "cost_reservation_id", "eligible"):
            payload.pop(key)
        return _digest(payload)

    def validate(self) -> None:
        if not re.fullmatch(r"shot_\d{3}", self.shot_id):
            raise MultishotValidationError("Invalid shot id")
        if not self.prompt.strip() or not self.provider or not self.model:
            raise MultishotValidationError("Prompt, provider and model are required")
        if (not isinstance(self.revision, int) or isinstance(self.revision, bool)
                or self.revision < 1 or not math.isfinite(self.duration_sec) or self.duration_sec <= 0):
            raise MultishotValidationError("Invalid revision or duration")
        if self.input_hash and self.input_hash != self.fingerprint():
            raise MultishotValidationError("Input hash does not match current render inputs")
        def check_settings(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if _SECRET.search(key):
                        raise MultishotValidationError("Credentials do not belong in JobSpec")
                    check_settings(item)
            elif isinstance(value, list):
                for item in value:
                    check_settings(item)
        check_settings(self.settings)
        self.fingerprint()  # Reject non-JSON/non-finite settings before intent.
        if self.references and len(self.references) != len(self.reference_hashes):
            raise MultishotValidationError("Every reference needs an ordered content hash")
        for ref, expected in zip(self.references, self.reference_hashes):
            if not isinstance(ref, dict) or ref.get("sha256") != expected:
                raise MultishotValidationError("Reference hash mismatch")
            if ref.get("path") and file_hash(ref["path"]) != expected:
                raise MultishotValidationError("Reference content changed")


@dataclass
class JobOutcome:
    shot_id: str
    status: str
    file_path: Optional[str]
    attempts: list
    error_code: Optional[str] = None
    provider_job_id: Optional[str] = None
    input_hash: Optional[str] = None
    content_hash: Optional[str] = None
    validation: Optional[dict] = None
    idempotency_key: Optional[str] = None
    cost_reservation_id: Optional[str] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["attempts"] = [dict(attempt=a.attempt, status=a.status, error_code=a.error_code)
                              for a in self.attempts]
        return result


def backoff_delay(attempt, base_delay, max_delay, *, retry_after=None, jitter=0.0):
    delay = min(max_delay, base_delay * (2 ** min(attempt - 1, 30))) + jitter
    if retry_after is not None:
        delay = max(delay, retry_after)
    return min(max_delay, delay)


def validate_download(path: Path, spec: JobSpec) -> dict:
    """Production validation: existing nonempty file, ffprobe AND full decode."""
    from lib.multishot_media import probe_clip, validate_shot_clip
    if not path.is_file() or not path.stat().st_size:
        raise MultishotValidationError("Missing or empty output")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MultishotValidationError("ffmpeg and ffprobe are required")
    report = probe_clip(path)
    errors = validate_shot_clip(report, planned_duration_sec=spec.duration_sec)
    if (errors or not report.get("decode_ok") or not report.get("has_video")
            or not report.get("duration_sec") or not report.get("fps")):
        raise MultishotValidationError("Output failed media validation")
    return {"valid": True, **report}


def _redacted(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if _SECRET.search(k) else _redacted(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redacted(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"https?://\S+", "[redacted-url]", value)
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=1)
def _job_validator():
    from jsonschema import Draft202012Validator
    from schemas.multishot import load_schema
    schema = load_schema("job")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class JobScheduler:
    """Bounded remote-job lifecycle with atomic, process-safe recovery.

    API: run_one(spec), run_all(specs), get_record(spec). ``max_polls`` and
    ``deadline_seconds`` bound each invocation, not remote lifetime. Running
    handles and unknown submissions retain slots across calls/restarts.
    ``eligibility(spec)`` is the caller's R3 continuity gate, rechecked before
    dispatch and reuse. No creative acceptance is performed here.

    ``download_validator(path, spec)`` is a trusted Python-only test seam; never
    expose it as tool input. Omit it in production. ``cost_reservation_id`` is
    supplied by the caller's pre-spend cost gate and preserved, not re-reserved.
    """
    def __init__(self, provider: VideoProvider, *, max_concurrency=3, max_attempts=3,
                 base_delay=0.1, max_delay=10.0, deadline_seconds=None, sleep=None,
                 rng=None, dest_dir=".", state_dir: Optional[Path] = None,
                 max_polls=100, poll_interval=5.0, download_validator=None,
                 eligibility: Optional[Callable[[JobSpec], bool]] = None):
        limits = (max_concurrency, max_attempts, max_polls)
        if any(not isinstance(x, int) or isinstance(x, bool) or x < 1 for x in limits):
            raise ValueError("Concurrency, attempts and polls must be positive integers")
        deadline = 900.0 if deadline_seconds is None else deadline_seconds
        if not math.isfinite(deadline) or deadline <= 0:
            raise ValueError("A finite positive deadline is required")
        if any(not math.isfinite(x) or x < 0 for x in (base_delay, max_delay, poll_interval)):
            raise ValueError("Delays must be finite and nonnegative")
        self.provider = provider
        self.max_concurrency = max_concurrency
        self.max_attempts = max_attempts
        self.base_delay, self.max_delay = base_delay, max_delay
        self.deadline_seconds = deadline
        self.max_polls, self.poll_interval = max_polls, poll_interval
        self._sleep, self._rng = sleep or time.sleep, rng or (lambda: 0.0)
        self._dest_dir = Path(dest_dir).resolve()
        self.state_dir = Path(state_dir).resolve() if state_dir is not None else None
        self._validator = download_validator or validate_download
        self._eligibility = eligibility or (lambda spec: spec.eligible)
        self._records: dict[str, dict] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(spec):
        return f"{spec.shot_id}-r{spec.revision}"

    @contextmanager
    def _exclusive(self):
        with self._lock:
            if self.state_dir is None:
                yield
                return
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with (self.state_dir / ".scheduler.lock").open("a+b") as lock:
                if os.name == "nt":
                    import msvcrt
                    lock.seek(0)
                    if not lock.read(1):
                        lock.write(b"0")
                        lock.flush()
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    path = self.state_dir / "jobs.json"
                    if path.exists():
                        data = json.loads(path.read_text(encoding="utf-8"))
                        if data.get("schema_version") != 2 or not isinstance(data.get("jobs"), dict):
                            raise MultishotValidationError("Invalid job ledger; refusing submission")
                        self._records = data["jobs"]
                        for key, record in self._records.items():
                            self._validate_record(record)
                            if key != f"{record['shot_id']}-r{record['revision']}":
                                raise MultishotValidationError("Job ledger key mismatch")
                    yield
                finally:
                    if os.name == "nt":
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _validate_record(record):
        _job_validator().validate(record)
        json.dumps(record, allow_nan=False)
        required = {"revision", "spec", "transitions", "attempts", "idempotency_key",
                    "cost_reservation_id", "file_path", "content_hash", "validation"}
        if not required.issubset(record):
            raise MultishotValidationError("Incomplete durable job record")
        if record["status"] in _ACTIVE and not record.get("provider_job_id"):
            if not record.get("idempotency_key") or not record["attempts"]:
                raise MultishotValidationError("Submission intent lost identity")
        if record["status"] in {"SUBMITTED", "RUNNING", "DOWNLOADING", "COMPLETED"}:
            if not record.get("provider_job_id") and not record.get("imported"):
                raise MultishotValidationError("Durable job has lost its handle")
        if not record.get("input_hash") or "attempts" not in record:
            raise MultishotValidationError("Incomplete recovery record")

    def _save(self):
        for record in self._records.values():
            self._validate_record(record)
        if self.state_dir is None:
            return
        path = self.state_dir / "jobs.json"
        temp = self.state_dir / f".jobs-{uuid.uuid4().hex}.tmp"
        try:
            with temp.open("x", encoding="utf-8") as stream:
                os.chmod(temp, 0o600)
                json.dump({"schema_version": 2, "jobs": self._records}, stream,
                          sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            if os.name != "nt":
                fd = os.open(self.state_dir, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            temp.unlink(missing_ok=True)

    def _transition(self, record, status, error=None):
        record.update(status=status, error_code=error, updated_at=_now())
        record["transitions"].append(dict(status=status, error_code=error, at=record["updated_at"]))
        if record["attempts"]:
            attempt = record["attempts"][-1]
            attempt.update(status=status.lower(), error_code=error)
            if status in {"FAILED", "PERMANENTLY_FAILED", "COMPLETED"}:
                attempt["finished_at"] = time.time()
        self._save()

    def _new(self, spec):
        return dict(shot_id=spec.shot_id, provider=spec.provider, model=spec.model,
                    status="PENDING", attempt=1, max_attempts=self.max_attempts,
                    submitted_at=_now(), updated_at=_now(), input_hash=spec.fingerprint(),
                    provider_job_id=None, error_code=None, revision=spec.revision,
                    spec=_redacted(asdict(spec)), attempts=[], transitions=[],
                    idempotency_key=None, cost_reservation_id=spec.cost_reservation_id,
                    file_path=None, content_hash=None, validation=None)

    def _outcome(self, record, *, status=None, error=None):
        return JobOutcome(
            record["shot_id"], status or record["status"].lower(), record.get("file_path"),
            [_AttemptRecord(**{k: a[k] for k in _AttemptRecord.__dataclass_fields__})
             for a in record["attempts"]], error or record.get("error_code"),
            record.get("provider_job_id"), record["input_hash"], record.get("content_hash"),
            copy.deepcopy(record.get("validation")), record.get("idempotency_key"),
            record.get("cost_reservation_id"))

    def get_record(self, spec: JobSpec) -> Optional[dict]:
        with self._exclusive():
            return copy.deepcopy(self._records.get(self._key(spec)))

    def run_one(self, spec, *, resume_handle=None, resume_attempts=0):
        resume = None
        if resume_handle:
            resume = {spec.shot_id: {"provider_job_id": resume_handle,
                                    "resume_attempts": resume_attempts}}
        return self.run_all([spec], resume=resume)[0]

    def _validate_output(self, path, spec):
        path = Path(path).resolve()
        if not path.is_file() or not path.stat().st_size:
            raise MultishotValidationError("Missing or empty output")
        before = file_hash(path)
        report = self._validator(path, spec)
        if not isinstance(report, dict) or report.get("valid") is not True:
            raise MultishotValidationError("Validator did not accept output")
        if file_hash(path) != before:
            raise MultishotValidationError("Output changed during validation")
        return before, {**report, "input_hash": spec.fingerprint(), "content_hash": before}

    def _reuse(self, record, spec):
        try:
            if not record.get("file_path") or not record.get("content_hash") or not record.get("validation") or not record.get("input_hash"):
                return False

            if record["input_hash"] != spec.fingerprint():
                return False

            v = record["validation"]
            if v.get("valid") is not True:
                return False
            if v.get("content_hash") != record["content_hash"]:
                return False
            if v.get("input_hash") != spec.fingerprint():
                return False

            path = Path(record["file_path"]).resolve()
            if not path.is_file() or not path.stat().st_size:
                return False

            fresh_digest, report = self._validate_output(path, spec)

            if fresh_digest != record["content_hash"]:
                return False

            return True
        except Exception:
            return False

    def run_all(self, specs, *, resume=None):
        # Freeze caller-owned inputs so mutations cannot change a paid payload
        # after its intent was persisted.
        specs = copy.deepcopy(list(specs))
        if len({s.shot_id for s in specs}) != len(specs):
            raise MultishotValidationError("Duplicate shot ids")
        for spec in specs:
            spec.validate()
            provider_name = getattr(self.provider, "provider", None)
            if provider_name and provider_name != spec.provider:
                raise MultishotValidationError("Scheduler provider does not match JobSpec")
        with self._exclusive():
            return self._run_all(specs, resume or {})

    def _run_all(self, specs, resume):
        deadline = time.monotonic() + self.deadline_seconds
        results, pending = {}, []
        polls = {s.shot_id: 0 for s in specs}
        downloads = {s.shot_id: 0 for s in specs}
        for spec in specs:
            key = self._key(spec)
            record = self._records.get(key)
            if record and record["input_hash"] != spec.fingerprint():
                results[spec.shot_id] = self._outcome(record, status="blocked", error="STALE_INPUT")
                continue
            if not spec.eligible or not self._eligibility(spec):
                results[spec.shot_id] = self._outcome(record or self._new(spec),
                                                    status="blocked", error="INELIGIBLE")
                continue
            if record and record["status"] == "SUBMISSION_UNKNOWN":
                handle = None
                try:
                    handle = self.provider.reconcile(spec, record.get("idempotency_key"))
                except Exception:
                    handle = None
                if handle:
                    self._check_handle(handle)
                    record["provider_job_id"] = handle
                    self._transition(record, "SUBMITTED")
                else:
                    results[spec.shot_id] = self._outcome(record)
                    continue
            if record is None:
                record = self._new(spec)
                self._records[key] = record
                info = resume.get(spec.shot_id)
                if info:
                    if info.get("provider_job_id"):
                        self._check_handle(info["provider_job_id"])
                        record["provider_job_id"] = info["provider_job_id"]
                        record["attempt"] = info.get("resume_attempts", 0) + 1
                        record["attempts"] = [dict(attempt=record["attempt"], started_at=time.time(),
                                                   finished_at=0.0, status="submitted", error_code=None)]
                        self._transition(record, "SUBMITTED")
                    else:
                        if not info.get("input_hash"):
                            del self._records[key]
                            dummy = self._new(spec)
                            results[spec.shot_id] = self._outcome(dummy, status="failed", error="INVALID_INPUT")
                            continue
                        record.update({k: info.get(k) for k in
                                       ("file_path", "content_hash", "validation")})
                        if "input_hash" in info:
                            record["input_hash"] = info["input_hash"]
                        record["imported"] = True
                        if not self._reuse(record, spec):
                            self._transition(record, "FAILED", "CORRUPT_OUTPUT")
                        else:
                            self._transition(record, "COMPLETED")
                self._save()
            if record["status"] == "COMPLETED":
                if self._reuse(record, spec):
                    results[spec.shot_id] = self._outcome(record)
                    continue
                record.update(file_path=None, content_hash=None, validation=None)
                self._transition(record, "DOWNLOADING" if record.get("provider_job_id") else "FAILED",
                                 "CORRUPT_OUTPUT")
            if record["status"] in {"INTENT", "SUBMISSION_UNKNOWN"}:
                # A crash between intent and POST is indistinguishable from a
                # crash after POST. A negative lookup is NOT proof of rejection.
                try:
                    reconcile = getattr(self.provider, "reconcile", None)
                    handle = reconcile(spec, record["idempotency_key"]) if reconcile else None
                except Exception:
                    handle = None
                if handle:
                    self._check_handle(handle)
                    record["provider_job_id"] = handle
                    record["attempts"][-1]["provider_job_id"] = handle
                    self._transition(record, "SUBMITTED")
                else:
                    self._transition(record, "SUBMISSION_UNKNOWN", "SUBMISSION_UNKNOWN")
                    results[spec.shot_id] = self._outcome(record)
                    continue
            if record["status"] in {"FAILED", "PERMANENTLY_FAILED"}:
                results[spec.shot_id] = self._outcome(record)
            else:
                pending.append(spec)

        while pending and time.monotonic() < deadline:
            progressed = False
            for spec in list(pending):
                if time.monotonic() >= deadline:
                    break
                record = self._records[self._key(spec)]
                status = record["status"]
                if status in {"PENDING", "RETRY_PENDING"}:
                    if not spec.eligible or not self._eligibility(spec):
                        results[spec.shot_id] = self._outcome(record, status="blocked", error="INELIGIBLE")
                        pending.remove(spec)
                        continue
                    active = sum(r["status"] in _ACTIVE for r in self._records.values())
                    if active >= self.max_concurrency:
                        continue
                    self._submit(spec, record, deadline)
                    progressed = True
                elif status in {"SUBMITTED", "RUNNING"}:
                    if polls[spec.shot_id] >= self.max_polls:
                        results[spec.shot_id] = self._outcome(record, status="running", error="TIMEOUT")
                        pending.remove(spec)
                        continue
                    polls[spec.shot_id] += 1
                    self._poll(record, deadline)
                    progressed = True
                    if (record["status"] == "RUNNING" and record.get("error_code")
                            and not is_retryable(record["error_code"])):
                        results[spec.shot_id] = self._outcome(record)
                        pending.remove(spec)
                        continue
                elif status == "DOWNLOADING":
                    if downloads[spec.shot_id] >= self.max_attempts:
                        results[spec.shot_id] = self._outcome(record, status="failed")
                        pending.remove(spec)
                        continue
                    downloads[spec.shot_id] += 1
                    self._download(spec, record, downloads[spec.shot_id], deadline)
                    progressed = True
                    if record["status"] == "DOWNLOADING" and record.get("error_code") in PERMANENT_ERRORS:
                        results[spec.shot_id] = self._outcome(record, status="failed")
                        pending.remove(spec)
                        continue
                if record["status"] in {"COMPLETED", "FAILED", "PERMANENTLY_FAILED", "SUBMISSION_UNKNOWN"}:
                    results[spec.shot_id] = self._outcome(record)
                    pending.remove(spec)
            if not progressed:
                break
            if pending and self.poll_interval:
                self._sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
        for spec in pending:
            record = self._records[self._key(spec)]
            waiting = record["status"] in {"PENDING", "RETRY_PENDING"}
            at_capacity = sum(r["status"] in _ACTIVE for r in self._records.values()) >= self.max_concurrency
            status = "running" if record["status"] in _ACTIVE else record["status"].lower()
            results[spec.shot_id] = self._outcome(
                record, status="blocked" if waiting and at_capacity else status,
                error="CAPACITY" if waiting and at_capacity else "TIMEOUT")
        return [results[s.shot_id] for s in specs]

    def _delay(self, attempt, exc, deadline):
        delay = backoff_delay(attempt, self.base_delay, self.max_delay,
                              retry_after=exc.retry_after, jitter=self._rng())
        if delay:
            self._sleep(min(delay, max(0, deadline - time.monotonic())))

    def _failed_attempt(self, record, exc, deadline):
        self._transition(record, "FAILED" if is_retryable(exc.code) else "PERMANENTLY_FAILED", exc.code)
        if is_retryable(exc.code) and record["attempt"] < record["max_attempts"]:
            self._delay(record["attempt"], exc, deadline)
            record["attempt"] += 1
            record["provider_job_id"] = None
            # Retain terminal attempt status and handle in attempt history.
            record.update(status="RETRY_PENDING", error_code=exc.code, updated_at=_now())
            self._save()

    def _submit(self, spec, record, deadline):
        # Validate provider mapping locally before recording an uncertain POST.
        validate = getattr(self.provider, "validate_spec", None)
        if validate:
            try:
                validate(spec)
            except Exception:
                self._transition(record, "PERMANENTLY_FAILED", "INVALID_INPUT")
                return
        record["idempotency_key"] = uuid.uuid4().hex
        record["attempts"].append(dict(attempt=record["attempt"], started_at=time.time(),
                                      finished_at=0.0, status="intent", error_code=None,
                                      idempotency_key=record["idempotency_key"], provider_job_id=None))
        self._transition(record, "INTENT")
        try:
            handle = self.provider.submit(spec, record["attempt"], record["idempotency_key"])
            self._check_handle(handle)
        except ProviderError as exc:
            if exc.rejected:
                self._failed_attempt(record, exc, deadline)
            else:
                record["transitions"].append(dict(status="SUBMIT_ERROR", cause_code=exc.code, at=_now()))
                self._transition(record, "SUBMISSION_UNKNOWN", "SUBMISSION_UNKNOWN")
            return
        except Exception:
            self._transition(record, "SUBMISSION_UNKNOWN", "SUBMISSION_UNKNOWN")
            return
        record["provider_job_id"] = handle
        record["attempts"][-1]["provider_job_id"] = handle
        self._transition(record, "SUBMITTED")

    @staticmethod
    def _check_handle(handle):
        if (not isinstance(handle, str) or not handle or "http" in handle.lower()
                or len(handle) > 2048 or "\n" in handle or "\r" in handle):
            raise ProviderError("SUBMISSION_UNKNOWN")

    def _poll(self, record, deadline):
        try:
            status = self.provider.poll(record["provider_job_id"])
            if status not in {"running", "completed"}:
                raise ProviderError("UNKNOWN_PROVIDER_ERROR")
            self._transition(record, "RUNNING" if status == "running" else "DOWNLOADING")
        except Exception as error:
            exc = error if isinstance(error, ProviderError) else ProviderError("UNKNOWN_PROVIDER_ERROR")
            if exc.terminal:
                self._failed_attempt(record, exc, deadline)
            else:
                self._transition(record, "RUNNING", exc.code)
                self._delay(record["attempt"], exc, deadline)

    def _download(self, spec, record, attempt, deadline):
        dest = self._dest_dir / self._key(spec) / record["input_hash"].split(":")[-1]
        dest.mkdir(parents=True, exist_ok=True)
        download_number = 1 + sum(t["status"] == "DOWNLOAD_STARTED" for t in record["transitions"])
        record["transitions"].append(dict(status="DOWNLOAD_STARTED", attempt=download_number, at=_now()))
        self._save()
        try:
            path = Path(self.provider.download(record["provider_job_id"], str(dest))).resolve()
            if not path.is_relative_to(dest):
                raise MultishotValidationError("Provider output escaped destination")
            digest, report = self._validate_output(path, spec)
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            record.update(file_path=str(path), content_hash=digest, validation=report)
            self._transition(record, "COMPLETED")
        except Exception as error:
            exc = error if isinstance(error, ProviderError) else ProviderError("CORRUPT_OUTPUT")
            record["transitions"].append(dict(status="DOWNLOAD_ATTEMPT", attempt=attempt,
                                               error_code=exc.code, at=_now()))
            self._transition(record, "DOWNLOADING", exc.code)
            self._delay(attempt, exc, deadline)
