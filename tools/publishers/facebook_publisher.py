"""Facebook Business Suite / Creator Studio Adapter Publisher Tool for OpenMontage.

Publishes videos and Reels to Facebook Pages via Toolcase Gateway (/custom/facebook)
with automated multi-language AI dubbing / translation (14 languages enabled by default)
and native post scheduling (scheduled_publish_time) between 10m and 75d in advance.

Follows /home/ubuntu/toolcase-gateway-rs/.gw_state/modules/facebook-suite/README.md
and SCHEDULING_AND_AUTO_TRANSLATE_GUIDE.md.
Deploys on server SSH using port 20129.
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

DEFAULT_GATEWAY_PORT = 20129
MIME_APPLICATION_JSON = "application/json"
DEFAULT_GATEWAY_URL = f"http://127.0.0.1:{DEFAULT_GATEWAY_PORT}/custom/facebook"
DEFAULT_14_LANGUAGES = [
    "en_US", "vi_VN", "hi_IN", "ar_AR", "pt_BR", "es_LA", "fr_FR",
    "bn_IN", "id_ID", "th_TH", "te_IN", "ta_IN", "mr_IN", "kn_IN",
]


class FacebookPublisher(BaseTool):
    name = "facebook_publisher"
    version = "1.1.0"
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
        "2. Configure Meta Business Suite cookie in Gateway Dashboard or config.json (port 20129).\n"
        "Configured via TOOLCASE_GATEWAY_URL or FACEBOOK_GATEWAY_BASE_URL."
    )

    agent_skills = []
    capabilities = ["facebook_upload", "reels_publish", "auto_translate", "scheduled_publish", "chunked_upload"]
    supports = {
        "local_offline": False,
        "free": True,
        "uploads": True,
        "auto_dubbing": True,
        "native_scheduling": True,
        "chunked_upload": True,
    }
    best_for = [
        "direct Facebook video upload & Reels publishing via Toolcase Gateway on port 20129",
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
            "publish_type": {
                "type": "string",
                "enum": ["REEL", "FEED", "STORY"],
                "default": "REEL",
                "description": "Content type to publish: REEL, FEED (video post), or STORY.",
            },
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
        """Resolve and validate the configured Facebook Gateway base URL.

        Ensures port 20129 is enforced when deployed on the server.
        """
        inputs = inputs or {}
        configured = (
            inputs.get("gateway_url")
            or os.environ.get("FACEBOOK_GATEWAY_BASE_URL")
            or os.environ.get("META_GATEWAY_BASE_URL")
        )
        if not configured:
            toolcase_gw = os.environ.get(
                "TOOLCASE_GATEWAY_URL", f"http://127.0.0.1:{DEFAULT_GATEWAY_PORT}"
            ).strip().rstrip("/")
            configured = f"{toolcase_gw}/custom/facebook"

        base_url = configured.strip().rstrip("/")
        # Port normalization: change 28130 from doc examples to 20129 on server deployment
        if ":28130" in base_url:
            logger.info("Normalizing Facebook Suite gateway port from 28130 to server port 20129")
            base_url = base_url.replace(":28130", f":{DEFAULT_GATEWAY_PORT}")

        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid Facebook Gateway URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError(f"Missing hostname in Facebook Gateway URL: {base_url}")
        return base_url

    def check_readiness(self, base_url: Optional[str] = None) -> dict[str, Any]:
        """Check status and readiness of the Facebook Suite adapter."""
        url = base_url or self.get_gateway_base_url()
        for ep in (f"{url}/v1/status", f"{url}/status"):
            try:
                resp = self._session.get(ep, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return {"module": "facebook-suite", "status": "unknown", "configured": False}

    def get_scopes(self, base_url: Optional[str] = None) -> dict[str, Any]:
        """List accessible Facebook Pages and identities via /v1/scopes."""
        url = base_url or self.get_gateway_base_url()
        for ep in (f"{url}/v1/scopes", f"{url}/scopes"):
            try:
                resp = self._session.get(ep, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return {"error": {"code": 503, "message": "Failed to fetch Facebook scopes"}}

    def get_config(self, base_url: Optional[str] = None) -> dict[str, Any]:
        """View active masked module configuration via /v1/config."""
        url = base_url or self.get_gateway_base_url()
        for ep in (f"{url}/v1/config", f"{url}/config"):
            try:
                resp = self._session.get(ep, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return {"error": "Failed to retrieve Facebook configuration"}

    def import_har(self, har_data: str | Path | dict, base_url: Optional[str] = None) -> dict[str, Any]:
        """Import HAR capture to auto-extract credentials via /v1/config/har."""
        url = base_url or self.get_gateway_base_url()
        raw_body = ""
        if isinstance(har_data, Path) or (isinstance(har_data, str) and Path(har_data).is_file()):
            raw_body = Path(har_data).read_text(encoding="utf-8")
        elif isinstance(har_data, dict):
            raw_body = json.dumps(har_data)
        else:
            raw_body = str(har_data)
        for ep in (f"{url}/v1/config/har", f"{url}/config/har"):
            try:
                resp = self._session.post(
                    ep,
                    data=raw_body.encode("utf-8"),
                    headers={"Content-Type": MIME_APPLICATION_JSON},
                    timeout=30,
                )
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return {"error": "Failed to import HAR file to Facebook Suite"}

    def check_video_published(self, video_id: str, base_url: Optional[str] = None) -> dict[str, Any] | None:
        """Check if video/post exists and is published."""
        if not video_id:
            return None
        url = base_url or self.get_gateway_base_url()
        for ep in (f"{url}/v1/status/{video_id}", f"{url}/status/{video_id}", f"{url}/v1/video/{video_id}"):
            try:
                resp = self._session.get(ep, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status") or ("published" if data.get("published") else None)
                    if status == "published":
                        return {
                            "platform": "facebook",
                            "video_id": str(video_id),
                            "status": "published",
                            "gateway_url": url,
                            "details": data,
                        }
            except Exception:
                continue
        return None

    def publish_status(
        self,
        message: str,
        target_id: Optional[str] = None,
        scheduled_publish_time: Optional[int] = None,
        base_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Publish text or status update to Facebook Page via /v1/publish/status."""
        url = base_url or self.get_gateway_base_url()
        payload: dict[str, Any] = {"message": message}
        if target_id:
            payload["target_id"] = target_id
        if scheduled_publish_time:
            payload["scheduled_publish_time"] = scheduled_publish_time
        for ep in (f"{url}/v1/publish/status", f"{url}/publish/status", f"{url}/feed/post"):
            try:
                resp = self._session.post(ep, json=payload, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (404, 405):
                    continue
                try:
                    return resp.json()
                except Exception:
                    return {"error": f"Status post failed with HTTP {resp.status_code}: {resp.text[:200]}"}
            except requests.exceptions.ConnectionError:
                continue
            except Exception as e:
                return {"error": f"Status post interrupted or ambiguous: {e}"}
        return {"error": "Failed to publish Facebook status"}

    def _validate_execution_params(
        self, inputs: dict[str, Any]
    ) -> tuple[Optional[ToolResult], Optional[Path], str, str, str, str, Optional[int]]:
        if "video_path" not in inputs:
            return ToolResult(success=False, error="Missing required input: video_path"), None, "", "", "", "", None

        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}"), None, "", "", "", "", None

        caption = str(inputs.get("caption") or inputs.get("description") or "").strip()
        title = str(inputs.get("title") or "").strip()
        if not caption and not title:
            return ToolResult(success=False, error="Missing caption or title for Facebook post"), None, "", "", "", "", None

        target_id = str(inputs.get("target_id") or inputs.get("page_id") or os.environ.get("FB_PAGE_ID") or "").strip()
        publish_type = str(inputs.get("publish_type") or "REEL").upper()

        raw_sched = inputs.get("scheduled_publish_time") or inputs.get("schedule_time")
        scheduled_epoch: Optional[int] = None
        if raw_sched is not None:
            try:
                scheduled_epoch = int(raw_sched)
            except (ValueError, TypeError):
                return ToolResult(success=False, error=f"Invalid scheduled_publish_time: {raw_sched}"), None, "", "", "", "", None
            now_sec = int(time.time())
            min_sec = now_sec + 600  # 10 minutes
            max_sec = now_sec + 6480000  # 75 days
            if not (min_sec <= scheduled_epoch <= max_sec):
                return (
                    ToolResult(
                        success=False,
                        error=f"scheduled_publish_time ({scheduled_epoch}) must be between 10m and 75d in advance (range {min_sec}-{max_sec})",
                    ),
                    None, "", "", "", "", None,
                )

        return None, video_path, caption, title, target_id, publish_type, scheduled_epoch

    def _try_fallback_endpoints(
        self, base_url: str, payload: dict[str, Any], headers: dict[str, str], condition: str = "status"
    ) -> Optional[requests.Response]:
        for alt in (f"{base_url}/v1/publish", f"{base_url}/upload/video", f"{base_url}/publish"):
            try:
                resp = self._session.post(alt, json=payload, headers=headers, timeout=300)
                if condition == "status" and resp.status_code == 200:
                    return resp
                if condition == "not_404" and resp.status_code != 404:
                    return resp
            except Exception:
                continue
        return None

    def _post_video_upload(
        self, base_url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> tuple[Optional[requests.Response], Optional[str]]:
        upload_url = f"{base_url}/v1/upload/video"
        resp = None
        try:
            resp = self._session.post(upload_url, json=payload, headers=headers, timeout=300)
        except requests.exceptions.ConnectTimeout as conn_err:
            resp = self._try_fallback_endpoints(base_url, payload, headers, condition="status")
            if resp is None:
                err_msg = (
                    f"Failed to connect to Facebook Gateway at {base_url}: {conn_err}\n"
                    f"Please verify toolcase-gateway-rs is running on port {DEFAULT_GATEWAY_PORT} with facebook-suite enabled."
                )
                return None, err_msg
        except requests.exceptions.ConnectionError as conn_err:
            if "Connection refused" in str(conn_err):
                resp = self._try_fallback_endpoints(base_url, payload, headers, condition="status")
            if resp is None:
                err_msg = (
                    f"Connection failed or aborted during upload to Facebook Gateway at {base_url}: {conn_err}\n"
                    f"Please verify toolcase-gateway-rs is running on port {DEFAULT_GATEWAY_PORT} with facebook-suite enabled."
                )
                return None, err_msg
        except Exception as exc:
            return None, f"Facebook upload request error: {exc}"

        if resp is not None and resp.status_code == 404:
            alt_resp = self._try_fallback_endpoints(base_url, payload, headers, condition="not_404")
            if alt_resp is not None:
                resp = alt_resp

        return resp, None

    def _extract_upload_result(
        self, res_json: dict[str, Any], target_id: str
    ) -> tuple[Optional[str], str, str, Optional[str]]:
        if res_json.get("status") == "error":
            err_msg = (
                res_json.get("details", {}).get("error", {}).get("message")
                or res_json.get("message")
                or "Upload error"
            )
            return err_msg, "", "", None

        if "error" in res_json and res_json["error"]:
            err = res_json["error"]
            err_msg = err.get("message") if isinstance(err, dict) else str(err)
            return err_msg, "", "", None

        pub_res = res_json.get("publish_result") or {}
        video_id = str(
            res_json.get("video_id")
            or res_json.get("id")
            or res_json.get("post_id")
            or pub_res.get("id")
            or pub_res.get("video_id")
            or ""
        )
        resolved_target = str(res_json.get("target_id") or target_id or "")
        video_url = res_json.get("video_url")
        if not video_url and video_id and resolved_target:
            video_url = f"https://facebook.com/{resolved_target}/videos/{video_id}"
        elif not video_url and video_id:
            video_url = f"https://facebook.com/watch/?v={video_id}"

        return None, video_id, resolved_target, video_url

    def _read_video_base64(self, video_path: Path) -> tuple[Optional[str], Optional[str]]:
        """Read video bytes and encode to base64 for universal gateway compatibility."""
        try:
            with open(video_path, "rb") as vf:
                v_bytes = vf.read()
            return base64.b64encode(v_bytes).decode("ascii"), None
        except Exception as read_err:
            return None, f"Failed to read video file: {read_err}"

    def _build_upload_payload(
        self,
        v_b64: str,
        video_path: Path,
        caption: str,
        title: str,
        publish_type: str,
        enable_auto_translate: bool,
        translated_languages: list[str],
        target_id: str,
        scheduled_epoch: Optional[int],
    ) -> dict[str, Any]:
        """Construct the upload payload dictionary for the Gateway adapter."""
        payload: dict[str, Any] = {
            "video_base64": v_b64,
            "file_name": video_path.name,
            "title": title or caption[:100],
            "description": caption or title,
            "publish_type": publish_type,
            "enable_auto_translate": bool(enable_auto_translate),
            "translated_languages": translated_languages,
        }
        if target_id:
            payload["target_id"] = target_id
        if scheduled_epoch is not None:
            payload["scheduled_publish_time"] = scheduled_epoch
        return payload

    def _build_publish_result(
        self,
        video_path: Path,
        video_id: str,
        resolved_target: str,
        video_url: Optional[str],
        publish_type: str,
        enable_auto_translate: bool,
        translated_languages: list[str],
        caption: str,
        title: str,
        scheduled_epoch: Optional[int],
    ) -> ToolResult:
        """Construct the final ToolResult after successful upload and registration."""
        status = "scheduled" if scheduled_epoch else "published"
        timestamp = datetime.now(timezone.utc).isoformat()

        log_entry: dict[str, Any] = {
            "platform": "facebook",
            "status": status,
            "timestamp": timestamp,
            "video_id": video_id,
            "target_id": resolved_target,
            "video_url": video_url,
            "publish_type": publish_type,
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
            "publish_type": publish_type,
            "auto_translate_enabled": bool(enable_auto_translate),
        }
        if scheduled_epoch:
            result_data["scheduled_publish_time"] = scheduled_epoch

        return ToolResult(success=True, data=result_data, artifacts=[str(video_path)])

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        """Upload video to Facebook Page with optional scheduling and auto-dubbing."""
        err_res, video_path, caption, title, target_id, publish_type, scheduled_epoch = self._validate_execution_params(inputs)
        if err_res is not None or video_path is None:
            return err_res or ToolResult(success=False, error="Invalid parameters")

        enable_auto_translate = inputs.get("enable_auto_translate", True)
        translated_languages = inputs.get("translated_languages") or DEFAULT_14_LANGUAGES

        try:
            base_url = self.get_gateway_base_url(inputs)
        except ValueError as err:
            return ToolResult(success=False, error=str(err))

        v_b64, read_err = self._read_video_base64(video_path)
        if read_err or v_b64 is None:
            return ToolResult(success=False, error=read_err or "Failed to read video file")

        headers = {"Content-Type": MIME_APPLICATION_JSON, "Accept": MIME_APPLICATION_JSON}
        payload = self._build_upload_payload(
            v_b64=v_b64,
            video_path=video_path,
            caption=caption,
            title=title,
            publish_type=publish_type,
            enable_auto_translate=bool(enable_auto_translate),
            translated_languages=translated_languages,
            target_id=target_id,
            scheduled_epoch=scheduled_epoch,
        )

        resp, err_msg = self._post_video_upload(base_url, payload, headers)
        if err_msg or resp is None:
            return ToolResult(success=False, error=err_msg or "Failed to upload to Facebook")

        if resp.status_code != 200:
            return ToolResult(
                success=False,
                error=f"Facebook Suite API returned HTTP {resp.status_code}: {resp.text[:300]}",
            )

        try:
            res_json = resp.json()
        except Exception as json_err:
            return ToolResult(success=False, error=f"Invalid JSON response from Facebook adapter: {json_err}")

        extract_err, video_id, resolved_target, video_url = self._extract_upload_result(res_json, target_id)
        if extract_err:
            return ToolResult(success=False, error=f"Facebook upload failed: {extract_err}")

        return self._build_publish_result(
            video_path=video_path,
            video_id=video_id,
            resolved_target=resolved_target,
            video_url=video_url,
            publish_type=publish_type,
            enable_auto_translate=bool(enable_auto_translate),
            translated_languages=translated_languages,
            caption=caption,
            title=title,
            scheduled_epoch=scheduled_epoch,
        )
