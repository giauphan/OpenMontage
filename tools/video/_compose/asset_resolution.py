"""Asset resolution and media mapping helpers for composition.

Pure, deterministic helpers for mapping cuts to assets, detecting image media,
and translating cuts to cinematic scenes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Set

IMAGE_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}


def is_image(path: str | Path) -> bool:
    """Return True if the file path has a recognized image extension."""
    if not path:
        return False
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def build_asset_lookup(asset_manifest: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build an ID -> asset dictionary from an asset_manifest."""
    if not asset_manifest:
        return {}
    return {a["id"]: a for a in asset_manifest.get("assets", []) if isinstance(a, dict) and "id" in a}


def resolve_cuts(
    cuts: list[dict[str, Any]],
    asset_manifest: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Resolve asset IDs in cuts[].source to concrete file paths."""
    if not cuts:
        return []
    lookup = build_asset_lookup(asset_manifest)
    if not lookup:
        return [dict(c) for c in cuts]

    resolved = []
    for cut in cuts:
        c = dict(cut)
        source_id = c.get("source", "")
        if source_id in lookup:
            asset = lookup[source_id]
            if "path" in asset:
                c["source"] = asset["path"]
        resolved.append(c)
    return resolved


def cuts_to_cinematic_scenes(cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt canonical sequential cuts to CinematicRenderer's scene contract."""
    scenes: list[dict[str, Any]] = []
    timeline_cursor = 0.0
    hard_transitions = {"cut", "none"}
    title_types = {"hero_title", "text_card", "title"}

    for index, cut in enumerate(cuts):
        try:
            source_in = float(cut.get("in_seconds", 0))
            source_out = float(cut.get("out_seconds", source_in))
            speed = max(float(cut.get("speed", 1.0)), 0.1)
        except (TypeError, ValueError):
            continue
        duration = max(0.0, (source_out - source_in) / speed)
        if duration <= 0:
            continue

        scene_id = str(cut.get("id") or f"cut-{index + 1}")
        source = str(cut.get("source") or "")
        cut_type = str(cut.get("type") or "").lower()
        common = {
            "id": scene_id,
            "startSeconds": timeline_cursor,
            "durationSeconds": duration,
        }

        if cut_type in title_types or not source:
            scene: dict[str, Any] = {
                **common,
                "kind": "title",
                "text": str(
                    cut.get("text")
                    or cut.get("title")
                    or cut.get("reason")
                    or scene_id
                ),
            }
            if source:
                scene["backgroundSrc"] = source
                scene["backgroundTrimBeforeSeconds"] = source_in
                scene["backgroundTrimAfterSeconds"] = source_out
        else:
            scene = {
                **common,
                "kind": "video",
                "src": source,
                "trimBeforeSeconds": source_in,
                "trimAfterSeconds": source_out,
                "playbackRate": speed,
            }
            if str(cut.get("transition_in") or "").lower() in hard_transitions:
                scene["fadeInFrames"] = 0
            if str(cut.get("transition_out") or "").lower() in hard_transitions:
                scene["fadeOutFrames"] = 0

        scenes.append(scene)
        timeline_cursor += duration

    return scenes
