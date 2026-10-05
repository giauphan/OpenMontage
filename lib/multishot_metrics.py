"""Observability metrics for the multi-shot pipeline (plan §8).

Aggregates the required metrics from a scheduler run and the media stages.
No I/O, no provider calls — pure aggregation over the records the pipeline
already produces (``JobOutcome`` objects, timing samples, durations).

Metrics emitted (plan §8):
    project_total_time, planning_time, avg_generation_time_per_shot,
    attempts_per_shot, provider_failure_count, normalization_time,
    final_render_time, total_raw_duration, final_duration.

Dimensions (§8): provider, model, project_id, shot_id, error_type.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence


def _attempts_sum(outcomes: Sequence[Any]) -> int:
    return sum(len(o.attempts) for o in outcomes)


def _failed_codes(outcomes: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in outcomes:
        for a in o.attempts:
            if a.error_code:
                counts[a.error_code] = counts.get(a.error_code, 0) + 1
    return counts


def summarize_run(
    outcomes: Sequence[Any],
    *,
    planning_time_sec: float,
    normalization_time_sec: Optional[float] = None,
    final_render_time_sec: Optional[float] = None,
    total_raw_duration_sec: Optional[float] = None,
    final_duration_sec: Optional[float] = None,
    project_total_time_sec: Optional[float] = None,
) -> dict[str, Any]:
    """Return the §8 metric dictionary for one scheduler run.

    ``outcomes`` is the list of ``JobOutcome`` in plan order. Averages are
    computed over every shot, not just the successful ones, so flaky
    projects surface in ``attempts_per_shot``.
    """
    shot_count = len(outcomes)
    completed = [o for o in outcomes if o.status == "completed"]
    total_attempts = _attempts_sum(outcomes)

    generation_seconds: list[float] = []
    for o in outcomes:
        if o.attempts:
            generation_seconds.append(o.attempts[-1].finished_at - o.attempts[0].started_at)
    avg_generation = sum(generation_seconds) / len(generation_seconds) if generation_seconds else 0.0
    avg_attempts = total_attempts / shot_count if shot_count else 0.0

    failures = _failed_codes(outcomes)

    total = project_total_time_sec
    if total is None:
        total = planning_time_sec + sum(generation_seconds)
        if normalization_time_sec:
            total += normalization_time_sec
        if final_render_time_sec:
            total += final_render_time_sec

    return {
        "project_total_time_sec": total,
        "planning_time_sec": planning_time_sec,
        "avg_generation_time_per_shot_sec": round(avg_generation, 4),
        "attempts_per_shot": round(avg_attempts, 4),
        "provider_failure_count": sum(failures.values()),
        "provider_failures_by_code": failures,
        "normalization_time_sec": normalization_time_sec,
        "final_render_time_sec": final_render_time_sec,
        "total_raw_duration_sec": total_raw_duration_sec,
        "final_duration_sec": final_duration_sec,
        "shots": shot_count,
        "shots_completed": len(completed),
    }


def dimension(
    *,
    provider: str,
    model: str,
    project_id: str,
    shot_id: Optional[str] = None,
    error_type: Optional[str] = None,
) -> dict[str, Any]:
    """Return the §8 dimension labels for a single metric datapoint."""
    return {
        "provider": provider,
        "model": model,
        "project_id": project_id,
        "shot_id": shot_id,
        "error_type": error_type,
    }
