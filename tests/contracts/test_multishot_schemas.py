"""Multi-shot schema and cross-field validation tests (M0, TASK 001).

Tests cover all 8 schemas plus the Python cross-field validators for:
  - min_shots >= 2
  - duplicate shot ids / orders rejected
  - missing end_state rejected
  - valid 2-shot plan accepted
  - valid 25-shot plan accepted
  - shot count within max_shots range
  - character FK validation
  - non-finite number rejection
  - story beat coverage
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.multishot_schemas import (
    MultishotValidationError,
    validate_request_cross_fields,
    validate_story_cross_fields,
    validate_character_bible_cross_fields,
    validate_style_bible_cross_fields,
    validate_shot_plan_cross_fields,
    validate_continuity_state_cross_fields,
    validate_job_cross_fields,
    validate_run_manifest_cross_fields,
    validate_all_cross,
)
from schemas.multishot import list_schemas, validate


_BASE_REQUEST = {
    "topic": "A funny cat cooking noodles",
    "aspect_ratio": "9:16",
    "resolution": {"width": 1080, "height": 1920},
    "fps": 30,
    "shot_policy": {"min_shots": 2, "max_shots": 8},
}

_BASE_STORY = {
    "version": "1.0",
    "title": "Mochi Cooking Disaster",
    "topic": "Funny cooking animation",
    "beats": [
        {"id": "beat_01", "type": "hook", "summary": "Mochi starts cooking."},
        {"id": "beat_02", "type": "escalation", "summary": "Mistakes escalate."},
        {"id": "beat_03", "type": "climax", "summary": "Explosion of flour."},
        {"id": "beat_04", "type": "punchline", "summary": "Mochi sees instructions too late."},
    ],
    "characters": ["Mochi"],
    "locations": ["Kitchen"],
    "important_props": ["noodle packet", "pot"],
}

_BASE_CHARACTER_BIBLE = {
    "version": "1.0",
    "characters": [
        {
            "id": "char_mochi",
            "name": "Mochi",
            "role": "main",
            "locked_identity": {
                "type": "chubby orange cartoon cat",
                "body": "round body, short legs",
                "face": "round face",
                "eyes": "large green eyes",
                "fur": "orange with cream belly",
                "markings": "consistent orange stripes",
                "clothing": ["white chef hat", "red apron"],
            },
            "personality": ["overconfident", "clumsy"],
            "motion_style": ["squash and stretch"],
            "forbidden_changes": ["do not change eye color"],
        }
    ],
}

_BASE_STYLE_BIBLE = {
    "version": "1.0",
    "visual_style": "high-quality colorful 3D cartoon animation",
    "lighting": "bright warm cinematic lighting",
    "camera_language": ["reaction close-ups"],
    "motion": ["continuous visible movement"],
    "color": "bright cheerful saturated palette",
    "render_rules": ["consistent character identity", "no watermark"],
}


def _base_shot(shot_id: str = "shot_001", order: int = 1, duration_sec: float = 5.0) -> dict:
    return {
        "id": shot_id,
        "order": order,
        "duration_sec": duration_sec,
        "location": "Kitchen",
        "characters": ["char_mochi"],
        "start_state": {"character": "Mochi clean", "environment": "clean kitchen"},
        "action": "Mochi slams noodle packet.",
        "expression": "smug confidence",
        "camera": "medium close-up",
        "motion": "fast paw slam",
        "props": ["instant noodle packet"],
        "end_state": {"character": "Mochi shocked", "environment": "clean kitchen"},
        "transition_out": "hard_cut",
    }


def _make_shot_plan(shots: list[dict]) -> dict:
    return {"version": "1.0", "shots": shots}


class TestSchemaList:
    def test_all_expected_schemas_present(self):
        names = list_schemas()
        assert "request" in names
        assert "story" in names
        assert "character_bible" in names
        assert "style_bible" in names
        assert "shot_plan" in names
        assert "continuity_state" in names
        assert "job" in names
        assert "run_manifest" in names
        assert len(names) == 8

    def test_schemas_are_valid_json_schema(self):
        from jsonschema import Draft202012Validator
        load_schema = __import__("schemas.multishot", fromlist=["load_schema"]).load_schema
        for name in list_schemas():
            schema = load_schema(name)
            assert isinstance(schema, dict)
            assert "$schema" in schema


class TestRequestValidation:
    def test_valid_2_shot_request_accepts(self):
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 2, "max_shots": 2}}
        validate_request_cross_fields(req)

    def test_min_shots_below_2_rejected(self):
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 1, "max_shots": 4}}
        with pytest.raises(MultishotValidationError, match="minimum"):
            validate_request_cross_fields(req)

    def test_max_below_min_rejected(self):
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 5, "max_shots": 2}}
        with pytest.raises(MultishotValidationError, match="max_shots"):
            validate_request_cross_fields(req)

    def test_nan_fps_rejected(self):
        import math
        req = {**_BASE_REQUEST, "fps": float("nan")}
        with pytest.raises(MultishotValidationError, match="Non-finite"):
            validate_request_cross_fields(req)

    def test_invalid_min_schema(self):
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 1, "max_shots": 4}}
        with pytest.raises(Exception):
            validate("request", req)

    def test_missing_aspect_ratio_rejected(self):
        req = {**_BASE_REQUEST}
        del req["aspect_ratio"]
        with pytest.raises(Exception):
            validate("request", req)


class TestStoryValidation:
    def test_valid_story_accepts(self):
        validate_story_cross_fields(_BASE_STORY)

    def test_missing_hook_rejected(self):
        story = {**_BASE_STORY}
        story["beats"] = [b for b in story["beats"] if b["type"] != "hook"]
        with pytest.raises(MultishotValidationError, match="hook"):
            validate_story_cross_fields(story)

    def test_missing_climax_rejected(self):
        story = {**_BASE_STORY}
        story["beats"] = [b for b in story["beats"] if b["type"] != "climax"]
        with pytest.raises(MultishotValidationError, match="climax"):
            validate_story_cross_fields(story)

    def test_resolution_punchline_aliases(self):
        story = {
            **_BASE_STORY,
            "beats": [
                {"id": "beat_01", "type": "hook", "summary": "H"},
                {"id": "beat_02", "type": "escalation", "summary": "E"},
                {"id": "beat_03", "type": "climax", "summary": "C"},
                {"id": "beat_04", "type": "resolution", "summary": "R"},
            ],
        }
        validate_story_cross_fields(story)

    def test_punchline_passes_for_resolution(self):
        story = {
            **_BASE_STORY,
            "beats": [
                {"id": "beat_01", "type": "hook", "summary": "H"},
                {"id": "beat_02", "type": "escalation", "summary": "E"},
                {"id": "beat_03", "type": "climax", "summary": "C"},
                {"id": "beat_04", "type": "punchline", "summary": "P"},
            ],
        }
        validate_story_cross_fields(story)

    def test_too_few_beats_rejected(self):
        story = {**_BASE_STORY, "beats": [_BASE_STORY["beats"][0]]}
        with pytest.raises(Exception):
            validate("story", story)


class TestCharacterBibleValidation:
    def test_valid_bible_accepts(self):
        validate_character_bible_cross_fields(_BASE_CHARACTER_BIBLE)

    def test_duplicate_character_id_rejected(self):
        bible = {**_BASE_CHARACTER_BIBLE}
        c = dict(_BASE_CHARACTER_BIBLE["characters"][0])
        c["id"] = "char_mochi"
        bible["characters"] = [_BASE_CHARACTER_BIBLE["characters"][0], c]
        with pytest.raises(MultishotValidationError, match="Duplicate"):
            validate_character_bible_cross_fields(bible)

    def test_missing_locked_identity_type_rejected(self):
        bible = copy.deepcopy(_BASE_CHARACTER_BIBLE)
        c = bible["characters"][0]
        del c["locked_identity"]["type"]
        with pytest.raises(MultishotValidationError, match="locked_identity"):
            validate_character_bible_cross_fields(bible)


class TestStyleBibleValidation:
    def test_valid_style_accepts(self):
        validate_style_bible_cross_fields(_BASE_STYLE_BIBLE)

    def test_empty_render_rules_rejected(self):
        bible = {**_BASE_STYLE_BIBLE, "render_rules": []}
        with pytest.raises(MultishotValidationError, match="render_rules"):
            validate_style_bible_cross_fields(bible)


class TestShotPlanValidation:
    def test_valid_2_shot_plan_accepts(self):
        plan = _make_shot_plan([
            _base_shot("shot_001", order=1),
            _base_shot("shot_002", order=2),
        ])
        validate_shot_plan_cross_fields(plan)

    def test_valid_25_shot_plan_accepts(self):
        shots = [_base_shot(f"shot_{i:03d}", order=i) for i in range(1, 26)]
        plan = _make_shot_plan(shots)
        validate_shot_plan_cross_fields(plan)

    def test_min_2_shots_enforced(self):
        plan = _make_shot_plan([_base_shot()])
        with pytest.raises(MultishotValidationError, match="at least 2 shots"):
            validate_shot_plan_cross_fields(plan)

    def test_duplicate_shot_ids_rejected(self):
        shots = [
            _base_shot("shot_001", order=1),
            _base_shot("shot_001", order=2),
        ]
        plan = _make_shot_plan(shots)
        with pytest.raises(MultishotValidationError, match="Duplicate shot ids"):
            validate_shot_plan_cross_fields(plan)

    def test_duplicate_orders_rejected(self):
        shots = [
            _base_shot("shot_001", order=1),
            _base_shot("shot_002", order=1),
        ]
        plan = _make_shot_plan(shots)
        with pytest.raises(MultishotValidationError, match="Duplicate shot orders"):
            validate_shot_plan_cross_fields(plan)

    def test_non_contiguous_orders_rejected(self):
        shots = [
            _base_shot("shot_001", order=1),
            _base_shot("shot_002", order=3),
        ]
        plan = _make_shot_plan(shots)
        with pytest.raises(MultishotValidationError, match="contiguous"):
            validate_shot_plan_cross_fields(plan)

    def test_missing_end_state_rejected(self):
        shots = [
            _base_shot("shot_001", order=1),
            _base_shot("shot_002", order=2),
        ]
        del shots[0]["end_state"]
        plan = _make_shot_plan(shots)
        with pytest.raises(Exception):
            validate("shot_plan", plan)

    def test_unknown_character_fk_rejected(self):
        shots = [_base_shot("shot_001", order=1), _base_shot("shot_002", order=2)]
        shots[0]["characters"] = ["char_unknown"]
        plan = _make_shot_plan(shots)
        with pytest.raises(MultishotValidationError, match="unknown character"):
            validate_shot_plan_cross_fields(plan, character_bible=_BASE_CHARACTER_BIBLE)

    def test_max_shots_exceeded(self):
        shots = [_base_shot(f"shot_{i:03d}", order=i) for i in range(1, 10)]
        plan = _make_shot_plan(shots)
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 2, "max_shots": 8}}
        with pytest.raises(MultishotValidationError, match="max_shots"):
            validate_shot_plan_cross_fields(plan, request=req)


class TestContinuityStateValidation:
    def test_valid_state_accepts(self):
        state = {
            "version": 1,
            "accepted_through_shot": None,
            "character_state": {},
            "environment_state": {},
            "object_state": {},
        }
        validate_continuity_state_cross_fields(state)

    def test_invalid_version_rejected(self):
        state = {
            "version": 0,
            "accepted_through_shot": None,
            "character_state": {},
            "environment_state": {},
            "object_state": {},
        }
        with pytest.raises(MultishotValidationError, match="version"):
            validate_continuity_state_cross_fields(state)


class TestJobValidation:
    def test_valid_job_accepts(self):
        job = {
            "shot_id": "shot_001",
            "provider": "fake",
            "model": "test",
            "provider_job_id": "abc123",
            "status": "RUNNING",
            "attempt": 1,
            "max_attempts": 3,
            "submitted_at": "2026-10-05T13:00:00Z",
            "updated_at": "2026-10-05T13:00:00Z",
            "input_hash": "sha256:abc",
            "error_code": None,
            "error": None,
        }
        validate_job_cross_fields(job)

    def test_attempt_exceeds_max_rejected(self):
        job = {
            "shot_id": "shot_001",
            "provider": "fake",
            "model": "test",
            "provider_job_id": None,
            "status": "FAILED",
            "attempt": 4,
            "max_attempts": 3,
            "submitted_at": "2026-10-05T13:00:00Z",
            "updated_at": "2026-10-05T13:00:00Z",
            "input_hash": "sha256:abc",
            "error_code": "PROVIDER_5XX",
            "error": "timeout",
        }
        with pytest.raises(MultishotValidationError, match="attempt"):
            validate_job_cross_fields(job)


class TestRunManifestValidation:
    def test_valid_manifest_accepts(self):
        manifest = {
            "project_id": "p_test",
            "schema_version": "1.0",
            "project_status": "CREATED",
            "created_at": "2026-10-05T13:00:00Z",
            "updated_at": "2026-10-05T13:00:00Z",
            "shot_count": 2,
            "shots": {
                "shot_001": {"status": "NORMALIZED"},
                "shot_002": {"status": "NORMALIZED"},
            },
        }
        validate_run_manifest_cross_fields(manifest)

    def test_shot_count_mismatch_rejected(self):
        manifest = {
            "project_id": "p_test",
            "schema_version": "1.0",
            "project_status": "CREATED",
            "created_at": "2026-10-05T13:00:00Z",
            "updated_at": "2026-10-05T13:00:00Z",
            "shot_count": 5,
            "shots": {"shot_001": {"status": "NORMALIZED"}},
        }
        with pytest.raises(MultishotValidationError, match="shot_count"):
            validate_run_manifest_cross_fields(manifest)


class TestValidateAllCross:
    def test_valid_bundle_accepts(self):
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 2, "max_shots": 8}}
        plan = _make_shot_plan([
            _base_shot("shot_001", order=1),
            _base_shot("shot_002", order=2),
        ])
        validate_all_cross(request=req, story=_BASE_STORY, character_bible=_BASE_CHARACTER_BIBLE,
                           style_bible=_BASE_STYLE_BIBLE, shot_plan=plan)

    def test_invalid_bundle_raises(self):
        req = {**_BASE_REQUEST, "shot_policy": {"min_shots": 2, "max_shots": 8}}
        plan = _make_shot_plan([_base_shot("shot_001", order=1)])
        with pytest.raises(MultishotValidationError, match="at least 2 shots"):
            validate_all_cross(request=req, shot_plan=plan)


def test_request_accepts_kids_profile_and_editorial_review():
    request = copy.deepcopy(_BASE_REQUEST)
    request["production_profile"] = {
        "id": "kids-3d-cartoon",
        "version": "v1",
        "age_target": "6-8",
        "render_orientation": "landscape",
    }
    request["kids_editorial_review"] = {
        "originality": True,
        "beginning_middle_end": True,
        "age_appropriate": True,
        "unsafe_imitation_risk": False,
        "audio_intelligibility": True,
        "rights_licenses": True,
        "made_for_kids_decision": "creator_must_decide",
        "reviewer": "creator",
        "notes": "Original stylized characters only.",
    }

    validate("request", request)


def test_request_rejects_extra_kids_editorial_field():
    request = copy.deepcopy(_BASE_REQUEST)
    request["kids_editorial_review"] = {
        "originality": True,
        "beginning_middle_end": True,
        "age_appropriate": True,
        "unsafe_imitation_risk": False,
        "audio_intelligibility": True,
        "rights_licenses": True,
        "made_for_kids_decision": "creator_must_decide",
        "agent_guessed_coppa_status": False,
    }

    with pytest.raises(Exception):
        validate("request", request)
