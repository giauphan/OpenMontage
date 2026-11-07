from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from lib.domain.publishing.exceptions import InvalidPublishSlotError


class PlatformType(str, Enum):
    YOUTUBE = "youtube"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class PublishStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class PublishSlot:
    slot_time: str
    date_str: str
    timezone: str = "America/New_York"
    utc_iso_z: str = field(init=False)

    def __post_init__(self) -> None:
        if not re.match(r"^\d{1,2}:\d{2}$", self.slot_time):
            raise InvalidPublishSlotError(f"Invalid slot time format '{self.slot_time}', expected HH:MM")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", self.date_str):
            raise InvalidPublishSlotError(f"Invalid date format '{self.date_str}', expected YYYY-MM-DD")

        try:
            tz = ZoneInfo(self.timezone)
        except Exception as e:
            raise InvalidPublishSlotError(f"Unknown timezone '{self.timezone}': {e}") from e

        try:
            hour, minute = map(int, self.slot_time.split(":"))
            year, month, day = map(int, self.date_str.split("-"))
            local_dt = datetime(year, month, day, hour, minute, 0, tzinfo=tz)
        except Exception as e:
            raise InvalidPublishSlotError(f"Failed to parse datetime for slot '{self.date_str} {self.slot_time}': {e}") from e

        utc_dt = local_dt.astimezone(timezone.utc)
        object.__setattr__(self, "utc_iso_z", utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))


@dataclass(frozen=True)
class PublishJob:
    project_id: str
    video_path: str
    title: str
    description: str
    slot: PublishSlot
    platform: PlatformType
    tags: Tuple[str, ...] = ()
    status: PublishStatus = PublishStatus.PENDING
    platform_post_id: Optional[str] = None
    error_message: Optional[str] = None

    def with_status(
        self,
        new_status: PublishStatus,
        platform_post_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> PublishJob:
        return replace(
            self,
            status=new_status,
            platform_post_id=platform_post_id if platform_post_id is not None else self.platform_post_id,
            error_message=error_message if error_message is not None else self.error_message,
        )


@dataclass(frozen=True)
class PublishResult:
    success: bool
    platform: PlatformType
    post_id: Optional[str] = None
    publish_at: Optional[str] = None
    error: Optional[str] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        platform: PlatformType,
        post_id: str,
        publish_at: Optional[str] = None,
        raw_metadata: Optional[Dict[str, Any]] = None,
    ) -> PublishResult:
        return cls(
            success=True,
            platform=platform,
            post_id=post_id,
            publish_at=publish_at,
            raw_metadata=raw_metadata or {},
        )

    @classmethod
    def fail(
        cls,
        platform: PlatformType,
        error: str,
        raw_metadata: Optional[Dict[str, Any]] = None,
    ) -> PublishResult:
        return cls(
            success=False,
            platform=platform,
            error=error,
            raw_metadata=raw_metadata or {},
        )
