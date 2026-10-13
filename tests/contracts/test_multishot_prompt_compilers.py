"""Tests for multi-shot provider-specific prompt compilers."""

from __future__ import annotations

import hashlib
import pytest

from lib.multishot_prompt_compilers import (
    compile_prompt,
    compile_kling_prompt,
    compile_runway_prompt,
    prompt_hash_for_provider,
)
from tests.fixtures.multishot_mochi import all_project_data, continuity_snapshot_for


def test_compile_prompt_distinguishes_providers():
    data = all_project_data()
    shots = {s["id"]: s for s in data["shot_plan"]["shots"]}
    context = {
        "project_title": data["project_title"],
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot": shots["shot_001"],
        "continuity_in": continuity_snapshot_for(1),
    }

    kling_prompt = compile_prompt("kling_official", context)
    runway_prompt = compile_prompt("runway", context)

    assert "PROJECT:" in kling_prompt
    assert "PROJECT:" in runway_prompt
    # Runway prompt includes provider-specific negative constraints
    assert "stable cinematic motion" in runway_prompt
    assert "stable cinematic motion" not in kling_prompt


def test_prompt_hash_for_provider():
    prompt = "A friendly fox walks through a magical forest."
    expected = "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert prompt_hash_for_provider("kling_official", prompt) == expected
    assert prompt_hash_for_provider("runway", prompt) == expected


def test_prepare_generation_binds_provider_compiled_prompt(tmp_path):
    from tests.contracts.test_multishot_generation_preflight import _setup_session, _first_shot_id
    from lib.multishot_generation import prepare_generation

    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)

    spec = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )

    shot = session.get_state()["shots"][shot_id]
    assert shot["bound_input"]["prompt"] == spec.prompt
    assert shot["job_spec"]["prompt"] == shot["bound_input"]["prompt"]
