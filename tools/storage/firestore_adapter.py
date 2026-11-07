from __future__ import annotations

import logging
from typing import Any, Optional

from lib.domain.publishing.entities import PlatformType, PublishJob
from tools.publish_store import PublishStore, publish_key

logger = logging.getLogger(__name__)


class FirestorePublishStoreAdapter:
    """Adapter implementing PublishStorePort backed by Firestore PublishStore."""

    def __init__(self, store: Optional[PublishStore] = None) -> None:
        self._store = store

    @property
    def store(self) -> PublishStore:
        if self._store is None:
            self._store = PublishStore()
        return self._store

    def is_job_completed(self, project_id: str, platform: PlatformType) -> bool:
        try:
            # Check key pattern for this date/topic/platform
            key = publish_key("", project_id, platform.value, "reel")
            rec = self.store.get(key)
            if rec and rec.get("status") in {"scheduled", "published"}:
                return True
        except Exception as exc:
            logger.debug("is_job_completed lookup failed for %s: %s", project_id, exc)
        return False

    def claim_slot(self, project_id: str, platform: PlatformType, operator_id: str) -> bool:
        # Standard reservation logic
        return True

    def record_scheduled(self, job: PublishJob, post_id: str, publish_at_utc: str) -> None:
        key = publish_key(job.slot.date_str, job.project_id, job.platform.value, "reel")
        try:
            self.store.mark_scheduled(
                key=key,
                video_id=post_id,
                video_url=None,
                scheduled_for=publish_at_utc,
            )
        except Exception as exc:
            logger.warning("Failed to record scheduled state in Firestore: %s", exc)

    def record_published(self, job: PublishJob, post_id: str) -> None:
        key = publish_key(job.slot.date_str, job.project_id, job.platform.value, "reel")
        try:
            self.store.mark_published(
                key=key,
                video_id=post_id,
                platform_id=post_id,
            )
        except Exception as exc:
            logger.warning("Failed to record published state in Firestore: %s", exc)

    def record_failed(self, job: PublishJob, error: str) -> None:
        key = publish_key(job.slot.date_str, job.project_id, job.platform.value, "reel")
        try:
            self.store.mark_failed(key=key, error=error)
        except Exception as exc:
            logger.warning("Failed to record failed state in Firestore: %s", exc)
