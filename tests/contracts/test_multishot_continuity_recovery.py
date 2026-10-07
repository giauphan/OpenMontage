"""Offline regressions for pure R3 helpers; no persistence or review policy."""
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


def test_accept_does_not_alias_end_state():
    end = {"character_state": {"cat": {"clothes": ["apron"]}}}
    before = initial_continuity()
    after = accept_shot(before, "a", end, expected_order=1, shot_order=1)
    end["character_state"]["cat"]["clothes"].append("hat")
    assert after["character_state"]["cat"]["clothes"] == ["apron"]
    assert before == initial_continuity()


@pytest.mark.parametrize("end,expected,order", [
    ({"object_state": {"pot": "dirty"}}, 1, 1), ({}, 2, 1), ({}, 1, 2),
])
def test_repeat_rejects_mismatched_state_or_order(end, expected, order):
    state = accept_shot(initial_continuity(), "a", {}, expected_order=1, shot_order=1)
    with pytest.raises(MultishotValidationError):
        accept_shot(state, "a", end, expected_order=expected, shot_order=order)


def test_failed_shot_marker_is_not_ignored():
    before = initial_continuity()
    after = copy.deepcopy(before)
    after["accepted_through_shot"] = "a"
    assert failed_shot_continuity_unchanged(before, after, "a") is False


def test_failed_shot_state_unchanged():
    before = initial_continuity()
    after = copy.deepcopy(before)
    assert failed_shot_continuity_unchanged(before, after, "a") is True


def test_later_input_requires_accepted_predecessor():
    with pytest.raises(MultishotValidationError):
        continuity_in_for_shot(initial_continuity(), 2, expected_previous_shot_id="shot_001")


def test_stale_list_is_in_plan_order():
    assert mark_downstream_stale({"a": 1, "z": 2, "b": 3}, "a") == ["z", "b"]


def reference_fixture(tmp_path):
    master, keyframe = tmp_path / "master.png", tmp_path / "keyframe.png"
    Image.new("RGB", (2, 2), "red").save(master)
    Image.new("RGB", (2, 2), "blue").save(keyframe)
    store = new_reference_store()
    register_character_master(store, "cat", master)
    register_shot_keyframe(store, "a", keyframe, derived_from_character="cat")
    return store, master, keyframe


@pytest.mark.parametrize("change", ["missing", "corrupt", "replaced", "master_replaced", "master_registered"])
def test_generation_rejects_invalid_files_and_stale_provenance(tmp_path, change):
    store, master, keyframe = reference_fixture(tmp_path)
    if change == "missing":
        keyframe.unlink()
    elif change == "corrupt":
        keyframe.write_bytes(b"not an image")
    elif change == "replaced":
        Image.new("RGB", (2, 2), "green").save(keyframe)
    else:
        Image.new("RGB", (2, 2), "green").save(master)
        if change == "master_registered":
            register_character_master(store, "cat", master)
    with pytest.raises(MultishotValidationError):
        validate_generation_ready(
            store,
            {"id": "a", "characters": ["cat"]},
            {"characters": [{"id": "cat"}]},
        )


def test_registration_rejects_fake_image(tmp_path):
    path = tmp_path / "fake.png"
    path.write_bytes(b"fake image")
    with pytest.raises(MultishotValidationError):
        register_character_master(new_reference_store(), "cat", path)
