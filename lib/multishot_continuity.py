"""Continuity engine for the multi-shot pipeline.

Implements the state transition rules from the multi-shot data contract:
planned continuity snapshots are separate from accepted continuity, and
acceptance increments the version only once. Stale propagation happens
transitively when a material end-state changes.

No provider calls, no filesystem writes, no orchestration. This module
operates on the plain dicts that persist as ``continuity_state`` artifacts.
"""

from __future__ import annotations

import copy
from typing import Any

from lib.multishot_schemas import MultishotValidationError

_STATE_KEYS = ("character_state", "environment_state", "object_state")


def initial_continuity() -> dict[str, Any]:
    """Return a fresh continuity state with nothing accepted yet."""
    return {
        "version": 1,
        "accepted_through_shot": None,
        "character_state": {},
        "environment_state": {},
        "object_state": {},
    }


def snapshot(continuity: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied immutable snapshot of the given state."""
    return copy.deepcopy(continuity)


def _merge_state(current: dict[str, Any], end_state: dict[str, Any]) -> dict[str, Any]:
    """Merge an end_state payload into a continuity state without mutating the input."""
    updated = snapshot(current)
    for key in _STATE_KEYS:
        updated[key].update(end_state.get(key, {}))
    return updated


def accept_shot(
    continuity: dict[str, Any],
    shot_id: str,
    end_state: dict[str, Any],
    *,
    expected_order: int,
    shot_order: int,
) -> dict[str, Any]:
    """Advance continuity after a shot has been explicitly accepted.

    Idempotence:
        Calling twice with the same ``shot_id`` returns an identical state
        (no version bump on repeat).

    Raises:
        MultishotValidationError if the shot order does not match the
        expected contiguous position.
    """
    if continuity["accepted_through_shot"] == shot_id:
        return snapshot(continuity)
    if shot_order != expected_order:
        raise MultishotValidationError(
            f"Cannot accept shot {shot_id!r} at order {shot_order}; "
            f"expected next order {expected_order}"
        )
    updated = _merge_state(continuity, end_state)
    updated["version"] = continuity["version"] + 1
    updated["accepted_through_shot"] = shot_id
    return updated


def continuity_in_for_shot(
    continuity: dict[str, Any],
    shot_order: int,
) -> dict[str, Any]:
    """Return the exact continuity input a shot at ``shot_order`` must use.

    Shot order 1 binds the initial state. Later shots bind the current
    accepted state, which must already have been advanced past the
    predecessor.
    """
    if shot_order == 1:
        return initial_continuity()
    return snapshot(continuity)


def retry_continuity_in(
    continuity: dict[str, Any],
) -> dict[str, Any]:
    """Return the exact continuity snapshot a same-input retry must use.

    Same-input retry must use the identical continuity input it was
    originally submitted with — the current accepted state, deep-copied so
    the caller cannot mutate it.
    """
    return snapshot(continuity)


def mark_downstream_stale(
    shot_orders: dict[str, int],
    regenerated_shot_id: str,
) -> list[str]:
    """Return shot ids that must be marked STALE after a material end-state change.

    A material accepted end-state change invalidates all shots whose order
    is strictly greater than the regenerated shot's order, transitively.
    """
    if regenerated_shot_id not in shot_orders:
        raise MultishotValidationError(
            f"mark_downstream_stale: unknown shot {regenerated_shot_id!r}"
        )
    reg_order = shot_orders[regenerated_shot_id]
    return sorted(sid for sid, order in shot_orders.items() if order > reg_order)


def failed_shot_continuity_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
    failed_shot_id: str,
) -> bool:
    """True when a failed generation left continuity state unchanged.

    A failed shot must not advance ``accepted_through_shot``. If both states
    agree once the failed shot is excluded, the contract holds.
    """
    b = snapshot(before)
    a = snapshot(after)
    for state in (b, a):
        if state["accepted_through_shot"] == failed_shot_id:
            state["accepted_through_shot"] = None
    return b == a
