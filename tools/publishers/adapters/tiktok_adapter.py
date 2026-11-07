from __future__ import annotations

import logging
from typing import Any, Optional

from lib.domain.publishing.entities import (
    PlatformType,
    PublishJob,
    PublishResult,
    PublishStatus,
)

logger = logging.getLogger(__name__)


class TikTokAdapter:
    """Adapter bridging TiktokPublisher to SocialPublisherPort."""

    def __init__(self, publisher: Any = None) -> None:
        if publisher is None:
            from tools.publishers.tiktok_publisher import TiktokPublisher
            self._publisher = TiktokPublisher()
        else:
            self._publisher = publisher

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    def publish(self, job: PublishJob) -> PublishResult:
        try:
            logger.info("Uploading %s to TikTok at %s", job.project_id, job.slot.utc_iso_z)
            caption = f"{job.title}\n{job.description}".strip()
            resp = self._publisher.upload_video(
                video_path=job.video_path,
                text=caption,
                schedule_time=job.slot.utc_iso_z,
            )

            post_id = resp.get("publish_id") or resp.get("id") or resp.get("item_id")
            if not post_id and resp.get("status") != "scheduled":
                return PublishResult.fail(
                    platform=self.platform,
                    error=f"TikTok response missing publish ID: {resp}",
                    raw_metadata=resp,
                )

            return PublishResult.ok(
                platform=self.platform,
                post_id=str(post_id or "tiktok_published"),
                publish_at=job.slot.utc_iso_z,
                raw_metadata=resp,
            )
        except Exception as exc:
            logger.exception("TikTok publishing failed for %s: %s", job.project_id, exc)
            return PublishResult.fail(
                platform=self.platform,
                error=str(exc),
            )

    def check_status(self, post_id: str) -> Optional[PublishStatus]:
        return PublishStatus.SCHEDULED
