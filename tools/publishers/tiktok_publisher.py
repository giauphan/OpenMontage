"""TikTok Browser Automation Publisher Tool for OpenMontage.

Uploads videos to TikTok Creator Studio automatically using Playwright
and a saved session cookie/storage_state JSON.

No API App approval required. 100% Free.
"""

from __future__ import annotations

import json
import os
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


class TiktokPublisher(BaseTool):
    name = "tiktok_publisher"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "tiktok"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.LOCAL

    dependencies = [
        "cmd:google-chrome",
        "python:playwright",
    ]
    install_instructions = (
        "1. Ensure google-chrome is installed on system.\n"
        "2. Save your TikTok cookies / storage state to ~/.openmontage/tiktok_cookies.json"
    )

    agent_skills = []

    capabilities = ["tiktok_upload", "write_publish_log"]
    supports = {
        "local_offline": False,
        "free": True,
        "uploads": True,
    }
    best_for = [
        "direct automatic video upload to TikTok without API approval",
        "setting TikTok video caption and hashtags via browser automation",
    ]
    not_good_for = [
        "offline publishing without internet",
    ]

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
            "cookie_path": {
                "type": "string",
                "description": "Path to TikTok storage_state/cookies JSON file. Defaults to '~/.openmontage/tiktok_cookies.json'.",
            },
            "headless": {
                "type": "boolean",
                "default": True,
                "description": "Run browser in headless mode.",
            },
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "status": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=200, network_required=True
    )
    side_effects = ["uploads video to user TikTok account via browser"]
    user_visible_verification = [
        "Check TikTok Creator Studio or TikTok profile to verify the uploaded video",
    ]

    def _get_tiktok_host_rules(self) -> str:
        """Resolve TikTok domain IPs via Public DNS 8.8.8.8 to bypass local WSL DNS issues."""
        try:
            import dns.resolver

            r = dns.resolver.Resolver()
            r.nameservers = ["8.8.8.8", "1.1.1.1"]
            rules = []
            for domain in ["tiktok.com", "www.tiktok.com", "v16-webapp-prime.tiktok.com"]:
                try:
                    ans = r.resolve(domain, "A")
                    if ans:
                        ip = ans[0].address
                        rules.append(f"MAP {domain} {ip}")
                except Exception:
                    pass
            if rules:
                return ", ".join(rules)
        except Exception:
            pass
        return "MAP www.tiktok.com 125.234.51.33, MAP tiktok.com 171.242.7.234"

    def _normalize_cookies(self, raw_data: Any) -> dict[str, Any]:
        """Convert standard EditThisCookie/Cookie-Editor list format into Playwright storage_state dict format."""
        if isinstance(raw_data, dict) and "cookies" in raw_data:
            return raw_data

        if isinstance(raw_data, list):
            playwright_cookies = []
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                cookie = {
                    "name": item.get("name", ""),
                    "value": item.get("value", ""),
                    "domain": item.get("domain", ""),
                    "path": item.get("path", "/"),
                    "httpOnly": bool(item.get("httpOnly", False)),
                    "secure": bool(item.get("secure", False)),
                }
                same_site = item.get("sameSite", "")
                if same_site and same_site.lower() in ("strict", "lax", "none"):
                    cookie["sameSite"] = same_site.capitalize()
                else:
                    cookie["sameSite"] = "Lax"

                if "expirationDate" in item:
                    cookie["expires"] = float(item["expirationDate"])

                playwright_cookies.append(cookie)

            return {"cookies": playwright_cookies, "origins": []}

        return {"cookies": [], "origins": []}

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        cookie_path_str = inputs.get("cookie_path", "~/.openmontage/tiktok_cookies.json")
        cookie_path = Path(cookie_path_str).expanduser()

        if not cookie_path.is_file():
            return ToolResult(
                success=False,
                error=(
                    f"TikTok cookies file not found at {cookie_path}.\n"
                    "Please save your logged-in TikTok storage state / cookies JSON first."
                ),
            )

        try:
            with open(cookie_path, encoding="utf-8") as f:
                raw_cookies = json.load(f)
            storage_state = self._normalize_cookies(raw_cookies)
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to parse cookie file: {exc}")

        caption = inputs.get("caption", "")
        headless = inputs.get("headless", True)
        host_rules = self._get_tiktok_host_rules()

        try:
            from playwright.sync_api import sync_playwright

            chrome_path = "/usr/bin/google-chrome"

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=chrome_path,
                    headless=headless,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        f"--host-rules={host_rules}",
                    ],
                )

                context = browser.new_context(
                    storage_state=storage_state,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    ignore_https_errors=True,
                )

                page = context.new_page()

                # Go to TikTok Creator Center Upload with commit wait strategy
                page.goto("https://www.tiktok.com/tiktokstudio/upload", timeout=60000, wait_until="commit")
                page.wait_for_timeout(8000)

                # Check if logged in
                if "login" in page.url.lower():
                    browser.close()
                    return ToolResult(
                        success=False,
                        error="TikTok session expired or invalid. Please refresh tiktok_cookies.json.",
                    )

                # Upload file
                file_input = page.locator('input[type="file"]')
                file_input.wait_for(state="attached", timeout=45000)
                file_input.set_input_files(str(video_path))

                # Wait for upload to complete
                page.wait_for_selector('div[contenteditable="true"]', timeout=90000)
                page.wait_for_timeout(5000)

                # Fill caption
                editor = page.locator('div[contenteditable="true"]').first
                editor.click()
                # Clear existing text
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(caption)
                page.wait_for_timeout(2000)

                # Click Post button
                post_btn = page.locator('button:has-text("Post"), button:has-text("Đăng")').first
                if post_btn.is_visible():
                    post_btn.click()
                    page.wait_for_timeout(10000)
                else:
                    browser.close()
                    return ToolResult(success=False, error="Post button not found on TikTok page.")

                browser.close()

            timestamp = datetime.now(timezone.utc).isoformat()
            entry = {
                "platform": "tiktok",
                "status": "published",
                "timestamp": timestamp,
                "metadata_used": {
                    "caption": caption,
                },
            }

            publish_log = {"version": "1.0", "entries": [entry]}

            return ToolResult(
                success=True,
                data={
                    "publish_log": publish_log,
                    "status": "published",
                },
                artifacts=[str(video_path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False, error=f"TikTok upload failed: {str(exc)}"
            )
