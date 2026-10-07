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
import json
from typing import Any

from lib.multishot_schemas import MultishotValidationError

_STATE_KEYS = ("character_state", "environment_state", "object_state")


def initial_continuity() -> dict[str, Any]:
    """Return a fresh continuity state with nothing accepted yet."""
    return {
        "version": 1,
        "accepted_through_shot": None,
        "accepted_end_state_fingerprint": None,
        "accepted_end_state": None,
        "accepted_order": None,
        "character_state": {},
        "environment_state": {},
        "object_state": {},
    }


def snapshot(continuity: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied immutable snapshot of the given state."""
    return copy.deepcopy(continuity)


def _merge_state(current: dict[str, Any], end_state: dict[str, Any]) -> dict[str, Any]:
    """Merge an end_state payload into a continuity state; deep-copy both inputs.

    The returned state is a new object; neither ``current`` nor ``end_state``
    may be mutated to affect the result. Nested lists and dicts are copied.
    """
    updated = snapshot(current)
    for key in _STATE_KEYS:
        src_val = end_state.get(key, {})
        if isinstance(src_val, dict):
            updated[key].update({k: copy.deepcopy(v) for k, v in src_val.items()})
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
    if continuity.get("accepted_through_shot") == shot_id:
        if shot_order != expected_order:
            raise MultishotValidationError(
                f"Cannot re-accept shot {shot_id!r} at order {shot_order}; "
                f"expected order {expected_order}"
            )
        fingerprint = json.dumps(end_state, sort_keys=True)
        if continuity.get("accepted_end_state_fingerprint") != fingerprint:
            raise MultishotValidationError(
                f"Cannot re-accept shot {shot_id!r} with changed end state"
            )
        # Prevent re-accepting the same shot id with new same arbitrary order.
        accepted_order = continuity.get("accepted_order")
        # Ensure that if it has accepted order previously, it must match.
        if accepted_order is not None and accepted_order != shot_order:
            raise MultishotValidationError(
                f"Cannot re-accept shot {shot_id!r} at changed order {shot_order}, previous was {accepted_order}"
            )
        # Even legacy states that have been loaded without accepted_order should have expected_order contiguous matching previous shot count

        return snapshot(continuity)
    if shot_order != expected_order:
        raise MultishotValidationError(
            f"Cannot accept shot {shot_id!r} at order {shot_order}; "
            f"expected next order {expected_order}"
        )
    fingerprint = json.dumps(end_state, sort_keys=True)
    updated = _merge_state(continuity, end_state)
    updated["version"] = continuity.get("version", 1) + 1
    updated["accepted_through_shot"] = shot_id
    updated["accepted_end_state_fingerprint"] = fingerprint
    updated["accepted_end_state"] = copy.deepcopy(end_state)
    updated["accepted_order"] = shot_order
    return updated


def continuity_in_for_shot(
    continuity: dict[str, Any],
    shot_order: int,
    expected_previous_shot_id: str | None = None,
) -> dict[str, Any]:
    """Return the exact continuity input a shot at ``shot_order`` must use.

    Shot order 1 binds the initial state. Later shots bind the current
    accepted state, which must already have been advanced past the
    predecessor.
    """
    if shot_order == 1:
        return initial_continuity()

    if expected_previous_shot_id is None:
        raise MultishotValidationError(
            f"Fail closed: Shot order {shot_order} requires explicit expected_previous_shot_id context"
        )

    if continuity.get("accepted_through_shot") != expected_previous_shot_id:
        raise MultishotValidationError(
            f"Shot order {shot_order} requires immediately preceding shot ({expected_previous_shot_id!r}) to be accepted"
        )

    accepted_order = continuity.get("accepted_order")
    if accepted_order is not None and accepted_order != shot_order - 1:
        raise MultishotValidationError(
            f"expected next order"
        )

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
    # Return in plan order, not alphabetical order, for deterministic staleness lists
    downstream = [(sid, order) for sid, order in shot_orders.items() if order > reg_order]
    downstream.sort(key=lambda pair: pair[1])
    return [sid for sid, _ in downstream]


def failed_shot_continuity_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
    failed_shot_id: str,
) -> bool:
    """True when a failed generation left continuity state unchanged.

    A failed shot must not alter any part of continuity state.
    """
    return snapshot(before) == snapshot(after)
