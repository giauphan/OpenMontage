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


class YouTubeAdapter:
    """Adapter bridging YoutubePublisher to SocialPublisherPort."""

    def __init__(self, publisher: Any = None) -> None:
        if publisher is None:
            from tools.publishers.youtube_publisher import YoutubePublisher
            self._publisher = YoutubePublisher()
        else:
            self._publisher = publisher

    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    def publish(self, job: PublishJob) -> PublishResult:
        try:
            logger.info("Uploading %s to YouTube at %s", job.project_id, job.slot.utc_iso_z)
            resp = self._publisher.upload_video(
                video_path=job.video_path,
                title=job.title,
                description=job.description,
                tags=list(job.tags) if job.tags else None,
                publish_at=job.slot.utc_iso_z,
            )
            video_id = resp.get("id") or resp.get("snippet", {}).get("resourceId", {}).get("videoId")
            if not video_id:
                return PublishResult.fail(
                    platform=self.platform,
                    error=f"YouTube response missing video ID: {resp}",
                    raw_metadata=resp,
                )

            publish_at = resp.get("status", {}).get("publishAt") or job.slot.utc_iso_z
            return PublishResult.ok(
                platform=self.platform,
                post_id=str(video_id),
                publish_at=str(publish_at),
                raw_metadata=resp,
            )
        except Exception as exc:
            logger.exception("YouTube publishing failed for %s: %s", job.project_id, exc)
            return PublishResult.fail(
                platform=self.platform,
                error=str(exc),
            )

    def check_status(self, post_id: str) -> Optional[PublishStatus]:
        return PublishStatus.SCHEDULED
