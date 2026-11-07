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


class FacebookAdapter:
    """Adapter bridging FacebookPublisher to SocialPublisherPort."""

    def __init__(self, publisher: Any = None) -> None:
        if publisher is None:
            from tools.publishers.facebook_publisher import FacebookPublisher
            self._publisher = FacebookPublisher()
        else:
            self._publisher = publisher

    @property
    def platform(self) -> PlatformType:
        return PlatformType.FACEBOOK

    def publish(self, job: PublishJob) -> PublishResult:
        try:
            logger.info("Uploading %s to Facebook at %s", job.project_id, job.slot.utc_iso_z)
            # Try publish_reel first, fall back to publish_video
            if hasattr(self._publisher, "publish_reel"):
                resp = self._publisher.publish_reel(
                    video_path=job.video_path,
                    title=job.title,
                    description=job.description,
                    scheduled_publish_time=job.slot.utc_iso_z,
                )
            else:
                resp = self._publisher.publish_video(
                    video_path=job.video_path,
                    description=f"{job.title}\n\n{job.description}",
                    scheduled_publish_time=job.slot.utc_iso_z,
                )

            post_id = resp.get("id") or resp.get("video_id")
            if not post_id and not resp.get("success"):
                return PublishResult.fail(
                    platform=self.platform,
                    error=f"Facebook response missing post ID: {resp}",
                    raw_metadata=resp,
                )

            return PublishResult.ok(
                platform=self.platform,
                post_id=str(post_id or "fb_published"),
                publish_at=job.slot.utc_iso_z,
                raw_metadata=resp,
            )
        except Exception as exc:
            logger.exception("Facebook publishing failed for %s: %s", job.project_id, exc)
            return PublishResult.fail(
                platform=self.platform,
                error=str(exc),
            )

    def check_status(self, post_id: str) -> Optional[PublishStatus]:
        return PublishStatus.SCHEDULED
