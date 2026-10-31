"""Facebook Business Suite / Creator Studio Adapter Publisher Tool for OpenMontage.

Publishes videos and Reels to Facebook Pages via Toolcase Gateway (/custom/facebook)
with automated multi-language AI dubbing / translation (14 languages enabled by default)
and native post scheduling (scheduled_publish_time) between 10m and 75d in advance.

Follows SCHEDULING_AND_AUTO_TRANSLATE_GUIDE.md.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:20129/custom/facebook"
DEFAULT_14_LANGUAGES = [
    "en_US", "vi_VN", "hi_IN", "ar_AR", "pt_BR", "es_LA", "fr_FR",
    "bn_IN", "id_ID", "th_TH", "te_IN", "ta_IN", "mr_IN", "kn_IN",
]


class FacebookPublisher(BaseTool):
    name = "facebook_publisher"
    version = "1.0.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "facebook"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["python:requests"]
    install_instructions = (
        "1. Ensure Toolcase Gateway is running on port 20129 with facebook-suite enabled.\n"
        "2. Configure Meta Business Suite cookie in Gateway Dashboard or config.json.\n"
        "Configured via TOOLCASE_GATEWAY_URL or FACEBOOK_GATEWAY_BASE_URL."
    )

    agent_skills = []
    capabilities = ["facebook_upload", "reels_publish", "auto_translate", "scheduled_publish"]
    supports = {
        "local_offline": False,
        "free": True,
        "uploads": True,
        "auto_dubbing": True,
        "native_scheduling": True,
    }
    best_for = [
        "direct Facebook video upload & Reels publishing via Toolcase Gateway",
        "native Facebook scheduled publishing between 10 minutes and 75 days in advance",
        "automated multi-language AI dubbing across 14 languages without extra tools",
    ]
    not_good_for = ["offline publishing without internet"]

    input_schema = {
        "type": "object",
        "required": ["video_path"],
        "properties": {
            "video_path": {"type": "string", "description": "Path to the video MP4 file."},
            "title": {"type": "string", "description": "Optional video title."},
            "caption": {"type": "string", "description": "Video caption or description."},
            "description": {"type": "string", "description": "Alias for caption."},
            "target_id": {"type": "string", "description": "Facebook Page ID or actor ID."},
            "page_id": {"type": "string", "description": "Alias for target_id."},
            "scheduled_publish_time": {
                "type": "integer",
                "description": "Unix timestamp in seconds for scheduled publishing (10m to 75d).",
            },
            "enable_auto_translate": {
                "type": "boolean",
                "default": True,
                "description": "Enable automated multi-language audio dubbing (default True).",
            },
            "translated_languages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional custom list of language codes to dub into.",
            },
            "gateway_url": {
                "type": "string",
                "description": "Optional custom Toolcase Gateway Facebook endpoint.",
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "status": {"type": "string"},
            "facebook_post_id": {"type": "string"},
            "video_id": {"type": "string"},
            "video_url": {"type": "string"},
            "target_id": {"type": "string"},
            "scheduled_publish_time": {"type": "integer"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True)
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout", "network_error"])
    side_effects = ["uploads video to Facebook Page via Meta Business Suite"]

    def __init__(self, http_session: Optional[requests.Session] = None):
        super().__init__()
        self._session = http_session or requests.Session()
        if http_session is None:
            self._session.trust_env = False

    def get_gateway_base_url(self, inputs: Optional[dict[str, Any]] = None) -> str:
        """Resolve and validate the configured Facebook Gateway base URL."""
        inputs = inputs or {}
        configured = (
            inputs.get("gateway_url")
            or os.environ.get("FACEBOOK_GATEWAY_BASE_URL")
            or os.environ.get("META_GATEWAY_BASE_URL")
        )
        if not configured:
            toolcase_gw = os.environ.get("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129").strip().rstrip("/")
            configured = f"{toolcase_gw}/custom/facebook"

        base_url = configured.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid Facebook Gateway URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError(f"Missing hostname in Facebook Gateway URL: {base_url}")
        return base_url

    def check_readiness(self, base_url: Optional[str] = None) -> dict[str, Any]:
        """Check status and readiness of the Facebook Suite adapter."""
        url = base_url or self.get_gateway_base_url()
        endpoints = [f"{url}/v1/status", f"{url}/status"]
        for ep in endpoints:
            try:
                resp = self._session.get(ep, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return {"module": "facebook-suite", "status": "unknown", "configured": False}

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        """Upload video to Facebook Page with optional scheduling and auto-dubbing."""
        if "video_path" not in inputs:
            return ToolResult(success=False, error="Missing required input: video_path")

        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        caption = str(inputs.get("caption") or inputs.get("description") or "").strip()
        title = str(inputs.get("title") or "").strip()
        if not caption and not title:
            return ToolResult(success=False, error="Missing caption or title for Facebook post")

        target_id = str(inputs.get("target_id") or inputs.get("page_id") or os.environ.get("FB_PAGE_ID") or "").strip()

        # Validate scheduled_publish_time (10m to 75d) per SCHEDULING_AND_AUTO_TRANSLATE_GUIDE.md
        raw_sched = inputs.get("scheduled_publish_time") or inputs.get("schedule_time")
        scheduled_epoch: Optional[int] = None
        if raw_sched is not None:
            try:
                scheduled_epoch = int(raw_sched)
            except (ValueError, TypeError):
                return ToolResult(success=False, error=f"Invalid scheduled_publish_time: {raw_sched}")
            now_sec = int(time.time())
            min_sec = now_sec + 600  # 10 minutes
            max_sec = now_sec + 6480000  # 75 days
            if not (min_sec <= scheduled_epoch <= max_sec):
                return ToolResult(
                    success=False,
                    error=f"scheduled_publish_time ({scheduled_epoch}) must be between 10m and 75d in advance (range {min_sec}-{max_sec})",
                )

        enable_auto_translate = inputs.get("enable_auto_translate", True)
        translated_languages = inputs.get("translated_languages") or DEFAULT_14_LANGUAGES

        try:
            base_url = self.get_gateway_base_url(inputs)
        except ValueError as err:
            return ToolResult(success=False, error=str(err))

        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        # Prepare payload: send video_path and base64 for universal gateway compatibility
        try:
            with open(video_path, "rb") as vf:
                v_bytes = vf.read()
            v_b64 = base64.b64encode(v_bytes).decode("ascii")
        except Exception as read_err:
            return ToolResult(success=False, error=f"Failed to read video file: {read_err}")

        payload: dict[str, Any] = {
            "video_path": str(video_path.resolve()),
            "video_base64": v_b64,
            "file_name": video_path.name,
            "title": title or caption[:100],
            "description": caption or title,
            "enable_auto_translate": bool(enable_auto_translate),
            "translated_languages": translated_languages,
        }
        if target_id:
            payload["target_id"] = target_id
        if scheduled_epoch is not None:
            payload["scheduled_publish_time"] = scheduled_epoch

        upload_url = f"{base_url}/v1/upload/video"
        try:
            resp = self._session.post(upload_url, json=payload, headers=headers, timeout=300)
        except requests.exceptions.ConnectionError as conn_err:
            # Fallback to alternative endpoint
            try:
                resp = self._session.post(f"{base_url}/upload/video", json=payload, headers=headers, timeout=300)
            except Exception:
                return ToolResult(
                    success=False,
                    error=(
                        f"Failed to connect to Facebook Gateway at {base_url}: {conn_err}\n"
                        "Please verify toolcase-gateway-rs is running on port 20129 with facebook-suite enabled."
                    ),
                )
        except Exception as exc:
            return ToolResult(success=False, error=f"Facebook upload request error: {exc}")

        if resp.status_code != 200:
            return ToolResult(
                success=False,
                error=f"Facebook Suite API returned HTTP {resp.status_code}: {resp.text[:300]}",
            )

        try:
            res_json = resp.json()
        except Exception as json_err:
            return ToolResult(success=False, error=f"Invalid JSON response from Facebook adapter: {json_err}")

        if res_json.get("status") == "error":
            err_msg = res_json.get("details", {}).get("error", {}).get("message") or res_json.get("message") or "Upload error"
            return ToolResult(success=False, error=f"Facebook upload failed: {err_msg}")

        video_id = str(res_json.get("video_id") or res_json.get("publish_result", {}).get("id") or "")
        resolved_target = str(res_json.get("target_id") or target_id or "")
        video_url = f"https://facebook.com/{resolved_target}/videos/{video_id}" if video_id and resolved_target else None
        status = "scheduled" if scheduled_epoch else "published"
        timestamp = datetime.now(timezone.utc).isoformat()

        log_entry: dict[str, Any] = {
            "platform": "facebook",
            "status": status,
            "timestamp": timestamp,
            "video_id": video_id,
            "target_id": resolved_target,
            "video_url": video_url,
            "auto_translate_enabled": bool(enable_auto_translate),
            "translated_languages": translated_languages,
            "metadata_used": {"caption": caption, "title": title},
        }
        if scheduled_epoch:
            log_entry["scheduled_publish_time"] = scheduled_epoch

        result_data: dict[str, Any] = {
            "publish_log": {"version": "1.0", "entries": [log_entry]},
            "status": status,
            "facebook_post_id": video_id,
            "video_id": video_id,
            "target_id": resolved_target,
            "video_url": video_url,
            "auto_translate_enabled": bool(enable_auto_translate),
        }
        if scheduled_epoch:
            result_data["scheduled_publish_time"] = scheduled_epoch

        return ToolResult(success=True, data=result_data, artifacts=[str(video_path)])
