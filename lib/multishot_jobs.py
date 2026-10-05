"""Provider-neutral job boundary and crash-safe scheduler for multi-shot.

This module defines the submit / poll / download boundary between the
pipeline and a video provider, plus a deterministic fake provider for
tests and a bounded-concurrency scheduler with retry policy.

No provider-specific logic leaks into the scheduler: it operates on the
generic ``VideoProvider`` protocol. No live API calls are made here.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, Sequence

from lib.multishot_schemas import MultishotValidationError

# Document 02 error vocabulary.
ERROR_CODES = frozenset({
    "AUTH_ERROR", "RATE_LIMIT", "QUOTA_EXCEEDED", "INVALID_INPUT",
    "SAFETY_REFUSAL", "PROVIDER_5XX", "TIMEOUT", "JOB_FAILED",
    "DOWNLOAD_FAILED", "CORRUPT_OUTPUT", "UNKNOWN_PROVIDER_ERROR",
})

# Transient failures that may be retried (bounded backoff).
RETRYABLE_ERRORS = frozenset({
    "RATE_LIMIT", "PROVIDER_5XX", "TIMEOUT", "DOWNLOAD_FAILED", "JOB_FAILED",
})
# Permanent failures — never loop on these.
PERMANENT_ERRORS = frozenset({
    "AUTH_ERROR", "QUOTA_EXCEEDED", "INVALID_INPUT", "SAFETY_REFUSAL",
})


def is_retryable(code: Optional[str]) -> bool:
    """True when the failure class is transient and bounded-retryable."""
    return code in RETRYABLE_ERRORS


class ProviderError(Exception):
    """Provider failure carrying a normalized error code."""

    def __init__(self, code: str, message: str = "", *, retry_after: Optional[float] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after


class VideoProvider(Protocol):
    """Minimal provider protocol the scheduler depends on."""

    def submit(self, shot_id: str, attempt: int, prompt_hash: str) -> str:
        """Submit a job and return a remote handle string."""
        ...

    def poll(self, handle: str) -> str:
        """Return 'running', 'completed', or raise ``ProviderError``."""
        ...

    def download(self, handle: str, dest_dir: str) -> str:
        """Download output to ``dest_dir``; return the file path."""
        ...


# ------------------------------------------------------------------
# Fake provider for offline tests
# ------------------------------------------------------------------

@dataclass
class _AttemptRecord:
    attempt: int
    started_at: float
    finished_at: float
    status: str
    error_code: Optional[str] = None


class FakeProvider:
    """Deterministic provider driven by a script dict.

    Script keys are ``(shot_id, attempt)``. Values are:
      - ``'ok'``: submit + poll succeed, download writes a file.
      - an error code: poll raises ``ProviderError(code)``.
      - ``'slow'``: poll reports running for ``n`` extra polls.

    Unknown keys default to ``'ok'``. The provider tracks every submit so
    crash/uncertain-submit tests can assert no duplicate submissions.
    """

    def __init__(
        self,
        script: Optional[dict] = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        retry_after_map: Optional[dict] = None,
    ):
        self._script = dict(script or {})
        self._sleep = sleep
        self._retry_after = dict(retry_after_map or {})
        self.submissions: list[tuple[str, int]] = []
        self._lock = threading.Lock()
        self._concurrent = 0
        self._peak_concurrent = 0
        self._handles: dict[str, str] = {}

    # -- provider protocol -------------------------------------------------

    def submit(self, shot_id: str, attempt: int, prompt_hash: str) -> str:
        with self._lock:
            self.submissions.append((shot_id, attempt))
            self._handles[f"{shot_id}#{attempt}"] = f"handle-{shot_id}-{attempt}"
        return f"handle-{shot_id}-{attempt}"

    def poll(self, handle: str) -> str:
        with self._lock:
            self._concurrent += 1
            self._peak_concurrent = max(self._peak_concurrent, self._concurrent)
        try:
            shot_id, attempt = self._parse_handle(handle)
            outcome = self._script.get((shot_id, attempt), "ok")
            if outcome == "slow":
                self._sleep(0)
                return "running"
            if outcome in ERROR_CODES:
                raise ProviderError(
                    outcome,
                    f"{shot_id} attempt {attempt}",
                    retry_after=self._retry_after.get((shot_id, attempt)),
                )
            return "completed"
        finally:
            with self._lock:
                self._concurrent -= 1

    def download(self, handle: str, dest_dir: str) -> str:
        shot_id, _ = self._parse_handle(handle)
        outcome = self._script.get((shot_id, "download"), "ok")
        if outcome in ERROR_CODES:
            raise ProviderError(outcome, f"download {shot_id}")
        import os
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, f"{shot_id}.mp4")
        with open(path, "wb") as f:
            f.write(b"fake-video-bytes")
        return path

    @staticmethod
    def _parse_handle(handle: str) -> tuple[str, int]:
        # Handle format: "handle-{shot_id}-{attempt}".
        base, attempt = handle.rsplit("-", 1)
        shot_id = base[len("handle-"):]
        return shot_id, int(attempt)

    def peak_concurrent(self) -> int:
        with self._lock:
            return self._peak_concurrent

    def submissions_for(self, shot_id: str) -> list[int]:
        return [a for (s, a) in self.submissions if s == shot_id]


# ------------------------------------------------------------------
# Input hashing
# ------------------------------------------------------------------

def canonical_input_hash(
    *,
    provider: str,
    model: str,
    settings: dict,
    prompt: str,
    reference_hashes: Sequence[str],
) -> str:
    """Hash the canonical inputs a shot job depends on."""
    payload = json.dumps(
        {
            "provider": provider,
            "model": model,
            "settings": settings,
            "prompt": prompt,
            "reference_hashes": sorted(reference_hashes),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


# ------------------------------------------------------------------
# Scheduler
# ------------------------------------------------------------------

@dataclass
class JobSpec:
    shot_id: str
    prompt: str
    prompt_hash: str
    reference_hashes: list = field(default_factory=list)


@dataclass
class JobOutcome:
    shot_id: str
    status: str
    file_path: Optional[str]
    attempts: list
    error_code: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "shot_id": self.shot_id,
            "status": self.status,
            "file_path": self.file_path,
            "error_code": self.error_code,
            "attempts": [
                {"attempt": a.attempt, "status": a.status, "error_code": a.error_code}
                for a in self.attempts
            ],
        }


def backoff_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    *,
    retry_after: Optional[float] = None,
    jitter: float = 0.0,
) -> float:
    """Capped exponential backoff, honoring provider retry-after when larger."""
    exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
    delay = exponential + jitter
    if retry_after is not None:
        delay = max(delay, retry_after)
    return min(max_delay, delay)


class JobScheduler:
    """Bounded-concurrency provider job runner with bounded retries."""

    def __init__(
        self,
        provider: VideoProvider,
        *,
        max_concurrency: int = 3,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 10.0,
        deadline_seconds: Optional[float] = None,
        sleep: Optional[Callable[[float], None]] = None,
        rng: Optional[Callable[[], float]] = None,
        dest_dir: str = ".",
    ):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.provider = provider
        self.max_concurrency = max_concurrency
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.deadline_seconds = deadline_seconds
        self._sleep = sleep or time.sleep
        self._rng = rng or (lambda: 0.0)
        self._dest_dir = dest_dir
        self._start_time: Optional[float] = None

    # -- single-shot operations --------------------------------------------

    def run_one(
        self,
        spec: JobSpec,
        *,
        resume_handle: Optional[str] = None,
        resume_attempts: int = 0,
    ) -> JobOutcome:
        """Run one shot to completion with bounded retries.

        ``resume_handle`` enables crash recovery: when a prior process
        already submitted this shot, the scheduler polls the known handle
        instead of submitting a duplicate.
        """
        self._start_time = time.monotonic()
        attempts: list = []
        start_attempt = resume_attempts + 1

        attempt = start_attempt
        last_error: Optional[str] = None
        last_retry_after: Optional[float] = None
        while attempt <= self.max_attempts:
            record = _AttemptRecord(attempt=attempt, started_at=time.monotonic(),
                                    finished_at=0.0, status="submitted")
            try:
                handle = (
                    resume_handle
                    if resume_handle and attempt == start_attempt
                    else self.provider.submit(spec.shot_id, attempt, spec.prompt_hash)
                )
                if self._deadline_exceeded():
                    record.status = "failed"
                    record.error_code = "TIMEOUT"
                    attempts.append(record)
                    last_error = "TIMEOUT"
                    break
                status = self.provider.poll(handle)
                if status == "running":
                    record.status = "running"
                    record.finished_at = time.monotonic()
                    attempts.append(record)
                    return self._finalize(spec, "running", attempts, None, "RUNNING")
                record.status = "completed"
                record.finished_at = time.monotonic()
                attempts.append(record)
                path = self.provider.download(handle, self._dest_dir)
                self._assert_download_complete(path)
                return JobOutcome(spec.shot_id, "completed", path, attempts, None)
            except ProviderError as exc:
                record.status = "failed"
                record.error_code = exc.code
                record.finished_at = time.monotonic()
                attempts.append(record)
                last_error = exc.code
                last_retry_after = exc.retry_after
                if not is_retryable(exc.code) or attempt == self.max_attempts:
                    status = "permanently_failed" if not is_retryable(exc.code) else "failed"
                    return JobOutcome(spec.shot_id, status, None, attempts, exc.code)
                delay = backoff_delay(
                    attempt, self.base_delay, self.max_delay,
                    retry_after=last_retry_after, jitter=self._rng(),
                )
                if delay > 0:
                    self._sleep(delay)
            except MultishotValidationError as exc:
                record.status = "failed"
                record.error_code = "DOWNLOAD_FAILED"
                record.finished_at = time.monotonic()
                attempts.append(record)
                last_error = "DOWNLOAD_FAILED"
                if attempt == self.max_attempts:
                    return JobOutcome(spec.shot_id, "failed", None, attempts, last_error)
                delay = backoff_delay(attempt, self.base_delay, self.max_delay, jitter=self._rng())
                if delay > 0:
                    self._sleep(delay)
            finally:
                pass
            attempt += 1

        status = "permanently_failed" if not is_retryable(last_error) else "failed"
        return JobOutcome(spec.shot_id, status, None, attempts, last_error)

    # -- bounded-concurrency multi-shot ------------------------------------

    def run_all(
        self,
        specs: list,
        *,
        resume: Optional[dict] = None,
    ) -> list:
        """Run all specs under a concurrency bound, preserving plan order.

        Completed shots in ``resume`` are reused without re-submission.
        Results are returned in the same order as ``specs``.
        """
        outcomes: dict = {}
        pending: list = []
        resume = resume or {}
        for spec in specs:
            if spec.shot_id in resume:
                resume_info = resume[spec.shot_id]
                outcomes[spec.shot_id] = JobOutcome(
                    spec.shot_id, "completed",
                    resume_info.get("file_path"), [], None,
                )
            else:
                pending.append(spec)

        if pending:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
                futures = {
                    pool.submit(self.run_one, spec): spec.shot_id
                    for spec in pending
                }
                for future in futures:
                    shot_id = futures[future]
                    outcomes[shot_id] = future.result()

        return [outcomes[spec.shot_id] for spec in specs]

    # -- helpers -----------------------------------------------------------

    def _assert_download_complete(self, path: str) -> None:
        import os
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise MultishotValidationError(
                f"Download incomplete or empty: {path!r} — not marking completed"
            )

    def _finalize(
        self, spec: JobSpec, status: str, attempts: list, path, error_code
    ) -> JobOutcome:
        return JobOutcome(spec.shot_id, status, path, attempts, error_code)

    def _deadline_exceeded(self) -> bool:
        if self.deadline_seconds is None or self._start_time is None:
            return False
        return (time.monotonic() - self._start_time) > self.deadline_seconds
