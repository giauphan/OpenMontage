import pytest
from typing import Dict, Optional, Set

from lib.domain.publishing.entities import (
    PlatformType,
    PublishJob,
    PublishResult,
    PublishSlot,
    PublishStatus,
)
from lib.application.publishing.ports import SocialPublisherPort, PublishStorePort
from lib.application.publishing.use_cases import PublishActiveSlotUseCase, ManualPublishUseCase


class FakePublisher:
    def __init__(self, platform: PlatformType, return_fail: bool = False):
        self._platform = platform
        self._return_fail = return_fail
        self.published_jobs = []

    @property
    def platform(self) -> PlatformType:
        return self._platform

    def publish(self, job: PublishJob) -> PublishResult:
        self.published_jobs.append(job)
        if self._return_fail:
            return PublishResult.fail(self._platform, "Fake network error")
        return PublishResult.ok(
            self._platform,
            post_id=f"{self._platform.value}_post_123",
            publish_at=job.slot.utc_iso_z,
        )

    def check_status(self, post_id: str) -> Optional[PublishStatus]:
        return PublishStatus.SCHEDULED


class InMemoryPublishStore:
    def __init__(self):
        self.completed_keys: Set[str] = set()
        self.scheduled_records = {}
        self.failed_records = {}
        self.claims: Set[str] = set()

    def is_job_completed(self, project_id: str, platform: PlatformType) -> bool:
        return f"{project_id}_{platform.value}" in self.completed_keys

    def claim_slot(self, project_id: str, platform: PlatformType, operator_id: str) -> bool:
        key = f"{project_id}_{platform.value}"
        if key in self.claims or key in self.completed_keys:
            return False
        self.claims.add(key)
        return True

    def record_scheduled(self, job: PublishJob, post_id: str, publish_at_utc: str) -> None:
        self.scheduled_records[f"{job.project_id}_{job.platform.value}"] = {
            "post_id": post_id,
            "publish_at": publish_at_utc,
        }
        self.completed_keys.add(f"{job.project_id}_{job.platform.value}")

    def record_published(self, job: PublishJob, post_id: str) -> None:
        self.completed_keys.add(f"{job.project_id}_{job.platform.value}")

    def record_failed(self, job: PublishJob, error: str) -> None:
        self.failed_records[f"{job.project_id}_{job.platform.value}"] = error


def test_publish_active_slot_use_case_filters_and_publishes():
    slot_09 = PublishSlot(slot_time="09:15", date_str="2026-11-08")
    slot_14 = PublishSlot(slot_time="14:15", date_str="2026-11-08")

    job1 = PublishJob(
        project_id="cand_1",
        video_path="/tmp/v1.mp4",
        title="Title 1",
        description="Desc 1",
        slot=slot_09,
        platform=PlatformType.YOUTUBE,
    )
    job2 = PublishJob(
        project_id="cand_2",
        video_path="/tmp/v2.mp4",
        title="Title 2",
        description="Desc 2",
        slot=slot_14,
        platform=PlatformType.YOUTUBE,
    )

    yt_pub = FakePublisher(PlatformType.YOUTUBE)
    store = InMemoryPublishStore()

    use_case = PublishActiveSlotUseCase(
        publishers={PlatformType.YOUTUBE: yt_pub},
        store=store,
    )

    # Execute slot 09:15 only
    results = use_case.execute([job1, job2], target_slot="09:15")

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].post_id == "youtube_post_123"
    assert len(yt_pub.published_jobs) == 1
    assert yt_pub.published_jobs[0].project_id == "cand_1"
    assert "cand_1_youtube" in store.completed_keys


def test_publish_active_slot_skips_already_completed():
    slot = PublishSlot(slot_time="09:15", date_str="2026-11-08")
    job = PublishJob(
        project_id="cand_already_done",
        video_path="/tmp/v1.mp4",
        title="Title 1",
        description="Desc 1",
        slot=slot,
        platform=PlatformType.YOUTUBE,
    )

    yt_pub = FakePublisher(PlatformType.YOUTUBE)
    store = InMemoryPublishStore()
    store.completed_keys.add("cand_already_done_youtube")

    use_case = PublishActiveSlotUseCase(
        publishers={PlatformType.YOUTUBE: yt_pub},
        store=store,
    )

    results = use_case.execute([job], target_slot="09:15")
    assert len(results) == 0
    assert len(yt_pub.published_jobs) == 0


def test_publish_active_slot_handles_failure():
    slot = PublishSlot(slot_time="09:15", date_str="2026-11-08")
    job = PublishJob(
        project_id="cand_fail",
        video_path="/tmp/v1.mp4",
        title="Title 1",
        description="Desc 1",
        slot=slot,
        platform=PlatformType.YOUTUBE,
    )

    yt_pub = FakePublisher(PlatformType.YOUTUBE, return_fail=True)
    store = InMemoryPublishStore()

    use_case = PublishActiveSlotUseCase(
        publishers={PlatformType.YOUTUBE: yt_pub},
        store=store,
    )

    results = use_case.execute([job], target_slot="09:15")
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "Fake network error"
    assert "cand_fail_youtube" in store.failed_records
