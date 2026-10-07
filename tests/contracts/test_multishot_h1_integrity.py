import copy

import pytest
from PIL import Image

from lib.multishot_continuity import (
    accept_shot, continuity_in_for_shot, failed_shot_continuity_unchanged,
    initial_continuity, mark_downstream_stale,
)
from lib.multishot_references import (
    new_reference_store, register_character_master, register_shot_keyframe,
    validate_generation_ready,
)
from lib.multishot_schemas import MultishotValidationError

def test_accept_repeat_changes_order():
    """Testing that repeating acceptance with same payload but different order fails."""
    # A shot that is successfully accepted once
    state = accept_shot(initial_continuity(), "a", {}, expected_order=1, shot_order=1)

    # You attempt to accept it again (e.g. from an out-of-order arrival, or repeat payload,
    # but the sequence plan expects it at a new position/order).
    with pytest.raises(MultishotValidationError, match="changed order"):
        accept_shot(state, "a", {}, expected_order=2, shot_order=2)

def test_accept_changed_repeat_order():
    """Testing that repeating acceptance where expected_order and shot_order changed to a same new equal value fails"""
    state_0 = initial_continuity()
    state_1 = accept_shot(state_0, "shot_123", {}, expected_order=1, shot_order=1)

    # A repeat message arrives where both shot_order and expected_order are matching each other
    # but they differ from the original order
    with pytest.raises(MultishotValidationError, match="changed order"):
        accept_shot(state_1, "shot_123", {}, expected_order=2, shot_order=2)

def test_legacy_schema_validation():
    """Tests that a state without explicit `accepted_order` still works correctly in validation/flow."""
    from jsonschema import validate
    from schemas.multishot import load_schema

    state = initial_continuity()
    # Mocking legacy unmigrated state without accepted_order
    del state["accepted_order"]

    schema = load_schema("continuity_state")
    validate(state, schema)

    state_after = accept_shot(state, "shot_z", {}, expected_order=1, shot_order=1)

    # Should seamlessly enforce order on repeat from now
    with pytest.raises(MultishotValidationError, match="changed order"):
         accept_shot(state_after, "shot_z", {}, expected_order=2, shot_order=2)

def test_missing_provenance(tmp_path):
    master, keyframe = tmp_path / "master.png", tmp_path / "keyframe.png"
    Image.new("RGB", (2, 2), "red").save(master)
    Image.new("RGB", (2, 2), "blue").save(keyframe)
    store = new_reference_store()
    register_character_master(store, "cat", master)

    # test_missing_provenance registers keyframe b then requests a;
    register_shot_keyframe(store, "b", keyframe, derived_from_character="cat")
    with pytest.raises(MultishotValidationError, match="is absent"):
        validate_generation_ready(
            store,
            {"id": "a", "characters": ["cat"]},
            {"characters": [{"id": "cat"}]},
        )

    # to test wrong owner, register a then change its owner to b.
    register_shot_keyframe(store, "a", keyframe, derived_from_character="cat")
    store["references"]["keyframe:a"]["owner"] = "b"
    with pytest.raises(MultishotValidationError, match="keyframe owner"):
        validate_generation_ready(
            store,
            {"id": "a", "characters": ["cat"]},
            {"characters": [{"id": "cat"}]},
        )


def test_missing_provenance_but_keyframe_exists(tmp_path):
    master, keyframe = tmp_path / "master.png", tmp_path / "keyframe.png"
    Image.new("RGB", (2, 2), "red").save(master)
    Image.new("RGB", (2, 2), "blue").save(keyframe)
    store = new_reference_store()
    register_character_master(store, "cat", master)

    register_shot_keyframe(store, "a", keyframe, derived_from_character=None) # missing provenance
    with pytest.raises(MultishotValidationError, match="missing character cat"):
        validate_generation_ready(
            store,
            {"id": "a", "characters": ["cat"]},
            {"characters": [{"id": "cat"}]},
        )

