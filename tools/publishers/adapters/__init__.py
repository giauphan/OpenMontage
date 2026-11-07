from __future__ import annotations

from typing import Dict, Optional

from lib.application.publishing.ports import SocialPublisherPort
from lib.domain.publishing.entities import PlatformType
from tools.publishers.adapters.facebook_adapter import FacebookAdapter
from tools.publishers.adapters.tiktok_adapter import TikTokAdapter
from tools.publishers.adapters.youtube_adapter import YouTubeAdapter


def create_publisher_registry(
    yt_client: Optional[object] = None,
    fb_client: Optional[object] = None,
    tt_client: Optional[object] = None,
) -> Dict[PlatformType, SocialPublisherPort]:
    """Factory creating adapters conforming to SocialPublisherPort."""
    return {
        PlatformType.YOUTUBE: YouTubeAdapter(yt_client),
        PlatformType.FACEBOOK: FacebookAdapter(fb_client),
        PlatformType.TIKTOK: TikTokAdapter(tt_client),
    }


__all__ = [
    "YouTubeAdapter",
    "FacebookAdapter",
    "TikTokAdapter",
    "create_publisher_registry",
]
