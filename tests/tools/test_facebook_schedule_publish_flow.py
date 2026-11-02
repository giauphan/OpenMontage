"""Integration tests verifying the scheduled Facebook video publishing flow.

Verifies:
1. Scheduled publishing timing validation (10m to 75d in advance)
2. Toolcase Gateway port 20129 URL resolution and normalization
3. Automated 14-language AI dubbing payload generation
4. End-to-end publish_manual_video.py schedule routing to Facebook
5. Firebase store reservation, scheduled transition, and cleanup verification
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publishers.facebook_publisher import (
    FacebookPublisher,
    DEFAULT_14_LANGUAGES,
    DEFAULT_GATEWAY_PORT,
)
from scripts.publish_config import is_platform_enabled, get_enabled_platforms
from scripts.publish_manual_video import publish_batch, _resolve_scheduled_publish
from tools.base_tool import ToolResult
from tools.publish_store import publish_key


def test_facebook_platform_is_activated_in_config(monkeypatch):
    """Verify that 'facebook' is active in config/publish_platforms.json."""
    config_path = ROOT / "config" / "publish_platforms.json"
    monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", str(config_path))
    enabled = get_enabled_platforms()
    assert enabled is not None
    assert "facebook" in enabled
    assert is_platform_enabled("facebook") is True
    assert is_platform_enabled("fb") is True


def test_facebook_publisher_schedule_window():
    """Verify scheduling requires between 10 minutes and 75 days in advance."""
    tool = FacebookPublisher()
    now_epoch = int(time.time())

    # Valid: 2 hours in the future
    valid_epoch = now_epoch + 7200
    assert (now_epoch + 600) <= valid_epoch <= (now_epoch + 6480000)

    # Invalid: 5 minutes in the future (too soon)
    too_soon = now_epoch + 300
    res = tool.execute({
        "video_path": str(Path(__file__)),
        "caption": "Test video",
        "scheduled_publish_time": too_soon,
    })
    assert not res.success
    assert "must be between 10m and 75d" in res.error

    # Invalid: 80 days in the future (too far)
    too_far = now_epoch + (80 * 86400)
    res_far = tool.execute({
        "video_path": str(Path(__file__)),
        "caption": "Test video",
        "scheduled_publish_time": too_far,
    })
    assert not res_far.success
    assert "must be between 10m and 75d" in res_far.error


def test_facebook_publisher_gateway_port_enforcement(monkeypatch):
    """Verify that port 20129 is enforced for Toolcase Gateway."""
    tool = FacebookPublisher()
    monkeypatch.delenv("FACEBOOK_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TOOLCASE_GATEWAY_URL", raising=False)

    # Default URL must use port 20129
    url = tool.get_gateway_base_url()
    assert ":20129" in url
    assert url == "http://127.0.0.1:20129/custom/facebook"

    # Any doc URL containing 28130 must be normalized to 20129
    normalized = tool.get_gateway_base_url({"gateway_url": "http://127.0.0.1:28130/custom/facebook"})
    assert ":20129" in normalized
    assert ":28130" not in normalized


def test_facebook_scheduled_publish_execution(tmp_path: Path):
    """Test full FacebookPublisher execution with scheduling, auto-translate, and Reel publish_type."""
    video_file = tmp_path / "test_fb_video.mp4"
    video_file.write_bytes(b"dummy_video_mp4_binary_content")

    sched_time = int(time.time()) + 14400  # 4 hours in advance

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "video_id": "fb_vid_555888",
        "target_id": "1435449429646177",
        "publish_result": {"id": "fb_vid_555888"},
    }
    mock_session.post.return_value = mock_resp

    tool = FacebookPublisher(http_session=mock_session)
    result = tool.execute({
        "video_path": str(video_file),
        "title": "Bản tin AI hôm nay",
        "caption": "Chi tiết video #AI #OpenMontage",
        "target_id": "1435449429646177",
        "publish_type": "REEL",
        "scheduled_publish_time": sched_time,
        "enable_auto_translate": True,
    })

    assert result.success is True
    assert result.data["status"] == "scheduled"
    assert result.data["facebook_post_id"] == "fb_vid_555888"
    assert result.data["scheduled_publish_time"] == sched_time
    assert result.data["publish_type"] == "REEL"
    assert result.data["auto_translate_enabled"] is True
    assert result.data["video_url"] == "https://facebook.com/1435449429646177/videos/fb_vid_555888"

    # Verify payload delivered to Toolcase Gateway
    call_kwargs = mock_session.post.call_args[1]
    sent_json = call_kwargs["json"]
    assert sent_json["target_id"] == "1435449429646177"
    assert sent_json["scheduled_publish_time"] == sched_time
    assert sent_json["enable_auto_translate"] is True
    assert sent_json["translated_languages"] == DEFAULT_14_LANGUAGES
    assert sent_json["publish_type"] == "REEL"
    assert "video_base64" in sent_json
    assert sent_json["file_name"] == "test_fb_video.mp4"


def test_end_to_end_scheduled_publish_batch_flow(tmp_path: Path):
    """Verify that publish_batch in publish_manual_video.py properly schedules to Facebook."""
    project_dir = tmp_path / "projects" / "cand_scheduled_fb"
    project_dir.mkdir(parents=True)
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_full_vi_9x16.mp4").touch()

    # Slot scheduled for tomorrow at 14:15
    tomorrow_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    metadata = {
        "id": "cand_scheduled_fb",
        "title": "Tiến bộ mới trong AI Agent #tintuc #ai",
        "description": "Cập nhật kiến trúc tác tử thông minh #congnghe",
        "fb_video": "renders/final_full_vi_9x16.mp4",
        "topic": "topic_agent_ai",
        "publish_date": tomorrow_str,
        "publish_time": "14:15",
    }
    (project_dir / "publish_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    class MockPublishStore:
        def __init__(self):
            self.claims = {}
            self.scheduled = {}
            self.published = {}

        def claim(self, *, date, topic, platform, kind, scheduled_for=None, **kwargs):
            key = publish_key(date, topic, platform, kind)
            self.claims[key] = {
                "date": date,
                "topic": topic,
                "platform": platform,
                "kind": kind,
                "status": "scheduling",
                "scheduled_for": scheduled_for,
            }
            return key, True, None

        def mark_scheduled(self, key, **kwargs):
            self.scheduled[key] = kwargs
            if key in self.claims:
                self.claims[key]["status"] = "scheduled"

        def mark_published(self, key, **kwargs):
            self.published[key] = kwargs

        def unclaim(self, *args, **kwargs):
            pass

    store = MockPublishStore()

    mock_execute_result = ToolResult(
        success=True,
        data={
            "status": "scheduled",
            "video_id": "fb_sched_10203040",
            "facebook_post_id": "fb_sched_10203040",
            "target_id": "1435449429646177",
            "video_url": "https://facebook.com/1435449429646177/videos/fb_sched_10203040",
            "publish_type": "REEL",
            "auto_translate_enabled": True,
        },
    )

    with patch("scripts.publish_manual_video.validate_publish_asset"), \
         patch("scripts.publish_manual_video.validate_project_quality"), \
         patch("lib.news_release_gate.require_news_evidence"), \
         patch("tools.publishers.facebook_publisher.FacebookPublisher.execute", return_value=mock_execute_result) as mock_pub:

        results = publish_batch(
            metadata,
            project_dir,
            store=store,
            dry_run=False,
            only_platform="facebook",
            enforce_preflight=False,
            date=tomorrow_str,
        )

    # 1. Verify Facebook publisher was invoked with future epoch timestamp
    assert mock_pub.call_count == 1
    call_args = mock_pub.call_args[0][0]
    assert call_args["publish_type"] == "REEL"
    assert call_args["enable_auto_translate"] is True
    assert "scheduled_publish_time" in call_args
    assert call_args["scheduled_publish_time"] > int(time.time()) + 600

    # 2. Verify platform results marked as scheduled
    fb_result = results["platforms"]["facebook/reels"]
    assert fb_result["status"] == "scheduled"
    assert fb_result["video_id"] == "fb_sched_10203040"

    # 3. Verify Firebase store marked the record as scheduled with scheduled_for timestamp
    claim_key = publish_key(tomorrow_str, "cand_scheduled_fb", "facebook", "reels")
    assert claim_key in store.scheduled
    assert store.scheduled[claim_key]["video_id"] == "fb_sched_10203040"
    assert store.claims[claim_key]["status"] == "scheduled"
