"""Meta Publisher Tool for OpenMontage.

Uploads videos to Facebook Pages (as Reels or standard video) and Instagram Business Accounts (as Reels).
Requires Meta Graph API User Access Token in `TOKEN_FACEBOOK`.
Automatically handles Cloudflare R2 temporary public hosting & auto-cleanup for Instagram Reels.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
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


class MetaPublisher(BaseTool):
    name = "meta_publisher"
    version = "0.2.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "meta"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = [
        "env:TOKEN_FACEBOOK",
        "python:requests",
        "python:boto3",
    ]
    install_instructions = (
        "1. Create an App in Meta for Developers.\n"
        "2. Add Instagram Graph API and Facebook Login for Business.\n"
        "3. Generate an Access Token with required permissions.\n"
        "4. Set TOKEN_FACEBOOK=<token> in .env."
    )

    agent_skills = []

    capabilities = ["facebook_upload", "instagram_upload", "write_publish_log"]
    supports = {
        "local_offline": False,
        "free": True,
        "uploads": True,
    }
    best_for = [
        "direct automatic video upload to Facebook Page and Instagram Reels",
    ]
    not_good_for = [
        "offline publishing without internet",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "caption", "page_id"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to the video MP4 file.",
            },
            "caption": {
                "type": "string",
                "description": "Video caption / description including hashtags.",
            },
            "page_id": {
                "type": "string",
                "description": "Facebook Page ID.",
            },
            "post_to_facebook": {
                "type": "boolean",
                "default": True,
                "description": "Whether to publish to Facebook Page.",
            },
            "post_to_instagram": {
                "type": "boolean",
                "default": True,
                "description": "Whether to publish to connected Instagram Business Account via R2 temporary hosting.",
            },
            "video_url": {
                "type": "string",
                "description": "Optional custom public URL to the video file. If omitted and R2 is configured, R2 temp hosting will be used automatically.",
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "facebook_post_id": {"type": "string"},
            "instagram_media_id": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True
    )
    side_effects = ["uploads video to Facebook Page / Instagram"]
    user_visible_verification = [
        "Check Facebook Page or Instagram profile to verify the uploaded video",
    ]

    GRAPH_VERSION = "v26.0"
    GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

    def _get_page_info(self, user_token: str, page_id: str) -> dict[str, Any]:
        url = f"{self.GRAPH_URL}/{page_id}?fields=access_token,instagram_business_account&access_token={user_token}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def _upload_facebook_video(self, page_token: str, page_id: str, video_path: Path, caption: str) -> str:
        """Upload video to Facebook Page."""
        import requests

        url = f"{self.GRAPH_URL}/{page_id}/videos"
        with open(video_path, "rb") as f:
            files = {
                "source": (video_path.name, f, "video/mp4"),
            }
            data = {
                "access_token": page_token,
                "description": caption,
            }

            response = requests.post(url, data=data, files=files, timeout=300)
            resp_data = response.json()

        if "error" in resp_data:
            raise Exception(f"Facebook upload error: {resp_data['error']}")

        return resp_data.get("id")

    def _upload_to_r2(self, video_path: Path) -> tuple[str, str, Any]:
        """Upload video to Cloudflare R2 temporarily and return (presigned_url, object_key, s3_client)."""
        import boto3

        key_id = os.environ.get("CLOUDFLARE_R2_KEY_ID")
        secret_key = os.environ.get("CLOUDFLARE_R2_SECRET") or os.environ.get("CLOUDFLARE_R2_SERECT")
        endpoint = os.environ.get("CLOUDFLARE_R2_ENDPOINT", "")

        # Clean endpoint to get base S3 endpoint without bucket path
        if "/store-instagram" in endpoint:
            base_endpoint = endpoint.replace("/store-instagram", "").rstrip("/")
            bucket_name = "store-instagram"
        else:
            base_endpoint = endpoint.rstrip("/")
            bucket_name = os.environ.get("CLOUDFLARE_R2_BUCKET_NAME", "open-montage")

        if not (key_id and secret_key and base_endpoint):
            raise Exception("Cloudflare R2 environment variables are not fully configured.")

        s3 = boto3.client(
            "s3",
            endpoint_url=base_endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )

        filename = f"temp_ig_{int(time.time())}_{video_path.name}"
        object_key = f"reels_temp/{filename}"

        print(f"Uploading temporary video to Cloudflare R2: {object_key}...")
        s3.upload_file(
            str(video_path),
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )

        # Generate S3 Presigned URL (valid for 2 hours)
        public_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=7200,
        )
        print(f"R2 Presigned URL generated successfully.")

        return public_url, object_key, s3

    def _delete_from_r2(self, s3_client: Any, object_key: str) -> None:
        """Delete temporary video from Cloudflare R2."""
        endpoint = os.environ.get("CLOUDFLARE_R2_ENDPOINT", "")
        bucket_name = "store-instagram" if "/store-instagram" in endpoint else os.environ.get("CLOUDFLARE_R2_BUCKET_NAME", "open-montage")
        try:
            print(f"Cleaning up temporary file from R2: {object_key}...")
            s3_client.delete_object(Bucket=bucket_name, Key=object_key)
            print("R2 Temporary File Cleaned Up Successfully!")
        except Exception as e:
            print(f"Warning: Failed to clean up R2 file {object_key}: {e}")

    def _upload_instagram_video(self, user_token: str, ig_account_id: str, video_url: str, caption: str) -> str:
        """Upload video to Instagram Reels using public URL."""
        import requests

        # 1. Create Media Container
        container_url = f"{self.GRAPH_URL}/{ig_account_id}/media"
        container_data = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": user_token,
        }

        res = requests.post(container_url, data=container_data, timeout=60).json()
        if "error" in res:
            raise Exception(f"IG container creation error: {res['error']}")

        container_id = res["id"]

        # 2. Wait for processing
        status_url = f"{self.GRAPH_URL}/{container_id}?fields=status_code,status&access_token={user_token}"
        for _ in range(30):  # Wait up to ~150s
            time.sleep(5)
            status_res = requests.get(status_url, timeout=30).json()
            code = status_res.get("status_code", "")
            if code == "FINISHED":
                break
            elif code == "ERROR":
                err_msg = status_res.get("status", "Media processing failed.")
                raise Exception(f"IG media processing error: {err_msg}")

        # 3. Publish Container
        publish_url = f"{self.GRAPH_URL}/{ig_account_id}/media_publish"
        publish_data = {
            "creation_id": container_id,
            "access_token": user_token,
        }

        pub_res = requests.post(publish_url, data=publish_data, timeout=60).json()
        if "error" in pub_res:
            raise Exception(f"IG publish error: {pub_res['error']}")

        return pub_res.get("id")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        user_token = os.environ.get("TOKEN_FACEBOOK")
        if not user_token:
            return ToolResult(success=False, error="TOKEN_FACEBOOK environment variable not set.")

        caption = inputs.get("caption", "")
        page_id = inputs.get("page_id")

        if not page_id:
            return ToolResult(success=False, error="page_id is required.")

        post_to_fb = inputs.get("post_to_facebook", True)
        post_to_ig = inputs.get("post_to_instagram", True)

        fb_id = None
        ig_id = None
        publish_entries = []
        timestamp = datetime.now(timezone.utc).isoformat()

        # R2 cleanup reference tracking
        r2_client = None
        r2_key = None

        try:
            # 1. Fetch Page Info & Access Token (if needed)
            page_token = user_token
            ig_account_id = None
            try:
                page_info = self._get_page_info(user_token, page_id)
                page_token = page_info.get("access_token", user_token)
                ig_account_id = page_info.get("instagram_business_account", {}).get("id")
            except Exception as e:
                print(f"Warning: Could not fetch page info: {e}. Will try to proceed with default token if page_id is actually an IG account ID.")

            # If page_id is actually an IG account ID, use it directly
            if not ig_account_id and not post_to_fb and post_to_ig:
                ig_account_id = page_id

            # 2. Upload to Facebook
            if post_to_fb:
                fb_id = self._upload_facebook_video(page_token, page_id, video_path, caption)
                if fb_id:
                    publish_entries.append({
                        "platform": "facebook",
                        "status": "published",
                        "video_id": fb_id,
                        "url": f"https://facebook.com/{page_id}/videos/{fb_id}",
                        "timestamp": timestamp,
                        "metadata_used": {"description": caption}
                    })

            # 3. Upload to Instagram
            if post_to_ig:
                if not ig_account_id:
                    if not publish_entries:
                        return ToolResult(False, error="No Instagram Business Account linked to this Page.")
                    print("Warning: No Instagram Business Account linked to Page. Skipping Instagram upload.")
                else:
                    video_url = inputs.get("video_url")

                    # If no video_url provided, handle temporary R2 upload
                    if not video_url:
                        video_url, r2_key, r2_client = self._upload_to_r2(video_path)

                    try:
                        ig_id = self._upload_instagram_video(
                            user_token,
                            ig_account_id,
                            video_url,
                            caption
                        )
                        if ig_id:
                            publish_entries.append({
                                "platform": "instagram",
                                "status": "published",
                                "video_id": ig_id,
                                "timestamp": timestamp,
                                "metadata_used": {"description": caption}
                            })
                    finally:
                        # Clean up temporary R2 file immediately after upload attempt
                        if r2_client and r2_key:
                            self._delete_from_r2(r2_client, r2_key)

            publish_log = {"version": "1.0", "entries": publish_entries}

            return ToolResult(
                success=True,
                data={
                    "publish_log": publish_log,
                    "facebook_post_id": fb_id,
                    "instagram_media_id": ig_id,
                },
                artifacts=[str(video_path)],
            )

        except Exception as exc:
            return ToolResult(success=False, error=f"Meta upload failed: {str(exc)}")
