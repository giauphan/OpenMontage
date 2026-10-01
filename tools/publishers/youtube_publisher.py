"""YouTube Official API Publisher Tool for OpenMontage.

Uploads videos directly to YouTube via official YouTube Data API v3.
Free quota: 10,000 units/day (~6 video uploads/day).
Supports headless OAuth authentication via console link or browser flow.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class YoutubePublisher(BaseTool):
    name = "youtube_publisher"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "youtube"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = [
        "env:YOUTUBE_CLIENT_SECRET_FILE",
        "python:googleapiclient",
        "python:google_auth_oauthlib",
    ]
    install_instructions = (
        "1. Create OAuth 2.0 Client ID (Desktop app) in Google Cloud Console with YouTube Data API v3 enabled.\n"
        "2. Download credentials JSON and set YOUTUBE_CLIENT_SECRET_FILE=/path/to/client_secret.json in .env\n"
        "3. Install dependencies: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
    )

    agent_skills = []

    capabilities = ["youtube_upload", "write_publish_log"]
    supports = {
        "local_offline": False,
        "free": True,
        "uploads": True,
    }
    best_for = [
        "direct automatic video upload to YouTube / YouTube Shorts",
        "setting YouTube title, description, tags, category, and privacy status",
        "setting video thumbnail and chapter metadata",
    ]
    not_good_for = [
        "offline publishing without internet or OAuth setup",
        "bypassing YouTube daily API quota limits",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "title"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to the final rendered video MP4 file.",
            },
            "title": {"type": "string", "description": "Video title (max 100 chars)."},
            "description": {"type": "string", "description": "Video description with chapters & hashtags."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "privacy_status": {
                "type": "string",
                "enum": ["public", "private", "unlisted"],
                "default": "unlisted",
            },
            "category_id": {
                "type": "string",
                "description": "YouTube category ID (e.g., '27' for Education, '28' for Science & Tech, '24' for Entertainment). Default is '28'.",
                "default": "28",
            },
            "thumbnail_path": {"type": "string", "description": "Optional custom thumbnail image path."},
            "publish_at": {
                "type": "string",
                "description": "Optional RFC3339 UTC publish time. If set, video is uploaded private and scheduled.",
            },
            "token_storage_path": {
                "type": "string",
                "description": "Optional path to store OAuth token.json. Defaults to '~/.openmontage/youtube_token.json'.",
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "video_id": {"type": "string"},
            "video_url": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True
    )
    side_effects = ["uploads video to user YouTube account"]
    user_visible_verification = [
        "Check YouTube Studio or the returned video URL to verify the uploaded video and metadata",
    ]

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    def _get_authenticated_service(self, client_secret_file: Path, token_file: Path, interactive: bool = True):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if token_file.is_file():
            try:
                creds = Credentials.from_authorized_user_file(str(token_file), self.SCOPES)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secret_file), self.SCOPES
                )
                flow.redirect_uri = "http://localhost:8080/"
                auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
                if not interactive:
                    raise ValueError(f"AUTH_REQUIRED: Please authenticate by visiting:\n{auth_url}")
                try:
                    creds = flow.run_local_server(port=8080, open_browser=False)
                except Exception as e:
                    raise ValueError(f"AUTH_REQUIRED: Please authenticate by visiting:\n{auth_url}") from e

            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")

        return build("youtube", "v3", credentials=creds)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        from tools.publishers.platform_routes import ensure_vertical, ensure_youtube_short

        try:
            ensure_vertical(video_path)
            ensure_youtube_short(video_path)
        except ValueError as geom_err:
            return ToolResult(success=False, error=str(geom_err))

        secret_file_str = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "")
        if not secret_file_str:
            return ToolResult(
                success=False,
                error="YOUTUBE_CLIENT_SECRET_FILE environment variable not set.",
            )
        secret_file = Path(secret_file_str).expanduser()
        if not secret_file.is_file():
            return ToolResult(
                success=False,
                error=f"Client secret file not found at: {secret_file}",
            )

        token_path_str = inputs.get(
            "token_storage_path", "~/.openmontage/youtube_token.json"
        )
        token_file = Path(token_path_str).expanduser()

        title = inputs["title"][:100]
        description = inputs.get("description", "")
        tags = inputs.get("tags", [])
        privacy_status = inputs.get("privacy_status", "unlisted")
        if privacy_status == "public":
            # Public publishing disallowed by policy — default to unlisted (draft mode)
            privacy_status = "unlisted"
        publish_at = inputs.get("publish_at")
        if publish_at:
            privacy_status = "private"
        category_id = inputs.get("category_id", "28")

        try:
            from googleapiclient.http import MediaFileUpload

            youtube = self._get_authenticated_service(secret_file, token_file)

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "categoryId": category_id,
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }
            if publish_at:
                body["status"]["publishAt"] = publish_at

            media = MediaFileUpload(
                str(video_path),
                chunksize=1024 * 1024 * 5,
                resumable=True,
                mimetype="video/*",
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()

            video_id = response.get("id")
            video_url = f"https://youtu.be/{video_id}"

            # Upload thumbnail if provided (handled gracefully if channel lacks custom thumbnail feature)
            thumb_in = inputs.get("thumbnail_path")
            if thumb_in and video_id:
                thumb_path = Path(thumb_in).expanduser()
                if thumb_path.is_file():
                    try:
                        youtube.thumbnails().set(
                            videoId=video_id,
                            media_body=MediaFileUpload(str(thumb_path)),
                        ).execute()
                    except Exception as e:
                        print(f"Warning: Custom thumbnail upload skipped ({e})")

            timestamp = datetime.now(timezone.utc).isoformat()
            entry = {
                "platform": "youtube",
                "status": "published",
                "url": video_url,
                "video_id": video_id,
                "visibility": privacy_status,
                "timestamp": timestamp,
                "metadata_used": {
                    "title": title,
                    "description": description,
                    "publish_at": publish_at,
                },
            }

            publish_log = {"version": "1.0", "entries": [entry]}

            return ToolResult(
                success=True,
                data={
                    "publish_log": publish_log,
                    "video_id": video_id,
                    "video_url": video_url,
                },
                artifacts=[str(video_path)],
            )

        except ValueError as val_err:
            msg = str(val_err)
            if "AUTH_REQUIRED" in msg:
                return ToolResult(
                    success=False,
                    error=msg,
                    data={"auth_required": True},
                )
            return ToolResult(success=False, error=msg)
        except Exception as exc:
            return ToolResult(
                success=False, error=f"YouTube upload failed: {str(exc)}"
            )

    def check_video_published(self, video_id: str) -> dict[str, Any]:
        """Check status of a YouTube video via YouTube Data API v3 for reconciliation.

        Returns a dict distinguishing unavailable/error/not-found from authoritative status.
        """
        try:
            secret_file_str = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "")
            if not secret_file_str:
                return {"status": "unavailable", "error_type": "missing_config", "error": "YOUTUBE_CLIENT_SECRET_FILE missing"}
            secret_file = Path(secret_file_str).expanduser()
            token_path_str = os.environ.get("YOUTUBE_TOKEN_PATH", "~/.openmontage/youtube_token.json")
            token_file = Path(token_path_str).expanduser()
            if not secret_file.is_file() or not token_file.is_file():
                return {
                    "status": "unavailable",
                    "error_type": "missing_credentials",
                    "error": f"Missing credential files: secret={secret_file.is_file()}, token={token_file.is_file()}",
                }

            from googleapiclient.errors import HttpError
            service = self._get_authenticated_service(secret_file, token_file, interactive=False)
            req = service.videos().list(part="status,snippet", id=video_id)
            res = req.execute()
            items = res.get("items", [])
            if items:
                status = items[0].get("status", {})
                snippet = items[0].get("snippet", {})
                return {
                    "status": "found",
                    "video_id": video_id,
                    "privacy_status": status.get("privacyStatus"),
                    "upload_status": status.get("uploadStatus"),
                    "publish_at": status.get("publishAt"),
                    "channel_id": snippet.get("channelId"),
                    "title": snippet.get("title"),
                }
            return {"status": "not_found", "video_id": video_id}
        except Exception as exc:
            # Fallback for read-only reconciliation: Check public visibility via YouTube oEmbed API
            # This does not require OAuth scopes and definitively proves if a video is publicly accessible.
            try:
                import urllib.request
                import json as _json
                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = _json.loads(resp.read().decode("utf-8"))
                        return {
                            "status": "unverified_oembed",
                            "video_id": video_id,
                            "title": data.get("title"),
                            "author_name": data.get("author_name"),
                            "via_oembed": True,
                        }
            except Exception:
                pass

            error_str = str(exc)
            status_code = None
            error_type = "exception"
            if "HttpError" in str(type(exc)):
                error_type = "http_error"
                status_code = getattr(getattr(exc, "resp", None), "status", getattr(exc, "status_code", None))
            elif "AUTH_REQUIRED" in error_str:
                error_type = "auth_required"

            return {
                "status": "error",
                "error_type": error_type,
                "status_code": status_code,
                "error": error_str[:200],
            }
