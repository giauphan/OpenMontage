"""Restartable Kling Official Classic adapter using the existing provider code.

Deliberately scoped to Classic text/image-to-video. Unsupported settings fail
before POST rather than silently changing model/family. No credentials or signed
result URLs enter handles. The existing client's automatic POST retry is disabled:
a transport error or server error cannot prove that a paid task was not created.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import jsonschema

from lib.multishot_jobs import JobSpec, ProviderError
from tools._kling.client import KlingClient
from tools._kling.errors import KlingAPIError
from tools.video.kling_official_video import KlingOfficialVideo


class KlingOfficialProvider:
    provider = "kling_official"
    _paths = {"/v1/videos/text2video", "/v1/videos/image2video"}
    _settings = {"api_family", "operation", "mode", "sound", "negative_prompt",
                 "cfg_scale", "aspect_ratio", "camera_control", "watermark"}

    def __init__(self, *, client: KlingClient | None = None,
                 max_download_bytes: int = 512 * 1024 * 1024,
                 download_timeout: float = 180):
        if (not isinstance(max_download_bytes, int) or max_download_bytes < 1
                or not math.isfinite(download_timeout) or download_timeout <= 0):
            raise ValueError("Download bounds must be positive and finite")
        self.max_download_bytes = max_download_bytes
        self.download_timeout = download_timeout
        self.client = client or KlingClient(max_retries=0)
        # This adapter, not a generic HTTP client, owns retry semantics.
        self.client.max_retries = 0
        self.tool = KlingOfficialVideo()

    def _request(self, spec: JobSpec, key: str):
        spec.validate()
        if spec.provider != self.provider:
            raise ValueError("Provider mismatch")
        expected = "sha256:" + hashlib.sha256(spec.prompt.encode("utf-8")).hexdigest()
        if spec.prompt_hash != expected:
            raise ValueError("Prompt content hash mismatch")
        if set(spec.settings) - self._settings:
            raise ValueError("Unsupported Classic settings")
        if spec.settings.get("api_family", "classic") != "classic":
            raise ValueError("This lifecycle adapter supports Classic only")
        if spec.duration_sec != int(spec.duration_sec):
            raise ValueError("Classic duration must be an integer")
        inputs = {**spec.settings, "prompt": spec.prompt, "model_name": spec.model,
                  "duration": str(int(spec.duration_sec)), "external_task_id": key,
                  "api_family": "classic"}
        operation = inputs.setdefault("operation", "image_to_video" if spec.references else "text_to_video")
        if operation not in {"text_to_video", "image_to_video"}:
            raise ValueError("Unsupported Classic operation")
        if spec.reference_hashes and not spec.references:
            raise ValueError("Hashes are not renderable references")
        if len(spec.references) > 2 or (spec.references and operation != "image_to_video"):
            raise ValueError("Classic supports first-frame and optional end-frame references")
        roles = set()
        for index, ref in enumerate(spec.references):
            role = ref.get("role", "first_frame" if index == 0 else "end_frame")
            if role not in {"first_frame", "end_frame"} or role in roles:
                raise ValueError("Unsupported or duplicate reference role")
            roles.add(role)
            # Frozen local references allow actual content hash and readability
            # validation; mutable remote image URLs cannot supply that guarantee.
            path = ref.get("path")
            if not path or ref.get("url"):
                raise ValueError("Freeze references locally before dispatch")
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
            inputs["reference_image_path" if role == "first_frame" else "reference_tail_image_path"] = path
        if operation == "image_to_video" and "first_frame" not in roles:
            raise ValueError("Image-to-video requires a first-frame reference")
        if operation == "image_to_video" and "aspect_ratio" in spec.settings:
            raise ValueError("Classic image-to-video does not accept aspect_ratio")
        jsonschema.validate(inputs, self.tool.input_schema)
        return self.tool._build_request(inputs)

    def validate_spec(self, spec: JobSpec):
        self._request(spec, "validation-only")

    @staticmethod
    def _error(exc: KlingAPIError, *, submitting=False, terminal=False):
        code, http = str(exc.code), exc.http_status
        if code in {"1000", "1001", "1002", "1003", "1004", "1103"} or http in {401, 403}:
            normalized = "AUTH_ERROR"
        elif code in {"1101", "1102"}:
            normalized = "QUOTA_EXCEEDED"
        elif code == "1301":
            normalized = "SAFETY_REFUSAL"
        elif code in {"1200", "1201"} or http in {400, 422}:
            normalized = "INVALID_INPUT"
        elif code in {"1302", "1303"} or http == 429:
            normalized = "RATE_LIMIT"
        elif code in {"5000", "5001", "5002"} or (http is not None and http >= 500):
            normalized = "PROVIDER_5XX"
        else:
            normalized = "JOB_FAILED" if terminal else "UNKNOWN_PROVIDER_ERROR"
        rejected = submitting and normalized in {
            "AUTH_ERROR", "QUOTA_EXCEEDED", "SAFETY_REFUSAL", "INVALID_INPUT", "RATE_LIMIT"}
        # Never leak the provider's raw message (may echo signed URLs/prompts).
        return ProviderError(normalized, rejected=rejected, terminal=terminal)

    def submit(self, spec: JobSpec, attempt: int, idempotency_key: str) -> str:
        try:
            request = self._request(spec, idempotency_key)
        except Exception:
            raise ProviderError("INVALID_INPUT", rejected=True) from None
        try:
            task_id = self.client.create_classic_task(request["path"], request["payload"])
        except KlingAPIError as exc:
            raise self._error(exc, submitting=True) from None
        if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
            raise ProviderError("SUBMISSION_UNKNOWN")
        return json.dumps({"path": request["path"], "task_id": task_id}, sort_keys=True)

    def reconcile(self, spec: JobSpec, idempotency_key: str):
        # external_task_id is a correlation key, NOT a documented idempotency
        # guarantee or lookup endpoint in the existing client. No blind POST.
        return None

    def _status(self, handle):
        try:
            value = json.loads(handle)
            path, task_id = value["path"], value["task_id"]
            if path not in self._paths or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ProviderError("INVALID_INPUT") from None
        try:
            data = self.client.get(f"{path}/{task_id}").get("data") or {}
        except KlingAPIError as exc:
            raise self._error(exc) from None
        status = data.get("task_status")
        if status in {"submitted", "processing"}:
            return "running", data
        if status == "succeed":
            return "completed", data
        if status == "failed":
            raise self._error(KlingAPIError("", code=data.get("task_status_code") or data.get("code")),
                              terminal=True)
        raise ProviderError("UNKNOWN_PROVIDER_ERROR")

    def poll(self, handle: str) -> str:
        return self._status(handle)[0]

    def _download_file(self, url: str, partial: Path):
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or host == "localhost" or host.endswith((".localhost", ".local"))):
            raise ProviderError("DOWNLOAD_FAILED")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ProviderError("DOWNLOAD_FAILED")
        partial.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        # Signed CDN URLs are ephemeral and never persisted. Do not forward API
        # authorization, or follow an unvalidated redirect to another host.
        response = self.client.session.get(url, stream=True, allow_redirects=False,
                                           timeout=min(30, self.download_timeout))
        try:
            self.client._raise_for_http_error(response)
            chunks = (response.iter_content(chunk_size=128 * 1024)
                      if hasattr(response, "iter_content") else [response.content])
            size = 0
            with partial.open("wb") as stream:
                for chunk in chunks:
                    size += len(chunk)
                    if size > self.max_download_bytes or time.monotonic() - started > self.download_timeout:
                        raise ProviderError("DOWNLOAD_FAILED")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if size == 0:
                raise ProviderError("DOWNLOAD_FAILED")
        finally:
            close = getattr(response, "close", None)
            if close:
                close()

    def download(self, handle: str, dest_dir: str) -> str:
        partial = Path(dest_dir) / "output.mp4.part"
        target = Path(dest_dir) / "output.mp4"
        try:
            status, data = self._status(handle)
            outputs = (data.get("task_result") or {}).get("videos") or []
            if status != "completed" or not outputs or not outputs[0].get("url"):
                raise ProviderError("DOWNLOAD_FAILED")
            self._download_file(outputs[0]["url"], partial)
            os.replace(partial, target)
            return str(target)
        except ProviderError:
            raise
        except KlingAPIError as exc:
            raise self._error(exc) from None
        except Exception:
            raise ProviderError("DOWNLOAD_FAILED") from None
        finally:
            partial.unlink(missing_ok=True)