def test_wrong_identity(tmp_path):
    master, keyframe = tmp_path / "master.png", tmp_path / "keyframe.png"
    Image.new("RGB", (2, 2), "red").save(master)
    Image.new("RGB", (2, 2), "blue").save(keyframe)
    store = new_reference_store()
    # master for dog, try to register keyframe derived from it to cat
    register_character_master(store, "dog", master)

    register_shot_keyframe(store, "a", keyframe, derived_from_character="dog")

    with pytest.raises(MultishotValidationError, match="missing character cat"):
         validate_generation_ready(
            store,
            {"id": "a", "characters": ["cat"]},
            {"characters": [{"id": "cat"}, {"id": "dog"}]}, # we have dog in bible but shot is only cat
        )

def test_two_character_incomplete_provenance(tmp_path):
    master_1, master_2, keyframe = tmp_path / "m1.png", tmp_path / "m2.png", tmp_path / "kf.png"
    Image.new("RGB", (2, 2), "red").save(master_1)
    Image.new("RGB", (2, 2), "green").save(master_2)
    Image.new("RGB", (2, 2), "blue").save(keyframe)

    store = new_reference_store()
    register_character_master(store, "cat", master_1)
    register_character_master(store, "dog", master_2)
    # only provide one provenance
    register_shot_keyframe(store, "a", keyframe, derived_from_character="cat")

    with pytest.raises(MultishotValidationError, match="missing character dog"):
         validate_generation_ready(
            store,
            {"id": "a", "characters": ["cat", "dog"]},
            {"characters": [{"id": "cat"}, {"id": "dog"}]},
        )

def test_two_character_complete_provenance(tmp_path):
    master_1, master_2, keyframe = tmp_path / "m1.png", tmp_path / "m2.png", tmp_path / "kf.png"
    Image.new("RGB", (2, 2), "red").save(master_1)
    Image.new("RGB", (2, 2), "green").save(master_2)
    Image.new("RGB", (2, 2), "blue").save(keyframe)

    store = new_reference_store()
    register_character_master(store, "cat", master_1)
    register_character_master(store, "dog", master_2)

    register_shot_keyframe(store, "a", keyframe, derived_from_characters=["cat", "dog"])

    # should not raise
    validate_generation_ready(
        store,
        {"id": "a", "characters": ["cat", "dog"]},
        {"characters": [{"id": "cat"}, {"id": "dog"}]},
    )

def test_corrupt_images(tmp_path):
    master_1, keyframe = tmp_path / "m1.png", tmp_path / "kf.png"
    master_1.write_bytes(b"not image")
    Image.new("RGB", (2,2), "blue").save(keyframe)

    store = new_reference_store()
    with pytest.raises(MultishotValidationError, match="not a readable image"):
        register_character_master(store, "cat", master_1)

def test_omitted_ordering_context():
    """Omitting expected_previous_shot_id when order > 1."""
    state = initial_continuity()
    with pytest.raises(MultishotValidationError, match="requires explicit expected_previous_shot_id"):
        continuity_in_for_shot(state, 2, expected_previous_shot_id=None)

def test_arbitrary_nonnumeric_ids():
    """Test standard IDs rather than arbitrary ones."""
    state = initial_continuity()
    state_after = accept_shot(state, "shot-alpha", {}, expected_order=1, shot_order=1)
    # The order doesn't dictate that id has to be something specific
    assert state_after["accepted_through_shot"] == "shot-alpha"

def test_immediate_predecessor_negative():
    state_0 = initial_continuity()
    state_1 = accept_shot(state_0, "shot_1", {}, expected_order=1, shot_order=1)
    # Passed predecessor ID matches, but expected_order doesn't match shot_order-1
    with pytest.raises(MultishotValidationError, match="expected next order"):
        accept_shot(state_1, "shot_2", {}, expected_order=2, shot_order=3)

def test_changed_repeat_payload_yielding_same_merged_state():
    """Even if merging yields the same semantic value, if the exact payload changed, reject."""
    state_0 = initial_continuity()
    # first accept a nonempty end_state
    state_1 = accept_shot(state_0, "shot_1", {"character_state": {"foo": {"emotion": "happy"}}}, expected_order=1, shot_order=1)

    # repeat with an empty payload that merges to the same state
    with pytest.raises(MultishotValidationError, match="changed end state"):
        accept_shot(state_1, "shot_1", {}, expected_order=1, shot_order=1)

    return
