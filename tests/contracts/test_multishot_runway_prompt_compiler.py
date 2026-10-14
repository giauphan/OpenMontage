"""Contracts for capability-aware Runway multishot prompt compilation."""
from __future__ import annotations

from lib.multishot_generation import prepare_generation
from lib.multishot_prompt_compiler import compile_multishot_prompt
from tests.contracts.test_multishot_generation_preflight import _first_shot_id, _setup_session


def test_runway_i2v_prompt_is_positive_motion_focused(tmp_path):
    _, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    spec = prepare_generation(
        tmp_path,
        shot_id,
        provider="runway",
        model="gen4_turbo",
        settings={"operation": "image_to_video", "ratio": "9:16"},
        spend_approved=True,
        budget_usd=10.0,
        estimated_usd=1.0,
        reference_store=store,
        reference_review=review,
    )

    assert spec.prompt_compiler_version == "runway_i2v_v1"
    assert "NEGATIVE CONSTRAINTS:" not in spec.prompt
    assert "PROJECT:" not in spec.prompt
    assert "Motion:" in spec.prompt
    assert "Camera:" in spec.prompt
    assert "Preserve identity:" in spec.prompt
    assert "no " not in spec.prompt.lower()
    assert len(spec.prompt.split()) <= 90


def test_generic_prompt_compiler_keeps_full_sections(tmp_path):
    _, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    spec = prepare_generation(
        tmp_path,
        shot_id,
        provider="kling_official",
        model="kling-v1",
        settings={},
        spend_approved=True,
        budget_usd=10.0,
        estimated_usd=1.0,
        reference_store=store,
        reference_review=review,
    )

    assert spec.prompt_compiler_version == "generic_multishot_v1"
    assert "NEGATIVE CONSTRAINTS:" in spec.prompt
    assert "PROJECT:" in spec.prompt


def test_runway_prompt_compiler_rejects_unknown_operation():
    source = {
        "project_title": "demo",
        "request": {"topic": "demo"},
        "story": {"summary": "demo"},
        "character_bible": {"characters": []},
        "style_bible": {"visual_style": "bright 3D"},
        "shot": {"id": "shot_001", "action": "Mochi waves", "camera": "medium shot", "duration_sec": 5},
        "continuity_in": {},
        "references": [],
    }
    try:
        compile_multishot_prompt(source, provider="runway", model="gen4_turbo", settings={"operation": "text_to_video"})
    except ValueError as exc:
        assert "image_to_video" in str(exc)
    else:
        raise AssertionError("Runway text_to_video prompt compilation should fail closed")
