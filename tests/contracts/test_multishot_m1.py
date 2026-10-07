"""M1 multi-shot tests — prompt builder, continuity engine, reference manager.

TASK 003–008 acceptance:
  - prompt snapshots for first / middle / last shot
  - missing character lock and missing reference rejection
  - repeat-acceptance idempotence
  - failed-shot non-mutation
  - stale-chain propagation
  - six-shot Mochi fixture validates
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.multishot_schemas import (
    MultishotValidationError,
    validate_all_cross,
)
from lib.multishot_prompt_builder import build_multishot_prompt, build_multishot_prompts
from lib.multishot_continuity import (
    initial_continuity,
    accept_shot,
    continuity_in_for_shot,
    retry_continuity_in,
    mark_downstream_stale,
    failed_shot_continuity_unchanged,
    snapshot,
)
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_shot_keyframe,
    validate_generation_ready,
    invalidate_dependent_jobs,
    reference_changed,
    content_hash,
)
from tests.fixtures.multishot_mochi import (
    all_project_data,
    continuity_snapshot_for,
)


class TestMochiFixture:
    def test_six_shot_plan_validates(self):
        data = all_project_data()
        validate_all_cross(
            request=data["request"],
            story=data["story"],
            character_bible=data["character_bible"],
            style_bible=data["style_bible"],
            shot_plan=data["shot_plan"],
        )
        assert len(data["shot_plan"]["shots"]) == 6

    def test_contiguity_and_orders(self):
        plan = all_project_data()["shot_plan"]
        orders = [s["order"] for s in plan["shots"]]
        assert orders == [1, 2, 3, 4, 5, 6]


class TestPromptBuilder:
    def test_first_middle_last_snapshots(self):
        data = all_project_data()
        shots = {s["id"]: s for s in data["shot_plan"]["shots"]}
        for shot_id, cont in [
            ("shot_001", continuity_snapshot_for(1)),
            ("shot_003", continuity_snapshot_for(3)),
            ("shot_006", continuity_snapshot_for(6)),
        ]:
            prompt = build_multishot_prompt(
                project_title=data["project_title"],
                request=data["request"],
                story=data["story"],
                character_bible=data["character_bible"],
                style_bible=data["style_bible"],
                shot=shots[shot_id],
                continuity_in=cont,
            )
            for section in (
                "PROJECT:", "CHARACTER LOCK:", "ENVIRONMENT LOCK:",
                "CURRENT CONTINUITY STATE:", "ENDING FRAME / REQUIRED END STATE:",
                "NEGATIVE CONSTRAINTS:",
            ):
                assert section in prompt, f"{section} missing in {shot_id}"
            assert "char_mochi" in prompt
            assert "chubby orange cartoon cat" in prompt
            assert "{{" not in prompt

    def test_shot_one_uses_initial_state(self):
        data = all_project_data()
        shots = {s["id"]: s for s in data["shot_plan"]["shots"]}
        prompt = build_multishot_prompt(
            project_title=data["project_title"],
            request=data["request"], story=data["story"],
            character_bible=data["character_bible"],
            style_bible=data["style_bible"],
            shot=shots["shot_001"],
            continuity_in=continuity_snapshot_for(1),
        )
        assert "INITIAL STATE" in prompt
        assert "kitchen" in prompt

    def test_missing_character_lock_rejected(self):
        data = all_project_data()
        shots = {s["id"]: s for s in data["shot_plan"]["shots"]}
        shot = dict(shots["shot_001"])
        shot["characters"] = []
        with pytest.raises(MultishotValidationError, match="character lock"):
            build_multishot_prompt(
                project_title=data["project_title"],
                request=data["request"], story=data["story"],
                character_bible=data["character_bible"],
                style_bible=data["style_bible"],
                shot=shot,
                continuity_in=continuity_snapshot_for(1),
            )

    def test_unknown_character_fk_rejected(self):
        data = all_project_data()
        shots = {s["id"]: s for s in data["shot_plan"]["shots"]}
        shot = dict(shots["shot_001"])
        shot["characters"] = ["char_unknown"]
        with pytest.raises(MultishotValidationError, match="unknown character"):
            build_multishot_prompt(
                project_title=data["project_title"],
                request=data["request"], story=data["story"],
                character_bible=data["character_bible"],
                style_bible=data["style_bible"],
                shot=shot,
                continuity_in=continuity_snapshot_for(1),
            )

    def test_missing_continuity_rejected(self):
        data = all_project_data()
        shots = {s["id"]: s for s in data["shot_plan"]["shots"]}
        with pytest.raises(MultishotValidationError, match="continuity"):
            build_multishot_prompt(
                project_title=data["project_title"],
                request=data["request"], story=data["story"],
                character_bible=data["character_bible"],
                style_bible=data["style_bible"],
                shot=shots["shot_001"],
                continuity_in={},
            )

    def test_batch_build_in_plan_order(self):
        data = all_project_data()
        continuity_by_shot = {f"shot_{o:03d}": continuity_snapshot_for(o) for o in range(1, 7)}
        results = build_multishot_prompts(
            project_title=data["project_title"],
            request=data["request"], story=data["story"],
            character_bible=data["character_bible"],
            style_bible=data["style_bible"],
            shot_plan=data["shot_plan"],
            continuity_by_shot=continuity_by_shot,
        )
        assert [r["shot_id"] for r in results] == [f"shot_{o:03d}" for o in range(1, 7)]

    def test_batch_missing_continuity_rejected(self):
        data = all_project_data()
        with pytest.raises(MultishotValidationError, match="continuity input"):
            build_multishot_prompts(
                project_title=data["project_title"],
                request=data["request"], story=data["story"],
                character_bible=data["character_bible"],
                style_bible=data["style_bible"],
                shot_plan=data["shot_plan"],
                continuity_by_shot={},
            )


class TestContinuity:
    def test_accept_advances_version_once(self):
        state = initial_continuity()
        after = accept_shot(state, "shot_001",
                            {"character_state": {"char_mochi": "clean"}},
                            expected_order=1, shot_order=1)
        assert after["version"] == state["version"] + 1
        assert after["accepted_through_shot"] == "shot_001"

    def test_repeat_acceptance_idempotent(self):
        state = initial_continuity()
        state = accept_shot(state, "shot_001", {}, expected_order=1, shot_order=1)
        v1 = state["version"]
        again = accept_shot(state, "shot_001", {}, expected_order=1, shot_order=1)
        assert again["version"] == v1
        assert again == state

    def test_failed_shot_does_not_mutate_continuity(self):
        before = initial_continuity()
        after = snapshot(before)
        assert failed_shot_continuity_unchanged(before, after, "shot_003") is True

    def test_retry_uses_identical_continuity_in(self):
        state = initial_continuity()
        state = accept_shot(state, "shot_001", {}, expected_order=1, shot_order=1)
        retry_in = retry_continuity_in(state)
        assert retry_in == state
        retry_in["character_state"]["x"] = "y"
        assert "x" not in state["character_state"]

    def test_out_of_order_acceptance_rejected(self):
        state = initial_continuity()
        with pytest.raises(MultishotValidationError, match="order"):
            accept_shot(state, "shot_003", {}, expected_order=1, shot_order=3)

    def test_stale_chain_after_regeneration(self):
        orders = {f"shot_{o:03d}": o for o in range(1, 7)}
        stale = mark_downstream_stale(orders, "shot_002")
        assert stale == ["shot_003", "shot_004", "shot_005", "shot_006"]

    def test_stale_chain_empty_for_last_shot(self):
        orders = {f"shot_{o:03d}": o for o in range(1, 7)}
        assert mark_downstream_stale(orders, "shot_006") == []

    def test_continuity_in_for_shot_1_is_initial(self):
        cont = continuity_in_for_shot(initial_continuity(), shot_order=1)
        assert cont["accepted_through_shot"] is None


class TestReferences:
    def _store_with_refs(self, tmp_path):
        store = new_reference_store()
        char_master = tmp_path / "character_master.png"
        Image.new("RGB", (2, 2), "red").save(char_master)
        register_character_master(store, "char_mochi", char_master)
        kf = tmp_path / "shot_001.png"
        Image.new("RGB", (2, 2), "blue").save(kf)
        register_shot_keyframe(store, "shot_001", kf, derived_from_character="char_mochi")
        return store, char_master, kf

    def test_generation_blocked_when_keyframe_missing(self, tmp_path):
        store = new_reference_store()
        data = all_project_data()
        shot = data["shot_plan"]["shots"][0]
        with pytest.raises(MultishotValidationError, match="absent"):
            validate_generation_ready(store, shot, data["character_bible"])

    def test_generation_proceeds_when_ref_present(self, tmp_path):
        store, _, _ = self._store_with_refs(tmp_path)
        data = all_project_data()
        shot = data["shot_plan"]["shots"][0]
        present = validate_generation_ready(store, shot, data["character_bible"])
        assert "keyframe:shot_001" in present

    def test_changed_reference_invalidates_dependent_jobs(self, tmp_path):
        store, _, kf = self._store_with_refs(tmp_path)
        before_ref = store["references"]["keyframe:shot_001"]["content_hash"]
        Image.new("RGB", (2, 2), "green").save(kf)
        register_shot_keyframe(store, "shot_001", kf, derived_from_character="char_mochi")
        after_ref = store["references"]["keyframe:shot_001"]["content_hash"]
        assert before_ref != after_ref
        assert reference_changed({"references": {"keyframe:shot_001": {"content_hash": before_ref}}},
                                 store, "keyframe:shot_001") is True

    def test_character_master_change_invalidates_derived_shots(self, tmp_path):
        store, char_master, _ = self._store_with_refs(tmp_path)
        Image.new("RGB", (2, 2), "green").save(char_master)
        register_character_master(store, "char_mochi", char_master)
        stale = invalidate_dependent_jobs(store, "character_master:char_mochi")
        assert "shot_001" in stale

    def test_content_hash_is_sha256(self, tmp_path):
        f = tmp_path / "a.png"
        Image.new("RGB", (2, 2), "red").save(f)
        h = content_hash(f)
        assert h.startswith("sha256:")
        assert len(h) == 7 + 64  # "sha256:" is 7 chars + 64 hex
