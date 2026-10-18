"""FFmpeg hook adapter for materializing title card assets and overlay injection."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Optional

from lib.hook_guard.adapters.base import BaseHookAdapter
from lib.hook_guard.adapters.remotion import RemotionHookAdapter
from lib.hook_guard.config import PlatformProfile


class FFmpegHookAdapter(BaseHookAdapter):
    """Adapter for FFmpeg composition runtime."""

    def __init__(self) -> None:
        self._remotion_helper = RemotionHookAdapter()

    def materialize_asset(
        self,
        candidate: dict[str, Any],
        project_dir: Path | str,
        video_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._remotion_helper.materialize_asset(
            candidate, project_dir, video_metadata=video_metadata
        )

    def apply_overlay(
        self,
        edl: dict[str, Any],
        candidate: dict[str, Any],
        asset: dict[str, Any],
        profile: Optional[PlatformProfile] = None,
    ) -> dict[str, Any]:
        return self._remotion_helper.apply_overlay(edl, candidate, asset, profile=profile)
