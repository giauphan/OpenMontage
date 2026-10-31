"""Audience retention curve mapping and structured hypothesis generation.

This module maps raw 100-point YouTube audience retention curves to video scenes,
preserves replay spikes (>100% watch ratio), handles missing/lagged analytics gracefully,
and structures hypotheses for review without autonomous policy mutation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


@dataclass(frozen=True)
class SceneTiming:
    """Represents a bounded scene beat within a video composition."""
    scene_id: str
    start_time: float
    end_time: float
    story_function: str = ""


@dataclass(frozen=True)
class RetentionPoint:
    """A discrete sample along the video duration curve."""
    ratio: float
    watch_ratio: float
    timestamp_seconds: float
    scene_id: str | None = None


@dataclass
class HypothesisEntry:
    """A structured, evidence-grounded hypothesis for viewer behavior."""
    observation: str
    observed_timestamp: str
    scene_id: str | None
    possible_causes: list[str]
    competing_hypotheses: list[str]
    proposed_change: str
    confidence: str  # LOW, MEDIUM, HIGH
    recheck_date: str
    owner_status: str = "PENDING_REVIEW"


@dataclass
class RetentionAnalysis:
    """Processed retention analysis for a video project."""
    video_id: str
    project_id: str
    duration: float
    points: list[RetentionPoint] = field(default_factory=list)
    scene_retention: dict[str, float] = field(default_factory=dict)
    dropoffs: list[dict] = field(default_factory=list)
    spikes: list[dict] = field(default_factory=list)
    status: str = "OK"  # "OK", "UNKNOWN", "DATA_LAGGED"


def _find_scene_for_timestamp(t: float, scenes: Sequence[SceneTiming]) -> str | None:
    """Matches a timestamp in seconds to its corresponding scene beat."""
    if not scenes:
        return None
    for idx, sc in enumerate(scenes):
        is_last = (idx == len(scenes) - 1)
        if sc.start_time <= t < sc.end_time or (is_last and sc.start_time <= t <= (sc.end_time + 0.05)):
            return sc.scene_id
    # Fallback if t slightly overshoots last scene end
    if t >= scenes[-1].start_time:
        return scenes[-1].scene_id
    return scenes[0].scene_id


def map_retention_curve(
    duration_seconds: float,
    retention_curve: Sequence[tuple[float, float]],
    scenes: Sequence[SceneTiming],
    video_id: str = "",
    project_id: str = "",
) -> RetentionAnalysis:
    """Maps a 100-point retention curve to scene beats.

    Args:
        duration_seconds: Total duration of the video in seconds.
        retention_curve: List of (elapsed_ratio, watch_ratio) tuples.
            elapsed_ratio is 0.0 to 1.0 (or 0% to 100%).
            watch_ratio is audienceWatchRatio (can exceed 1.0 for replays).
        scenes: Sequence of SceneTiming definitions.
        video_id: Associated YouTube Video ID.
        project_id: Local project build directory / slug.

    Returns:
        RetentionAnalysis containing mapped points, per-scene means, spikes, and dropoffs.
    """
    if not retention_curve or duration_seconds <= 0.0:
        return RetentionAnalysis(
            video_id=video_id,
            project_id=project_id,
            duration=max(0.0, duration_seconds),
            points=[],
            scene_retention={},
            dropoffs=[],
            spikes=[],
            status="DATA_LAGGED" if duration_seconds > 0.0 else "UNKNOWN",
        )

    points: list[RetentionPoint] = []
    scene_points: dict[str, list[float]] = {}

    for ratio, watch_ratio in retention_curve:
        # Standardize ratio if given in 0-100 range
        norm_ratio = ratio / 100.0 if ratio > 1.0 else ratio
        t = norm_ratio * duration_seconds
        scene_id = _find_scene_for_timestamp(t, scenes)

        # IMPORTANT: watch_ratio is NEVER clamped to 1.0; replay spikes > 1.0 are preserved
        point = RetentionPoint(
            ratio=norm_ratio,
            watch_ratio=watch_ratio,
            timestamp_seconds=round(t, 3),
            scene_id=scene_id,
        )
        points.append(point)

        if scene_id:
            scene_points.setdefault(scene_id, []).append(watch_ratio)

    scene_retention: dict[str, float] = {
        sid: round(sum(vals) / len(vals), 4)
        for sid, vals in scene_points.items()
        if vals
    }

    # Detect dropoffs and spikes
    dropoffs: list[dict] = []
    spikes: list[dict] = []

    for i in range(1, len(points)):
        prev = points[i - 1]
        curr = points[i]
        diff = curr.watch_ratio - prev.watch_ratio

        if curr.watch_ratio > 1.0 or diff >= 0.05:
            spikes.append({
                "timestamp_seconds": curr.timestamp_seconds,
                "scene_id": curr.scene_id,
                "watch_ratio": curr.watch_ratio,
                "spike_magnitude": round(diff, 4),
            })
        elif diff <= -0.10:
            dropoffs.append({
                "timestamp_seconds": curr.timestamp_seconds,
                "scene_id": curr.scene_id,
                "from_ratio": prev.watch_ratio,
                "to_ratio": curr.watch_ratio,
                "drop_magnitude": round(abs(diff), 4),
            })

    # Also detect scene-to-scene drops
    scene_ids = [sc.scene_id for sc in scenes if sc.scene_id in scene_retention]
    for i in range(1, len(scene_ids)):
        prev_sid = scene_ids[i - 1]
        curr_sid = scene_ids[i]
        prev_val = scene_retention[prev_sid]
        curr_val = scene_retention[curr_sid]
        if prev_val - curr_val >= 0.15:
            # Check if already noted in dropoffs
            if not any(d.get("scene_id") == curr_sid for d in dropoffs):
                dropoffs.append({
                    "timestamp_seconds": next((sc.start_time for sc in scenes if sc.scene_id == curr_sid), 0.0),
                    "scene_id": curr_sid,
                    "from_ratio": prev_val,
                    "to_ratio": curr_val,
                    "drop_magnitude": round(prev_val - curr_val, 4),
                })

    return RetentionAnalysis(
        video_id=video_id,
        project_id=project_id,
        duration=duration_seconds,
        points=points,
        scene_retention=scene_retention,
        dropoffs=dropoffs,
        spikes=spikes,
        status="OK",
    )


def generate_hypotheses_from_analysis(analysis: RetentionAnalysis) -> list[HypothesisEntry]:
    """Generates structured hypotheses from retention dropoffs for human owner review.

    Strictly adheres to policy: Never mutates prompts, niches, or schedules autonomously.
    Missing or lagged data yields zero hypotheses (no speculative conclusions).
    """
    if analysis.status != "OK" or not analysis.points or not analysis.dropoffs:
        return []

    now_iso = datetime.now(timezone.utc).isoformat()
    hypotheses: list[HypothesisEntry] = []

    for drop in analysis.dropoffs:
        sid = drop.get("scene_id")
        ts = drop.get("timestamp_seconds", 0.0)
        mag = drop.get("drop_magnitude", 0.0)

        obs = f"Retention dropped by {mag * 100:.1f}% at t={ts}s (scene: {sid or 'unknown'})."
        
        possible_causes = [
            "Pacing lag: narrative exposition lingered before visual proof appeared",
            "Visual complexity: viewer needed more time to parse diagram or text",
            "Topic mismatch: opening hook raised an expectation that was not immediately resolved",
        ]
        competing = [
            "Normal viewer natural drop-off after opening 5-15s hook resolution",
            "External platform factor (feed swipe / mobile distraction) uncorrelated with scene content",
        ]
        proposed = (
            f"Review scene {sid}: consider bringing authentic proof visual earlier in the beat "
            "or tightening narration by 1-2 seconds without altering niche policy."
        )

        hypotheses.append(HypothesisEntry(
            observation=obs,
            observed_timestamp=now_iso,
            scene_id=sid,
            possible_causes=possible_causes,
            competing_hypotheses=competing,
            proposed_change=proposed,
            confidence="LOW" if mag < 0.20 else "MEDIUM",
            recheck_date="7d",
            owner_status="PENDING_REVIEW",
        ))

    return hypotheses
