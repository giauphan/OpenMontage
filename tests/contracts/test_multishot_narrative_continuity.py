import json
import pytest

from lib.multishot_continuity import (
    accept_shot,
    initial_continuity,
    continuity_in_for_shot
)
from lib.multishot_prompt_builder import build_multishot_prompt
from lib.multishot_schemas import MultishotValidationError


@pytest.fixture
def base_continuity():
    return initial_continuity()

@pytest.fixture
def narrative_end_state():
    return {
        "character": "Covered in mud",
        "environment": "Floor is covered with puddles",
        "props": {
            "pot": "Broken on the floor",
            "lid": "Rolling away"
        }
    }


def test_persist_exact_full_original_accepted_end_state(base_continuity, narrative_end_state):
    # Accept a shot with a narrative payload
    updated = accept_shot(
        base_continuity,
        "shot_001",
        narrative_end_state,
        expected_order=1,
        shot_order=1
    )

    assert "accepted_end_state" in updated
    assert updated["accepted_end_state"] == narrative_end_state

    # Verify that caller mutation cannot change accepted metadata
    narrative_end_state["character"] = "Clean"
    assert updated["accepted_end_state"]["character"] == "Covered in mud"


def test_failed_acceptance_leaves_exact_prior_narrative(base_continuity, narrative_end_state):
    updated = accept_shot(
        base_continuity,
        "shot_001",
        narrative_end_state,
        expected_order=1,
        shot_order=1
    )

    try:
        accept_shot(
            updated,
            "shot_002",
            {"character": "Different"},
            expected_order=2,
            shot_order=3  # Fails due to wrong order
        )
    except MultishotValidationError:
        pass

    assert updated["accepted_end_state"] == {
        "character": "Covered in mud",
        "environment": "Floor is covered with puddles",
        "props": {
            "pot": "Broken on the floor",
            "lid": "Rolling away"
        }
    }


def test_changed_repeat_narrative_rejected(base_continuity, narrative_end_state):
    updated = accept_shot(
        base_continuity,
        "shot_001",
        narrative_end_state,
        expected_order=1,
        shot_order=1
    )

    # Re-accepting the same shot with a different end state should fail
    try:
        accept_shot(
            updated,
            "shot_001",
            {"character": "Clean"},
            expected_order=1,
            shot_order=1
        )
        assert False, "Should have raised MultishotValidationError"
    except MultishotValidationError:
        pass


def test_prompt_builder_includes_accepted_narrative(base_continuity, narrative_end_state):
    updated = accept_shot(
        base_continuity,
        "shot_001",
        narrative_end_state,
        expected_order=1,
        shot_order=1
    )

    continuity_in = continuity_in_for_shot(updated, 2, "shot_001")

    prompt = build_multishot_prompt(
        project_title="Test Project",
        request={"topic": "Test Topic"},
        story={"summary": "Test Summary"},
        character_bible={
            "characters": [
                {
                    "id": "char_001",
                    "name": "Test Character",
                    "locked_identity": {"type": "human"}
                }
            ]
        },
        style_bible={"visual_style": "Test Style"},
        shot={
            "id": "shot_002",
            "order": 2,
            "duration_sec": 5,
            "characters": ["char_001"],
            "start_state": {"character": "Muddy"},
            "end_state": {"character": "Clean"}
        },
        continuity_in=continuity_in
    )

    assert "Covered in mud" in prompt
    assert "Floor is covered with puddles" in prompt
    assert "Broken on the floor" in prompt
    assert "Rolling away" in prompt
