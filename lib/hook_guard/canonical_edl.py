"""Canonical Body EDL normalization, fingerprinting, and preservation verification."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Optional


def _round_float(val: Any, decimals: int = 4) -> Any:
    if isinstance(val, (int, float)):
        return round(float(val), decimals)
    return val


def _normalize_transform(transform: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not transform or not isinstance(transform, dict):
        return {
            "scale": 1.0,
            "position": "center",
            "animation": None,
            "crop": None,
        }
    return {
        "scale": _round_float(transform.get("scale", 1.0)),
        "position": str(transform.get("position", "center")),
        "animation": transform.get("animation"),
        "crop": transform.get("crop"),
    }


def _normalize_cut(cut: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(cut.get("id", "")),
        "source": str(cut.get("source", "")),
        "in_seconds": _round_float(cut.get("in_seconds", 0.0)),
        "out_seconds": _round_float(cut.get("out_seconds", 0.0)),
        "speed": _round_float(cut.get("speed", 1.0)),
        "layer": str(cut.get("layer", "primary")),
        "transform": _normalize_transform(cut.get("transform")),
        "transition_in": cut.get("transition_in"),
        "transition_out": cut.get("transition_out"),
        "transition_duration": _round_float(cut.get("transition_duration", 0.0)) if cut.get("transition_duration") is not None else None,
        "backgroundColor": cut.get("backgroundColor"),
    }


def _is_hook_cut(cut: dict[str, Any]) -> bool:
    cid = str(cut.get("id", ""))
    reason = str(cut.get("reason", ""))
    meta = cut.get("metadata", {})
    if isinstance(meta, dict) and meta.get("is_hook_preroll"):
        return True
    return cid.startswith("hook_preroll") or "hook_preroll" in reason


def _is_hook_overlay(overlay: dict[str, Any]) -> bool:
    aid = str(overlay.get("asset_id", ""))
    meta = overlay.get("metadata", {})
    if isinstance(meta, dict) and meta.get("is_hook"):
        return True
    return aid.startswith("hook_") or "hook_overlay" in aid


def canonicalize_body_edl(
    edl: dict[str, Any],
    exclude_preroll: bool = True,
    time_offset: float = 0.0,
) -> dict[str, Any]:
    """Produce a deterministic, normalized representation of the body EDL.
    
    In overlay mode:
      - Ignores hook overlays in `overlays` array.
      - Keeps canonical cuts and body audio schedule.
      
    In pre-roll mode:
      - If `exclude_preroll` is True, ignores tagged pre-roll cuts.
      - Normalizes audio start times by subtracting `time_offset`.
    """
    raw_cuts = edl.get("cuts", [])
    normalized_cuts: list[dict[str, Any]] = []

    for c in raw_cuts:
        if not isinstance(c, dict):
            continue
        if exclude_preroll and _is_hook_cut(c):
            continue
        normalized_cuts.append(_normalize_cut(c))

    # Normalize audio
    audio = edl.get("audio", {})
    normalized_audio: dict[str, Any] = {}

    if isinstance(audio, dict):
        # Narration
        narration = audio.get("narration", {})
        if isinstance(narration, dict):
            raw_segments = narration.get("segments", [])
            norm_segments = []
            for seg in raw_segments:
                if not isinstance(seg, dict):
                    continue
                start_sec = max(0.0, float(seg.get("start_seconds", 0.0)) - time_offset)
                end_sec = max(0.0, float(seg["end_seconds"]) - time_offset) if "end_seconds" in seg else None
                norm_seg = {
                    "asset_id": str(seg.get("asset_id", "")),
                    "start_seconds": _round_float(start_sec),
                }
                if end_sec is not None:
                    norm_seg["end_seconds"] = _round_float(end_sec)
                norm_segments.append(norm_seg)
            normalized_audio["narration"] = {"segments": norm_segments}

        # Music
        music = audio.get("music", edl.get("music", {}))
        if isinstance(music, dict) and music:
            normalized_audio["music"] = {
                "asset_id": str(music.get("asset_id", "")),
                "volume": _round_float(music.get("volume", 1.0)),
                "fade_in_seconds": _round_float(music.get("fade_in_seconds", 0.0)),
                "fade_out_seconds": _round_float(music.get("fade_out_seconds", 0.0)),
                "ducking": music.get("ducking", True),
            }

        # SFX
        sfx_list = audio.get("sfx", [])
        if isinstance(sfx_list, list):
            norm_sfx = []
            for s in sfx_list:
                if not isinstance(s, dict):
                    continue
                norm_sfx.append({
                    "asset_id": str(s.get("asset_id", "")),
                    "start_seconds": _round_float(max(0.0, float(s.get("start_seconds", 0.0)) - time_offset)),
                    "volume": _round_float(s.get("volume", 1.0)),
                })
            normalized_audio["sfx"] = norm_sfx

    # Non-hook overlays
    raw_overlays = edl.get("overlays", [])
    non_hook_overlays = []
    for ov in raw_overlays:
        if not isinstance(ov, dict):
            continue
        if _is_hook_overlay(ov):
            continue
        pos = ov.get("position", {})
        norm_ov = {
            "asset_id": str(ov.get("asset_id", "")),
            "start_seconds": _round_float(max(0.0, float(ov.get("start_seconds", 0.0)) - time_offset)),
            "end_seconds": _round_float(max(0.0, float(ov.get("end_seconds", 0.0)) - time_offset)),
            "position": {
                "x": _round_float(pos.get("x", 0)),
                "y": _round_float(pos.get("y", 0)),
                "width": _round_float(pos.get("width")),
                "height": _round_float(pos.get("height")),
            },
            "animation": ov.get("animation"),
            "opacity": _round_float(ov.get("opacity", 1.0)),
        }
        non_hook_overlays.append(norm_ov)

    return {
        "version": "1.0",
        "cuts": normalized_cuts,
        "audio": normalized_audio,
        "overlays": non_hook_overlays,
        "render_runtime": str(edl.get("render_runtime", "")),
        "renderer_family": str(edl.get("renderer_family", "")),
    }


def compute_body_edl_fingerprint(
    edl: dict[str, Any],
    exclude_preroll: bool = True,
    time_offset: float = 0.0,
) -> str:
    """Compute deterministic SHA-256 fingerprint of the canonical body EDL."""
    canonical = canonicalize_body_edl(edl, exclude_preroll=exclude_preroll, time_offset=time_offset)
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_body_edl_preservation(
    baseline_fingerprint: str,
    mutated_edl: dict[str, Any],
    mode: str = "overlay",
    preroll_duration: float = 0.0,
) -> tuple[bool, str]:
    """Verify that the mutated EDL exactly preserves the baseline body EDL.
    
    Returns (True, "") on exact match, or (False, reason) on mismatch.
    """
    if not baseline_fingerprint:
        return False, "Empty or missing baseline body EDL fingerprint"

    if mode in ("overlay", "overlay_text", "caption_emphasis"):
        current_fp = compute_body_edl_fingerprint(mutated_edl, exclude_preroll=True, time_offset=0.0)
    elif mode == "extractive_preroll":
        current_fp = compute_body_edl_fingerprint(
            mutated_edl,
            exclude_preroll=True,
            time_offset=preroll_duration,
        )
    else:
        current_fp = compute_body_edl_fingerprint(mutated_edl, exclude_preroll=True, time_offset=0.0)

    if current_fp == baseline_fingerprint:
        return True, ""
    return False, f"Body EDL fingerprint mismatch: baseline {baseline_fingerprint} != current {current_fp}"
