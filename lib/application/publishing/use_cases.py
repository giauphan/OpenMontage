from __future__ import annotations

import logging
from typing import List, Mapping, Optional, Sequence

from lib.application.publishing.ports import PublishStorePort, SocialPublisherPort
from lib.domain.publishing.entities import (
    PlatformType,
    PublishJob,
    PublishResult,
    PublishStatus,
)

logger = logging.getLogger(__name__)


class PublishActiveSlotUseCase:
    """Orchestrates scheduled slot publishing across social media platforms."""

    def __init__(
        self,
        publishers: Mapping[PlatformType, SocialPublisherPort],
        store: PublishStorePort,
        operator_id: str = "openmontage_scheduler",
    ) -> None:
        self._publishers = publishers
        self._store = store
        self._operator_id = operator_id

    def execute(
        self,
        jobs: Sequence[PublishJob],
        target_slot: Optional[str] = None,
        include_overdue: bool = False,
        dry_run: bool = False,
    ) -> List[PublishResult]:
        results: List[PublishResult] = []

        for job in jobs:
            # Slot matching
            if target_slot is not None and job.slot.slot_time != target_slot:
                logger.debug(
                    "Skipping %s on %s: slot %s does not match target %s",
                    job.project_id,
                    job.platform.value,
                    job.slot.slot_time,
                    target_slot,
                )
                continue

            # Idempotency check
            if self._store.is_job_completed(job.project_id, job.platform):
                logger.info(
                    "Job %s on %s already completed/scheduled, skipping.",
                    job.project_id,
                    job.platform.value,
                )
                continue

            # Dry-run handling
            if dry_run:
                logger.info("[DRY RUN] Would publish %s to %s", job.project_id, job.platform.value)
                results.append(
                    PublishResult.ok(
                        platform=job.platform,
                        post_id="dry_run_id",
                        publish_at=job.slot.utc_iso_z,
                    )
                )
                continue

            # Claim concurrency lock
            claimed = self._store.claim_slot(job.project_id, job.platform, self._operator_id)
            if not claimed:
                logger.warning(
                    "Failed to claim lock for %s on %s, skipping.",
                    job.project_id,
                    job.platform.value,
                )
                continue

            # Locate publisher port
            publisher = self._publishers.get(job.platform)
            if not publisher:
                err_msg = f"No publisher adapter registered for platform: {job.platform.value}"
                logger.error(err_msg)
                self._store.record_failed(job, err_msg)
                results.append(PublishResult.fail(platform=job.platform, error=err_msg))
                continue

            # Execute publishing
            try:
                res = publisher.publish(job)
                if res.success:
                    if res.publish_at:
                        self._store.record_scheduled(job, res.post_id or "", res.publish_at)
                    else:
                        self._store.record_published(job, res.post_id or "")
                else:
                    self._store.record_failed(job, res.error or "Unknown publisher error")
                results.append(res)
            except Exception as exc:
                err = f"Unexpected exception publishing {job.project_id} to {job.platform.value}: {exc}"
                logger.exception(err)
                self._store.record_failed(job, err)
                results.append(PublishResult.fail(platform=job.platform, error=err))

        return results


class ManualPublishUseCase:
    """Orchestrates manual, on-demand dispatch of a single project to platforms."""

    def __init__(
        self,
        publishers: Mapping[PlatformType, SocialPublisherPort],
        store: PublishStorePort,
    ) -> None:
        self._publishers = publishers
        self._store = store

    def execute(
        self,
        job: PublishJob,
        platforms: Optional[Sequence[PlatformType]] = None,
    ) -> List[PublishResult]:
        target_platforms = platforms or [job.platform]
        results: List[PublishResult] = []

        for plat in target_platforms:
            publisher = self._publishers.get(plat)
            if not publisher:
                results.append(PublishResult.fail(platform=plat, error=f"Missing publisher for {plat.value}"))
                continue

            target_job = job if job.platform == plat else PublishJob(
                project_id=job.project_id,
                video_path=job.video_path,
                title=job.title,
                description=job.description,
                slot=job.slot,
                platform=plat,
                tags=job.tags,
            )

            try:
                res = publisher.publish(target_job)
                if res.success:
                    if res.publish_at:
                        self._store.record_scheduled(target_job, res.post_id or "", res.publish_at)
                    else:
                        self._store.record_published(target_job, res.post_id or "")
                else:
                    self._store.record_failed(target_job, res.error or "Publisher failed")
                results.append(res)
            except Exception as exc:
                err = f"Manual publish failed for {plat.value}: {exc}"
                logger.exception(err)
                self._store.record_failed(target_job, err)
                results.append(PublishResult.fail(platform=plat, error=err))

        return results
