from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from lib.domain.publishing.entities import (
    PlatformType,
    PublishJob,
    PublishResult,
    PublishStatus,
)


@runtime_checkable
class SocialPublisherPort(Protocol):
    """Outbound port for publishing video content to social platforms."""

    @property
    def platform(self) -> PlatformType:
        """The social platform handled by this publisher."""
        ...

    def publish(self, job: PublishJob) -> PublishResult:
        """Publish or schedule a video job on the platform."""
        ...

    def check_status(self, post_id: str) -> Optional[PublishStatus]:
        """Poll the processing/publish status of an existing post."""
        ...


@runtime_checkable
class PublishStorePort(Protocol):
    """Outbound port for persisting publish states, locks, and history."""

    def is_job_completed(self, project_id: str, platform: PlatformType) -> bool:
        """Return True if the project has already been scheduled or published."""
        ...

    def claim_slot(self, project_id: str, platform: PlatformType, operator_id: str) -> bool:
        """Attempt to atomically acquire a lock/claim for a project on a platform."""
        ...

    def record_scheduled(self, job: PublishJob, post_id: str, publish_at_utc: str) -> None:
        """Persist state when a project is scheduled for future release."""
        ...

    def record_published(self, job: PublishJob, post_id: str) -> None:
        """Persist state when a project is immediately published/live."""
        ...

    def record_failed(self, job: PublishJob, error: str) -> None:
        """Persist failure diagnostic details."""
        ...
