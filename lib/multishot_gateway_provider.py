"""Gateway-backed multishot video provider adapter."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin

from lib.multishot_jobs import JobSpec, ProviderError


class GatewayHttpTransport:
    def __init__(self, base_url: str, *, timeout: float = 120):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def post_json(self, path: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload, allow_nan=False).encode("utf-8")
        req = urllib.request.Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_json(self, path: str, headers: dict) -> dict:
        req = urllib.request.Request(
            urljoin(self.base_url, path.lstrip("/")),
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def download(self, url: str, dest: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "OpenMontage/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            dest.write_bytes(response.read())


class GatewayVideoProvider:
    provider = "gateway"

    def __init__(self, *, base_url: str, transport=None):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        self.base_url = base_url.rstrip("/")
        self.transport = transport or GatewayHttpTransport(base_url)
        self._videos: dict[str, str] = {}

    def validate_spec(self, spec: JobSpec) -> None:
        if spec.provider != self.provider:
            raise ProviderError("INVALID_INPUT", "spec provider must be gateway", rejected=True, terminal=True)
        if not isinstance(spec.model, str) or not spec.model.strip():
            raise ProviderError("INVALID_INPUT", "model is required", rejected=True, terminal=True)

    def submit(self, spec: JobSpec, attempt: int, idempotency_key: str) -> str:
        self.validate_spec(spec)
        payload = {
            "prompt": spec.prompt,
            "model": spec.model,
            "duration": spec.duration_sec,
            "aspect_ratio": spec.settings.get("aspect_ratio", "16:9"),
        }
        headers = {"Idempotency-Key": idempotency_key}
        try:
            body = self.transport.post_json("/muse-ai/v1/create-video", payload, headers)
        except (TimeoutError, OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ProviderError("SUBMISSION_UNKNOWN", str(exc)) from exc
        return self._handle_from_body(body)

    def reconcile(self, spec: JobSpec, idempotency_key: str) -> str | None:
        try:
            body = self.transport.get_json(f"/muse-ai/v1/create-video/{quote(idempotency_key, safe='')}", {})
        except (TimeoutError, OSError, urllib.error.URLError, urllib.error.HTTPError):
            return None
        if not body or not body.get("id"):
            return None
        return self._handle_from_body(body)

    def poll(self, handle: str) -> str:
        video_id = self._video_id(handle)
        body = self.transport.get_json(f"/muse-ai/v1/create-video/{quote(video_id, safe='')}", {})
        status = body.get("status")
        if status in {"completed", "running", "submitted"}:
            if body.get("video_url"):
                self._videos[video_id] = body["video_url"]
            return "completed" if status == "completed" else "running"
        if status in {"failed", "error", "cancelled"}:
            raise ProviderError("JOB_FAILED", status, terminal=True)
        return "running"

    def download(self, handle: str, dest_dir: str) -> str:
        video_id = self._video_id(handle)
        url = self._videos.get(video_id)
        if not url:
            body = self.transport.get_json(f"/muse-ai/v1/create-video/{quote(video_id, safe='')}", {})
            url = body.get("video_url")
        if not url:
            raise ProviderError("DOWNLOAD_FAILED", "gateway response has no video_url", terminal=True)
        target = Path(dest_dir) / f"{video_id}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.transport.download(url, target)
        except (TimeoutError, OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ProviderError("DOWNLOAD_FAILED", str(exc), terminal=True) from exc
        return str(target)

    def _handle_from_body(self, body: dict) -> str:
        video_id = body.get("id")
        if not isinstance(video_id, str) or not video_id:
            raise ProviderError("UNKNOWN_PROVIDER_ERROR", "gateway response missing id")
        if body.get("video_url"):
            self._videos[video_id] = body["video_url"]
        return f"gw:{video_id}"

    @staticmethod
    def _video_id(handle: str) -> str:
        if not isinstance(handle, str) or not handle.startswith("gw:"):
            raise ProviderError("INVALID_INPUT", "invalid gateway handle", rejected=True, terminal=True)
        return handle[3:]
