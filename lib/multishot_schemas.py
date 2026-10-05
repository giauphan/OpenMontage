"""Cross-field validators for multi-shot pipeline artifacts.

JSON Schema 2020-12 cannot express some required constraints (unique-id,
unique-order, FK checks, min_shots >= 2, non-finite number rejection, and
duration feasibility). This module provides those checks on top of the
base schema validation in schemas/multishot/__init__.py.

All public functions raise ValueError (or a subclass) on failure and return
None (or a bool) on success.
"""

from __future__ import annotations

import math
from typing import Any

from schemas.multishot import validate, MULTISHOT_ARTIFACT_NAMES
import jsonschema


class MultishotValidationError(ValueError):
    """Raised when a multi-shot artifact fails cross-field validation."""


# ------------------------------------------------------------------
# Non-finite number rejection
# ------------------------------------------------------------------

def _assert_finite_numbers(obj: Any, path: str = "") -> None:
    """Recursively reject NaN and ±Infinity values in a JSON-compatible structure."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise MultishotValidationError(
                f"Non-finite number at {path or '<root>'}: {obj}"
            )
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _assert_finite_numbers(v, f"{path}.{k}" if path else f"{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_finite_numbers(v, f"{path}[{i}]")


# ------------------------------------------------------------------
# Story validator
# ------------------------------------------------------------------

def validate_story_cross_fields(story: dict) -> None:
    """Validate story schema + required beat coverage."""
    _assert_finite_numbers(story)
    beats = story.get("beats", [])
    types = {b["type"] for b in beats}
    has_closing = "resolution" in types or "punchline" in types
    missing = []
    for req in ("hook", "escalation", "climax"):
        if req not in types:
            missing.append(req)
    if not has_closing:
        missing.append("resolution|punchline")
    if missing:
        raise MultishotValidationError(
            f"Story beats missing required narrative coverage: {missing}"
        )


# ------------------------------------------------------------------
# Character bible validator
# ------------------------------------------------------------------

def validate_character_bible_cross_fields(bible: dict) -> None:
    """Validate character_bible schema + unique character ids."""
    _assert_finite_numbers(bible)
    chars = bible.get("characters", [])
    ids = [c["id"] for c in chars]
    dupes = [i for i in ids if ids.count(i) > 1]
    if dupes:
        raise MultishotValidationError(
            f"Duplicate character ids in character_bible: {sorted(set(dupes))}"
        )
    for c in chars:
        if not c.get("locked_identity", {}).get("type"):
            raise MultishotValidationError(
                f"Character {c.get('id')} missing locked_identity.type"
            )


# ------------------------------------------------------------------
# Style bible validator
# ------------------------------------------------------------------

def validate_style_bible_cross_fields(bible: dict) -> None:
    """Validate style_bible schema."""
    _assert_finite_numbers(bible)
    if not bible.get("render_rules"):
        raise MultishotValidationError(
            "style_bible.render_rules must have at least one entry"
        )


# ------------------------------------------------------------------
# Shot plan validator
# ------------------------------------------------------------------

def validate_shot_plan_cross_fields(
    shot_plan: dict,
    character_bible: dict | None = None,
    request: dict | None = None,
) -> None:
    """Validate shot_plan schema + cross-field constraints."""
    _assert_finite_numbers(shot_plan)
    shots = shot_plan.get("shots", [])
    if len(shots) < 2:
        raise MultishotValidationError(
            f"shot_plan must have at least 2 shots; got {len(shots)}"
        )

    ids = [s["id"] for s in shots]
    dup_ids = [i for i in ids if ids.count(i) > 1]
    if dup_ids:
        raise MultishotValidationError(
            f"Duplicate shot ids in shot_plan: {sorted(set(dup_ids))}"
        )

    orders = [s["order"] for s in shots]
    dup_orders = [o for o in orders if orders.count(o) > 1]
    if dup_orders:
        raise MultishotValidationError(
            f"Duplicate shot orders in shot_plan: {sorted(set(dup_orders))}"
        )

    sorted_orders = sorted(orders)
    if sorted_orders != list(range(1, len(shots) + 1)):
        raise MultishotValidationError(
            f"Shot orders must be contiguous 1..N; got {sorted_orders}"
        )

    if character_bible is not None:
        char_ids = {c["id"] for c in character_bible.get("characters", [])}
        for shot in shots:
            bad = [c for c in shot.get("characters", []) if c not in char_ids]
            if bad:
                raise MultishotValidationError(
                    f"Shot {shot['id']} references unknown character(s): {bad}"
                )

    if request is not None:
        policy = request.get("shot_policy", {})
        max_shots = policy.get("max_shots")
        if max_shots is not None and len(shots) > max_shots:
            raise MultishotValidationError(
                f"shot_plan has {len(shots)} shots; request.shot_policy.max_shots is {max_shots}"
            )


# ------------------------------------------------------------------
# Request validator
# ------------------------------------------------------------------

def validate_request_cross_fields(request: dict) -> None:
    """Validate request schema + shot_policy min/max consistency."""
    _assert_finite_numbers(request)
    policy = request.get("shot_policy", {})
    min_s = policy.get("min_shots")
    max_s = policy.get("max_shots")
    if min_s is not None and min_s < 2:
        raise MultishotValidationError(
            f"request.shot_policy.min_shots below minimum: must be >= 2; got {min_s}"
        )
    if min_s is not None and max_s is not None and max_s < min_s:
        raise MultishotValidationError(
            f"request.shot_policy.max_shots ({max_s}) < min_shots ({min_s})"
        )


# ------------------------------------------------------------------
# Continuity state validator
# ------------------------------------------------------------------

def validate_continuity_state_cross_fields(state: dict) -> None:
    """Validate continuity_state schema + version >= 1."""
    _assert_finite_numbers(state)
    ver = state.get("version")
    if not isinstance(ver, int) or ver < 1:
        raise MultishotValidationError(
            f"continuity_state.version must be int >= 1; got {ver!r}"
        )


# ------------------------------------------------------------------
# Job validator
# ------------------------------------------------------------------

def validate_job_cross_fields(job: dict) -> None:
    """Validate job schema + attempt bounds."""
    _assert_finite_numbers(job)
    attempt = job.get("attempt")
    max_attempts = job.get("max_attempts")
    if attempt is not None and max_attempts is not None and attempt > max_attempts:
        raise MultishotValidationError(
            f"job attempt ({attempt}) exceeds max_attempts ({max_attempts})"
        )


# ------------------------------------------------------------------
# Run manifest validator
# ------------------------------------------------------------------

def validate_run_manifest_cross_fields(manifest: dict) -> None:
    """Validate run_manifest schema + shot_count consistency."""
    _assert_finite_numbers(manifest)
    shot_count = manifest.get("shot_count")
    shots = manifest.get("shots", {})
    if shot_count is not None and len(shots) != shot_count:
        raise MultishotValidationError(
            f"run_manifest.shot_count ({shot_count}) != len(shots) ({len(shots)})"
        )


# ------------------------------------------------------------------
# Aggregate entry point
# ------------------------------------------------------------------

def validate_all_cross(
    request: dict | None = None,
    story: dict | None = None,
    character_bible: dict | None = None,
    style_bible: dict | None = None,
    shot_plan: dict | None = None,
    continuity_state: dict | None = None,
    job: dict | None = None,
    run_manifest: dict | None = None,
) -> None:
    """Validate provided multi-shot artifacts: base schema + cross-field rules.

    Base-schema failures are re-raised as MultishotValidationError so callers
    of this aggregate entry point see a single exception type. Shot-plan
    cross-field checks run before base validation so the friendly
    "at least 2 shots" message wins over the raw minItems error.
    """

    def _base(name: str, data: dict) -> None:
        try:
            validate(name, data)
        except jsonschema.ValidationError as exc:
            raise MultishotValidationError(
                f"{name} failed schema validation: {exc.message}"
            ) from exc

    if request is not None:
        _base("request", request)
        validate_request_cross_fields(request)
    if story is not None:
        _base("story", story)
        validate_story_cross_fields(story)
    if character_bible is not None:
        _base("character_bible", character_bible)
        validate_character_bible_cross_fields(character_bible)
    if style_bible is not None:
        _base("style_bible", style_bible)
        validate_style_bible_cross_fields(style_bible)
    if shot_plan is not None:
        validate_shot_plan_cross_fields(shot_plan, character_bible, request)
        _base("shot_plan", shot_plan)
    if continuity_state is not None:
        _base("continuity_state", continuity_state)
        validate_continuity_state_cross_fields(continuity_state)
    if job is not None:
        _base("job", job)
        validate_job_cross_fields(job)
    if run_manifest is not None:
        _base("run_manifest", run_manifest)
        validate_run_manifest_cross_fields(run_manifest)
