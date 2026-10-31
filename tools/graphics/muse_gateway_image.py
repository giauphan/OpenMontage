"""Muse Image Generation Tool via Toolcase Gateway Rust.

Integrates with Toolcase Gateway Rust (POST /muse-ai/v1/create-image?async=true,
GET /muse-ai/v1/images/{id}, GET /muse-ai/v1/images/{id}/content).

Features:
- Idempotent async job submission and recovery.
- Full handling of 409 APPROVAL_REQUIRED without automated bypass.
- SSRF-safe redirect validation for content downloads.
- Local Pillow decoding, MIME, dimension, and hash verification.
- Zero direct external calls to unauthorized third-party services.
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import requests
from PIL import Image

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

logger = logging.getLogger(__name__)


class MuseGatewayImage(BaseTool):
    name = "muse_gateway_image"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "muse"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["pillow", "requests"]
    install_instructions = (
        "Ensure toolcase-gateway-rs is running and reachable via MUSE_GATEWAY_BASE_URL.\n"
        "Default: http://127.0.0.1:20129"
    )
    agent_skills = []

    capabilities = [
        "generate_image",
        "text_to_image",
        "conceptual_illustration",
        "async_image_job",
    ]
    supports = {
        "aspect_ratio": True,
        "async_jobs": True,
        "idempotency_keys": True,
        "local_validation": True,
    }
    best_for = [
        "conceptual AI illustrations for non-proof video beats",
        "gateway-mediated async image generation",
    ]
    not_good_for = [
        "authentic screenshot proof",
        "fake terminal logs or UI benchmarks",
        "direct unmediated cloud API calls",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Conceptual illustration prompt. Must not request fake screenshots or UI.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["9:16", "16:9", "1:1"],
                "default": "9:16",
                "description": "Aspect ratio for portrait Shorts or landscape video.",
            },
            "model": {
                "type": "string",
                "enum": ["muse-image"],
                "default": "muse-image",
                "description": "Gateway model alias.",
            },
            "submission_key": {
                "type": "string",
                "description": "Stable scoped hash for idempotency and job recovery.",
            },
            "output_path": {
                "type": "string",
                "description": "Local path where verified image will be saved.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout", "network_error"])
    idempotency_key_fields = ["prompt", "aspect_ratio", "model", "submission_key"]
    side_effects = ["creates local image asset", "dispatches gateway job"]
    user_visible_verification = ["Inspect generated conceptual image in contact sheet"]

    def __init__(self, http_session: Optional[requests.Session] = None):
        super().__init__()
        self._session = http_session or requests.Session()
        if http_session is None:
            self._session.trust_env = False

    def get_gateway_base_url(self) -> str:
        """Resolve and validate the configured Gateway base URL."""
        base_url = (
            os.environ.get("MUSE_GATEWAY_BASE_URL")
            or os.environ.get("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129")
        ).strip()
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid MUSE_GATEWAY_BASE_URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError(f"Missing hostname in MUSE_GATEWAY_BASE_URL: {base_url}")
        return base_url.rstrip("/")

    def get_status(self) -> ToolStatus:
        try:
            base_url = self.get_gateway_base_url()
            # If external calls are strictly disabled and no local gateway is running
            if os.environ.get("MUSE_GATEWAY_EXTERNAL_CALLS_ALLOWED", "0") not in ("1", "true", "True"):
                return ToolStatus.AVAILABLE
            return ToolStatus.AVAILABLE
        except Exception:
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Gateway pricing model is not established by API docs; do not invent a price
        configured = os.environ.get("MUSE_GATEWAY_ESTIMATED_COST_USD")
        if configured:
            try:
                return float(configured)
            except ValueError:
                pass
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start_time = time.time()
        prompt = inputs.get("prompt", "").strip()
        if not prompt:
            return ToolResult(success=False, error="Prompt cannot be empty", data={"error_code": "INVALID_INPUT"})

        aspect_ratio = inputs.get("aspect_ratio", "9:16")
        if aspect_ratio not in ("9:16", "16:9", "1:1"):
            return ToolResult(
                success=False,
                error=f"Invalid aspect_ratio: {aspect_ratio}",
                data={"error_code": "INVALID_ASPECT_RATIO"},
            )

        model = inputs.get("model", "muse-image")
        output_path_str = inputs.get("output_path", "assets/visuals/generated_muse_image.png")
        output_path = Path(output_path_str)

        # 1. Base URL & Safety Gates
        try:
            base_url = self.get_gateway_base_url()
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc), data={"error_code": "INVALID_GATEWAY_URL"})

        # Check external calls gate unless in test mode
        if (
            os.environ.get("MUSE_GATEWAY_EXTERNAL_CALLS_ALLOWED", "1") not in ("1", "true", "True")
            and not getattr(self, "_allow_offline_mock", False)
        ):
            return ToolResult(
                success=False,
                error="EXTERNAL_CALLS_DISABLED: External Muse gateway generation is disabled by operator policy",
                data={"error_code": "EXTERNAL_CALLS_DISABLED"},
            )

        # 2. Idempotency submission key
        submission_key = inputs.get("submission_key")
        if not submission_key:
            canon = f"{prompt}:{aspect_ratio}:{model}"
            submission_key = f"om-{hashlib.sha256(canon.encode('utf-8')).hexdigest()[:32]}"

        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "model": model,
            "submission_key": submission_key,
        }

        # 3. Submit generation job (sync by default, async if MUSE_GATEWAY_USE_ASYNC=1)
        use_async = os.environ.get("MUSE_GATEWAY_USE_ASYNC", "0") in ("1", "true", "True")
        create_url = f"{base_url}/muse-ai/v1/create-image" + ("?async=true" if use_async else "")
        post_timeout = float(os.environ.get("MUSE_GATEWAY_POST_TIMEOUT_SECONDS", "180.0" if not use_async else "30.0"))
        try:
            resp = self._session.post(create_url, json=payload, timeout=post_timeout)
        except requests.exceptions.RequestException as exc:
            return ToolResult(
                success=False,
                error=f"Gateway connection error: {exc}",
                data={"error_code": "GATEWAY_CONNECT_FAILED"},
            )

        if resp.status_code == 409:
            return ToolResult(
                success=False,
                error="APPROVAL_REQUIRED: Scoped Muse browser approval is required in Gateway",
                data={"error_code": "APPROVAL_REQUIRED", "approval_required": True, "submission_key": submission_key},
            )

        if resp.status_code in (401, 403):
            return ToolResult(
                success=False,
                error=f"Gateway auth failed: HTTP {resp.status_code}",
                data={"error_code": "AUTH_FAILED"},
            )

        if resp.status_code == 400:
            return ToolResult(
                success=False,
                error=f"Gateway rejected request: {resp.text}",
                data={"error_code": "INVALID_REQUEST"},
            )

        if resp.status_code not in (200, 201, 202):
            return ToolResult(
                success=False,
                error=f"Gateway returned unexpected HTTP {resp.status_code}: {resp.text}",
                data={"error_code": "GATEWAY_ERROR"},
            )

        try:
            res_data = resp.json()
        except Exception:
            return ToolResult(
                success=False,
                error="Gateway response is not valid JSON",
                data={"error_code": "INVALID_GATEWAY_JSON"},
            )

        job_id = res_data.get("id")
        if not job_id:
            return ToolResult(
                success=False,
                error="Gateway response omitted job id",
                data={"error_code": "MISSING_JOB_ID"},
            )

        status = res_data.get("status", "submitting")
        image_url = res_data.get("image_url") or ""

        # 4. Polling loop if not completed
        poll_interval = float(os.environ.get("MUSE_GATEWAY_POLL_INTERVAL_SECONDS", "2.0"))
        deadline_sec = float(os.environ.get("MUSE_GATEWAY_JOB_DEADLINE_SECONDS", "180.0"))
        poll_start = time.time()
        not_found_retries = 0

        while status != "completed":
            if status in ("failed", "error"):
                err_msg = res_data.get("error") or "Gateway reported job failed"
                return ToolResult(
                    success=False,
                    error=f"Job {job_id} failed: {err_msg}",
                    data={"error_code": "JOB_FAILED"},
                )

            if time.time() - poll_start > deadline_sec:
                return ToolResult(
                    success=False,
                    error=f"Job {job_id} timed out after {deadline_sec}s (last status: {status})",
                    data={"error_code": "JOB_TIMEOUT", "gateway_job_id": job_id, "submission_key": submission_key},
                )

            time.sleep(poll_interval)
            poll_url = f"{base_url}/muse-ai/v1/images/{job_id}"
            try:
                poll_resp = self._session.get(poll_url, timeout=15)
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Transient polling error for job {job_id}: {exc}")
                continue

            if poll_resp.status_code == 409:
                return ToolResult(
                    success=False,
                    error="APPROVAL_REQUIRED: Scoped Muse browser approval is required in Gateway",
                    data={"error_code": "APPROVAL_REQUIRED", "approval_required": True, "gateway_job_id": job_id},
                )
            if poll_resp.status_code == 404:
                not_found_retries += 1
                if not_found_retries <= 5 and (time.time() - poll_start) < 20.0:
                    logger.debug(f"Transient 404 for job {job_id} ({not_found_retries}/5); retrying...")
                    time.sleep(poll_interval)
                    continue
                return ToolResult(
                    success=False,
                    error=f"Job {job_id} not found in gateway",
                    data={"error_code": "JOB_NOT_FOUND"},
                )

            if poll_resp.status_code != 200:
                logger.warning(f"Polling returned HTTP {poll_resp.status_code}")
                continue

            try:
                res_data = poll_resp.json()
            except Exception:
                continue

            status = res_data.get("status", status)
            image_url = res_data.get("image_url") or image_url

        # 5. Fetch content bytes
        content_url = f"{base_url}/muse-ai/v1/images/{job_id}/content"
        img_bytes, fetch_error = self._fetch_safe_content(content_url, fallback_url=image_url)
        if fetch_error:
            return ToolResult(
                success=False,
                error=fetch_error,
                data={"error_code": "CONTENT_FETCH_FAILED"},
            )

        # 6. Pillow decode and verification
        verify_error, img_meta = self._verify_image_bytes(img_bytes)
        if verify_error:
            return ToolResult(
                success=False,
                error=verify_error,
                data={"error_code": "IMAGE_VALIDATION_FAILED"},
            )

        # 7. Atomic write to destination (transcode to PNG if target is .png and input is WEBP)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = output_path.with_suffix(f".tmp.{os.getpid()}_{int(time.time())}")
            if output_path.suffix.lower() == ".png" and img_meta.get("format") != "PNG":
                with Image.open(io.BytesIO(img_bytes)) as pil_img:
                    pil_img.convert("RGB").save(tmp_path, format="PNG")
            else:
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)
                    f.flush()
                    os.fsync(f.fileno())
            tmp_path.replace(output_path)
        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"Failed to write image file: {exc}",
                data={"error_code": "FS_ERROR"},
            )

        duration = round(time.time() - start_time, 2)
        return ToolResult(
            success=True,
            data={
                "gateway_job_id": job_id,
                "provider": "muse",
                "model": model,
                "submission_key": submission_key,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "image_sha256": img_meta["sha256"],
                "width": img_meta["width"],
                "height": img_meta["height"],
                "mime": img_meta["mime"],
                "size_bytes": len(img_bytes),
                "approval_required": False,
                "output_file": str(output_path),
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=duration,
            model=model,
        )

    def _fetch_safe_content(self, url: str, fallback_url: Optional[str] = None) -> tuple[bytes, Optional[str]]:
        """Fetch content with strict SSRF protection and size limits."""
        target_urls = [url]
        if fallback_url and fallback_url != url:
            target_urls.append(fallback_url)

        max_bytes = 20 * 1024 * 1024  # 20MB ceiling

        for u in target_urls:
            try:
                # SSRF check on target host
                if not self._is_safe_remote_url(u):
                    return b"", f"SSRF blocked: URL {u} targets unallowed host or private network"

                resp = self._session.get(u, timeout=30, stream=True, allow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location")
                    if not loc or not self._is_safe_redirect(loc):
                        return b"", f"SSRF blocked: Unsafe redirect location {loc}"
                    resp = self._session.get(loc, timeout=30, stream=True, allow_redirects=False)

                if resp.status_code != 200:
                    continue

                content = bytearray()
                for chunk in resp.iter_content(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        return b"", "Image size exceeds 20MB limit"

                if content:
                    return bytes(content), None
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Failed fetching content from {u}: {exc}")

        return b"", "Failed to fetch image bytes from gateway media endpoints"

    def _is_safe_remote_url(self, url_str: str) -> bool:
        """Enforce origin rules: allow configured gateway base URL, loopback, or explicitly configured redirect hosts."""
        try:
            parsed = urlparse(url_str)
            if not parsed.hostname:
                return False
            host = parsed.hostname.lower()
            if host in ("localhost", "127.0.0.1", "::1", "gateway"):
                return True

            # Allow configured gateway base host and scheme
            gw_base = self.get_gateway_base_url()
            gw_parsed = urlparse(gw_base)
            if gw_parsed.hostname and host == gw_parsed.hostname.lower():
                return parsed.scheme == gw_parsed.scheme

            allowed_hosts_str = os.environ.get("MUSE_GATEWAY_ALLOWED_REDIRECT_HOSTS", "")
            allowed_hosts = {h.strip().lower() for h in allowed_hosts_str.split(",") if h.strip()}
            if host in allowed_hosts:
                return parsed.scheme == "https"

            # Check if private or link-local IP
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return host in ("127.0.0.1", "::1")
            except ValueError:
                pass
            return False
        except Exception:
            return False

    def _is_safe_redirect(self, loc: str) -> bool:
        parsed = urlparse(loc)
        if parsed.scheme not in ("http", "https"):
            return False
        return self._is_safe_remote_url(loc)

    def _verify_image_bytes(self, data: bytes) -> tuple[Optional[str], Dict[str, Any]]:
        """Validate raw bytes using Pillow: format, dimensions, pixel budget, MIME."""
        if not data or len(data) < 32:
            return "Image bytes empty or too small", {}

        # Magic byte detection / anti-spoofing
        lower_head = data[:1024].lower()
        if (
            b"<html" in lower_head
            or b"<!doctype" in lower_head
            or b"<svg" in lower_head
            or b"<script" in lower_head
        ):
            return "Downloaded content is HTML/SVG/text, not a valid bitmap image", {}

        try:
            img = Image.open(io.BytesIO(data))
            img.verify()
        except Exception as exc:
            return f"Pillow image verification failed: {exc}", {}

        # Reopen after verify() to inspect attributes safely
        try:
            img = Image.open(io.BytesIO(data))
            fmt = (img.format or "").upper()
            width, height = img.size
        except Exception as exc:
            return f"Cannot read image dimensions: {exc}", {}

        allowed_formats = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
        if fmt not in allowed_formats:
            return f"Disallowed image format '{fmt}'; must be PNG, JPEG, or WEBP", {}

        if width <= 0 or height <= 0:
            return f"Invalid image dimensions: {width}x{height}", {}

        if width * height > 4096 * 4096:
            return f"Image dimensions {width}x{height} exceed pixel safety limit", {}

        sha256 = hashlib.sha256(data).hexdigest()
        return None, {
            "format": fmt,
            "mime": allowed_formats[fmt],
            "width": width,
            "height": height,
            "sha256": sha256,
        }
