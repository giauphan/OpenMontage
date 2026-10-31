"""TikTok Creator Studio Adapter Publisher Tool for OpenMontage.

Publishes vertical videos to TikTok Creator Studio via Toolcase Gateway
(POST /tiktok/v1/publish, GET /tiktok/v1/upload/auth, GET /tiktok/v1/user,
GET /tiktok/v1/status) or directly through the TikTok Creator Studio Adapter.

Follows the TikTok Creator Studio Adapter Specification:
https://github.com/giauphan/TikTok-Creator-Studio-Adapter/blob/main/docs/PUBLISHING.md
"""

from __future__ import annotations

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
    ToolStatus,
    ToolTier,
)

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:20129/tiktok"
VALID_VISIBILITIES = {"only-me", "public", "friends"}


class TiktokPublisher(BaseTool):
    name = "tiktok_publisher"
    version = "1.0.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "tiktok"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = [
        "python:requests",
    ]
    install_instructions = (
        "1. Ensure Toolcase Gateway is running on port 20129 with tiktok-studio enabled.\n"
        "2. Configure TikTok session cookie in Gateway Dashboard or via ~/.openmontage/tiktok_cookies.json.\n"
        "Configured via TIKTOK_GATEWAY_BASE_URL (default: http://127.0.0.1:20129/tiktok)."
    )

    agent_skills = []
    capabilities = ["tiktok_upload", "write_publish_log", "creator_studio"]
    supports = {"local_offline": False, "free": True, "uploads": True, "creator_studio_adapter": True}
    best_for = [
        "direct video upload to TikTok Creator Studio via Toolcase Gateway",
        "setting TikTok video caption, hashtags, and privacy/visibility",
        "publishing without enterprise API approval using session cookies",
    ]
    not_good_for = ["offline publishing without internet"]

    input_schema = {
        "type": "object",
        "required": ["video_path", "caption"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to the vertical 9:16 video MP4 file.",
            },
            "caption": {
                "type": "string",
                "description": "Video caption / description including hashtags.",
            },
            "title": {
                "type": "string",
                "description": "Optional video title.",
            },
            "visibility": {
                "type": "string",
                "enum": ["only-me", "public", "friends"],
                "default": "only-me",
                "description": "Video visibility setting (default: only-me / private).",
            },
            "allow_comment": {
                "type": "boolean",
                "default": True,
                "description": "Whether to allow user comments.",
            },
            "allow_duet": {"type": "boolean", "default": False},
            "allow_stitch": {"type": "boolean", "default": False},
            "schedule_time": {"type": "integer", "description": "Optional Unix timestamp for scheduled post."},
            "scheduled_publish_time": {"type": "integer", "description": "Alias for schedule_time."},
            "gateway_url": {"type": "string", "description": "Custom Gateway base URL."},
            "cookie_path": {"type": "string", "description": "Path to TikTok cookies JSON file."},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "status": {"type": "string"},
            "project_id": {"type": "string"},
            "item_id": {"type": "string"},
            "video_url": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout", "network_error"])
    side_effects = ["uploads video to user TikTok account via Creator Studio"]
    user_visible_verification = [
        "Check TikTok Creator Studio or TikTok profile to verify the uploaded video",
    ]

    def __init__(self, http_session: Optional[requests.Session] = None):
        super().__init__()
        self._session = http_session or requests.Session()
        if http_session is None:
            self._session.trust_env = False

    def get_gateway_base_url(self, inputs: Optional[dict[str, Any]] = None) -> str:
        """Resolve and validate the configured TikTok Gateway base URL."""
        inputs = inputs or {}
        configured = (
            inputs.get("gateway_url")
            or os.environ.get("TIKTOK_GATEWAY_BASE_URL")
            or os.environ.get("TIKTOK_API_BASE_URL")
        )
        if not configured:
            toolcase_gw = os.environ.get("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129").strip().rstrip("/")
            configured = f"{toolcase_gw}/tiktok"

        base_url = configured.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid TikTok Gateway URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError(f"Missing hostname in TikTok Gateway URL: {base_url}")
        return base_url

    def _normalize_cookie_list_to_header(self, raw_data: Any) -> tuple[str, str]:
        """Convert cookie list or storage state dict into Cookie string and CSRF token."""
        cookie_pairs = []
        csrf_token = ""
        cookies = raw_data.get("cookies", []) if isinstance(raw_data, dict) else (raw_data if isinstance(raw_data, list) else [])

        for item in cookies:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            value = item.get("value", "").strip()
            if name and value:
                cookie_pairs.append(f"{name}={value}")
                if name in ("tt_csrf_token", "x-tt-csrf-token", "csrf_session_id") and not csrf_token:
                    csrf_token = value

        return "; ".join(cookie_pairs), csrf_token

    def _resolve_auth_headers(self, inputs: dict[str, Any]) -> dict[str, str]:
        """Extract Cookie and CSRF headers from input overrides or cookie files."""
        headers: dict[str, str] = {}
        cookie_path_str = (
            inputs.get("cookie_path")
            or os.environ.get("TIKTOK_COOKIE_FILE")
            or "~/.openmontage/tiktok_cookies.json"
        )
        cookie_path = Path(cookie_path_str).expanduser()

        if cookie_path.is_file():
            try:
                with open(cookie_path, encoding="utf-8") as f:
                    raw_data = json.load(f)
                cookie_str, csrf = self._normalize_cookie_list_to_header(raw_data)
                if cookie_str:
                    headers["Cookie"] = cookie_str
                if csrf:
                    headers["x-tt-csrf-token"] = csrf
                    headers["tt-csrf-token"] = csrf
            except Exception as exc:
                logger.warning("Failed to parse TikTok cookie file %s: %s", cookie_path, exc)

        if inputs.get("session_cookie"):
            headers["Cookie"] = str(inputs["session_cookie"]).strip()
        if inputs.get("csrf_token"):
            token = str(inputs["csrf_token"]).strip()
            headers["x-tt-csrf-token"] = token
            headers["tt-csrf-token"] = token

        return headers

    def check_readiness(self, base_url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        """Check status and readiness of the TikTok Creator Studio adapter."""
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)

        endpoints = [f"{base_url}/v1/status", f"{base_url}/status"]
        for ep in endpoints:
            try:
                resp = self._session.get(ep, headers=req_headers, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue

        return {"module": "tiktok-studio", "status": "unknown", "configured": False}

    def check_video_published(self, video_id: str, gateway_url: Optional[str] = None) -> dict[str, Any]:
        """Verify if a video is published in the TikTok Creator Studio library."""
        clean_id = str(video_id).strip()
        if not clean_id:
            return {"status": "not_found", "error": "empty_video_id"}

        base_url = self.get_gateway_base_url({"gateway_url": gateway_url} if gateway_url else None)
        headers = self._resolve_auth_headers({})
        headers["Accept"] = "application/json"

        endpoints = [
            f"{base_url}/v1/items?count=50",
            f"{base_url}/items?count=50",
        ]

        for url in endpoints:
            try:
                resp = self._session.get(url, headers=headers, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    for item in items:
                        item_id = str(item.get("id") or item.get("item_id") or "")
                        if item_id == clean_id:
                            stats = item.get("stats", {})
                            return {
                                "status": "published",
                                "video_id": clean_id,
                                "play_count": stats.get("play_count", 0),
                                "like_count": stats.get("like_count", 0),
                                "comment_count": stats.get("comment_count", 0),
                                "share_count": stats.get("share_count", 0),
                                "item": item,
                            }
                    return {"status": "not_found", "video_id": clean_id}
            except Exception as exc:
                logger.warning("Error checking published video %s: %s", clean_id, exc)

        return {"status": "unverified", "video_id": clean_id}

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        """Publish vertical video to TikTok Creator Studio."""
        if "video_path" not in inputs:
            return ToolResult(success=False, error="Missing required input: video_path")

        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        caption = str(inputs.get("caption") or "").strip()
        title = str(inputs.get("title") or "").strip()
        if not caption and not title:
            return ToolResult(success=False, error="Missing caption or title for TikTok post")

        if caption:
            from lib.artifact_paths import is_english_locale
            from lib.language_validation import get_language_validator, VIETNAMESE_DIACRITICS
            locale = inputs.get("locale")
            if not locale:
                if any(ch in VIETNAMESE_DIACRITICS for ch in caption):
                    locale = "vi-VN"
                else:
                    locale = os.environ.get("OPENMONTAGE_LOCALE", "en-US")
            validator = get_language_validator(locale)
            caption_errors = validator.validate_prose(caption)
            if caption_errors:
                lang = "English" if is_english_locale(locale) else "Vietnamese"
                return ToolResult(
                    success=False,
                    error=f"Invalid TikTok caption (non-{lang} prose): {caption_errors[0]}",
                )

        from tools.publishers.platform_routes import ensure_vertical
        try:
            ensure_vertical(video_path)
        except ValueError as geom_err:
            return ToolResult(success=False, error=str(geom_err))

        raw_sched = inputs.get("schedule_time") if inputs.get("schedule_time") is not None else inputs.get("scheduled_publish_time")
        schedule_time: Optional[int] = None
        if raw_sched is not None:
            try:
                schedule_time = int(raw_sched)
            except (ValueError, TypeError):
                return ToolResult(success=False, error=f"Invalid schedule_time: {raw_sched}")
            now_sec = int(time.time())
            min_sec = now_sec + 900
            max_sec = now_sec + 864000
            if not (min_sec <= schedule_time <= max_sec):
                return ToolResult(
                    success=False,
                    error=f"schedule_time ({schedule_time}) must be between 15m and 10d in advance (range {min_sec}-{max_sec})",
                )

        if "visibility" in inputs and inputs["visibility"]:
            visibility = str(inputs["visibility"]).lower().strip()
        elif schedule_time is not None:
            visibility = "public"
        else:
            visibility = str(os.environ.get("TIKTOK_DEFAULT_VISIBILITY") or "only-me").lower().strip()
        if visibility not in VALID_VISIBILITIES:
            visibility = "public" if schedule_time else "only-me"

        allow_comment = bool(inputs.get("allow_comment", True))
        allow_duet = bool(inputs.get("allow_duet", False))
        allow_stitch = bool(inputs.get("allow_stitch", False))

        try:
            base_url = self.get_gateway_base_url(inputs)
        except ValueError as val_err:
            return ToolResult(success=False, error=str(val_err))

        headers = self._resolve_auth_headers(inputs)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        # Build publishing payload matching TikTok Creator Studio Adapter spec
        vpath_resolved = video_path.resolve()
        vpath_str = str(vpath_resolved)
        if vpath_str.startswith("/app/"):
            host_root = os.environ.get("OPENMONTAGE_HOST_ROOT", "/home/ubuntu/OpenMontage")
            vpath_str = str(Path(host_root) / vpath_resolved.relative_to("/app"))

        publish_payload: dict[str, Any] = {
            "video_path": vpath_str,
            "text": caption or title,
            "title": title or "",
            "visibility": visibility,
            "allow_comment": allow_comment,
            "allow_duet": allow_duet,
            "allow_stitch": allow_stitch,
        }
        if schedule_time is not None:
            publish_payload["schedule_time"] = schedule_time

        publish_url = f"{base_url}/v1/publish"

        try:
            resp = self._session.post(publish_url, json=publish_payload, headers=headers, timeout=120)
        except requests.exceptions.ConnectionError as conn_err:
            # Fallback to alternative namespace or provide informative diagnostic
            alt_url = f"{base_url}/publish"
            try:
                resp = self._session.post(alt_url, json=publish_payload, headers=headers, timeout=120)
            except Exception:
                return ToolResult(
                    success=False,
                    error=(
                        f"Failed to connect to TikTok Gateway at {base_url}: {conn_err}\n"
                        "Please verify toolcase-gateway-rs is running on port 20129 "
                        "and that the tiktok-studio module is enabled."
                    ),
                )
        except Exception as exc:
            return ToolResult(success=False, error=f"TikTok publish request error: {exc}")

        # Handle HTTP response codes per docs/PUBLISHING.md Section 6
        if resp.status_code == 401:
            return ToolResult(
                success=False,
                error="TikTok session expired or invalid (HTTP 401). Please update session cookie / CSRF token.",
            )
        if resp.status_code == 503:
            return ToolResult(
                success=False,
                error="TikTok Creator Studio module is currently disabled (HTTP 503). Enable it in Gateway.",
            )
        if resp.status_code != 200:
            return ToolResult(
                success=False,
                error=f"TikTok Creator Studio API returned HTTP {resp.status_code}: {resp.text[:300]}",
            )

        try:
            res_json = resp.json()
        except Exception as json_err:
            return ToolResult(success=False, error=f"Invalid JSON response from TikTok adapter: {json_err}")

        status_code = res_json.get("status_code", 0)
        if status_code != 0:
            err_msg = res_json.get("error", {}).get("message") or f"TikTok status_code: {status_code}"
            return ToolResult(success=False, error=f"TikTok post failed: {err_msg}")

        project_id = str(res_json.get("project_id") or "")
        item_id = str(res_json.get("item_id") or project_id)
        video_url = res_json.get("video_url") or (f"https://www.tiktok.com/video/{item_id}" if item_id else None)
        resp_status = str(res_json.get("status") or ("scheduled" if schedule_time else "published"))
        resp_schedule = res_json.get("schedule_time") or schedule_time

        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry: dict[str, Any] = {
            "platform": "tiktok",
            "status": resp_status,
            "timestamp": timestamp,
            "project_id": project_id,
            "item_id": item_id,
            "video_url": video_url,
            "visibility": visibility,
            "metadata_used": {"caption": caption, "title": title},
        }
        if resp_schedule:
            log_entry["schedule_time"] = resp_schedule

        result_data: dict[str, Any] = {
            "publish_log": {"version": "1.0", "entries": [log_entry]},
            "status": resp_status,
            "project_id": project_id,
            "item_id": item_id,
            "video_url": video_url,
            "visibility": visibility,
        }
        if resp_schedule:
            result_data["schedule_time"] = resp_schedule

        return ToolResult(
            success=True,
            data=result_data,
            artifacts=[str(video_path)],
        )
