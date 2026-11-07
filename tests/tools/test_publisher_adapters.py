from unittest.mock import MagicMock
import pytest

from lib.application.publishing.ports import SocialPublisherPort
from lib.domain.publishing.entities import (
    PlatformType,
    PublishJob,
    PublishSlot,
)
from tools.publishers.adapters.youtube_adapter import YouTubeAdapter
from tools.publishers.adapters.facebook_adapter import FacebookAdapter
from tools.publishers.adapters.tiktok_adapter import TikTokAdapter
from tools.publishers.adapters import create_publisher_registry


@pytest.fixture
def sample_job():
    slot = PublishSlot(slot_time="09:15", date_str="2026-11-08", timezone="America/New_York")
    return PublishJob(
        project_id="cand_adapter_test",
        video_path="/tmp/test_video.mp4",
        title="Sample Video",
        description="Sample Description",
        slot=slot,
        platform=PlatformType.YOUTUBE,
        tags=("tag1", "tag2"),
    )


def test_youtube_adapter_satisfies_port(sample_job):
    mock_yt = MagicMock()
    mock_yt.upload_video.return_value = {"id": "yt_vid_999", "status": {"publishAt": sample_job.slot.utc_iso_z}}

    adapter = YouTubeAdapter(mock_yt)
    assert isinstance(adapter, SocialPublisherPort)
    assert adapter.platform == PlatformType.YOUTUBE

    result = adapter.publish(sample_job)
    assert result.success is True
    assert result.post_id == "yt_vid_999"
    assert result.publish_at == sample_job.slot.utc_iso_z
    mock_yt.upload_video.assert_called_once()


def test_facebook_adapter_satisfies_port(sample_job):
    mock_fb = MagicMock()
    mock_fb.publish_reel.return_value = {"id": "fb_reel_888", "success": True}

    fb_job = PublishJob(
        project_id=sample_job.project_id,
        video_path=sample_job.video_path,
        title=sample_job.title,
        description=sample_job.description,
        slot=sample_job.slot,
        platform=PlatformType.FACEBOOK,
    )

    adapter = FacebookAdapter(mock_fb)
    assert isinstance(adapter, SocialPublisherPort)
    assert adapter.platform == PlatformType.FACEBOOK

    result = adapter.publish(fb_job)
    assert result.success is True
    assert result.post_id == "fb_reel_888"
    mock_fb.publish_reel.assert_called_once()


def test_tiktok_adapter_satisfies_port(sample_job):
    mock_tt = MagicMock()
    mock_tt.upload_video.return_value = {"id": "tt_item_777", "status": "scheduled"}

    tt_job = PublishJob(
        project_id=sample_job.project_id,
        video_path=sample_job.video_path,
        title=sample_job.title,
        description=sample_job.description,
        slot=sample_job.slot,
        platform=PlatformType.TIKTOK,
    )

    adapter = TikTokAdapter(mock_tt)
    assert isinstance(adapter, SocialPublisherPort)
    assert adapter.platform == PlatformType.TIKTOK

    result = adapter.publish(tt_job)
    assert result.success is True
    assert result.post_id == "tt_item_777"
    mock_tt.upload_video.assert_called_once()


def test_publisher_registry():
    registry = create_publisher_registry()
    assert PlatformType.YOUTUBE in registry
    assert PlatformType.FACEBOOK in registry
    assert PlatformType.TIKTOK in registry
