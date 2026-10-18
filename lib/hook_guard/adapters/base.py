"""Base adapter interface for HookGuard runtime-specific overlays."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from lib.hook_guard.config import PlatformProfile


class BaseHookAdapter(ABC):
    """Abstract base class for HookGuard runtime overlay adapters."""

    @abstractmethod
    def materialize_asset(
        self,
        candidate: dict[str, Any],
        project_dir: Path | str,
        video_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a concrete image or visual asset representing the hook text.
        
        Returns an asset dict ready for inclusion in `asset_manifest.assets`.
        """
        pass

    @abstractmethod
    def apply_overlay(
        self,
        edl: dict[str, Any],
        candidate: dict[str, Any],
        asset: dict[str, Any],
        profile: Optional[PlatformProfile] = None,
    ) -> dict[str, Any]:
        """Inject the hook overlay into `edit_decisions` preserving all body cuts.
        
        Returns a mutated copy of `edl`.
        """
        pass

    def rollback_overlay(self, edl: dict[str, Any]) -> dict[str, Any]:
        """Purge hook overlays from `edit_decisions`, restoring original body schedule."""
        clean_edl = copy.deepcopy(edl)
        raw_overlays = clean_edl.get("overlays", [])
        clean_overlays = []
        for ov in raw_overlays:
            aid = str(ov.get("asset_id", ""))
            meta = ov.get("metadata", {})
            if isinstance(meta, dict) and meta.get("is_hook"):
                continue
            if aid.startswith("hook_"):
                continue
            clean_overlays.append(ov)
        clean_edl["overlays"] = clean_overlays
        return clean_edl
