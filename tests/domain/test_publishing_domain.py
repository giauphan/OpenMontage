from datetime import datetime, timezone
import pytest
from dataclasses import FrozenInstanceError

from lib.domain.publishing.entities import (
    PlatformType,
    PublishStatus,
    PublishSlot,
    PublishJob,
    PublishResult,
)
from lib.domain.publishing.exceptions import (
    PublishDomainError,
    InvalidPublishSlotError,
    VideoFileMissingError,
)


def test_platform_type_values():
    assert PlatformType.YOUTUBE.value == "youtube"
    assert PlatformType.FACEBOOK.value == "facebook"
    assert PlatformType.TIKTOK.value == "tiktok"
    assert PlatformType.INSTAGRAM.value == "instagram"


def test_publish_status_values():
    assert PublishStatus.PENDING.value == "pending"
    assert PublishStatus.CLAIMED.value == "claimed"
    assert PublishStatus.SCHEDULED.value == "scheduled"
    assert PublishStatus.PUBLISHED.value == "published"
    assert PublishStatus.FAILED.value == "failed"


def test_publish_slot_utc_calculation():
    # 09:15 in America/New_York on Nov 8 (EST, UTC-5) is 14:15:00Z
    slot = PublishSlot(slot_time="09:15", date_str="2026-11-08", timezone="America/New_York")
    assert slot.slot_time == "09:15"
    assert slot.date_str == "2026-11-08"
    assert slot.utc_iso_z == "2026-11-08T14:15:00Z"


def test_publish_slot_validation():
    with pytest.raises(InvalidPublishSlotError):
        PublishSlot(slot_time="invalid", date_str="2026-11-08")

    with pytest.raises(InvalidPublishSlotError):
        PublishSlot(slot_time="09:15", date_str="not-a-date")


def test_publish_job_immutability_and_transition():
    slot = PublishSlot(slot_time="09:15", date_str="2026-11-08", timezone="America/New_York")
    job = PublishJob(
        project_id="cand_test123",
        video_path="/tmp/video.mp4",
        title="Test Title",
        description="Test Desc",
        slot=slot,
        platform=PlatformType.YOUTUBE,
    )
    assert job.status == PublishStatus.PENDING

    # Immutable
    with pytest.raises((FrozenInstanceError, AttributeError)):
        job.status = PublishStatus.PUBLISHED  # type: ignore

    # Pure transition
    updated = job.with_status(PublishStatus.PUBLISHED, platform_post_id="post_999")
    assert updated.status == PublishStatus.PUBLISHED
    assert updated.platform_post_id == "post_999"
    assert job.status == PublishStatus.PENDING  # original untouched


def test_publish_result_helpers():
    success = PublishResult.ok(
        platform=PlatformType.YOUTUBE,
        post_id="yt_123",
        publish_at="2026-11-08T14:15:00Z",
    )
    assert success.success is True
    assert success.post_id == "yt_123"
    assert success.error is None

    failure = PublishResult.fail(
        platform=PlatformType.TIKTOK,
        error="Session expired",
    )
    assert failure.success is False
    assert failure.post_id is None
    assert failure.error == "Session expired"
