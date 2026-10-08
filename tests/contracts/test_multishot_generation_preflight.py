"""Contract tests for prepare_generation preflight (no network, no provider instance)."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict
from pathlib import Path

import pytest
from PIL import Image

from lib.multishot_generation import prepare_generation, SUPPORTED_PROVIDERS
from lib.multishot_session import MultishotSession
from lib.multishot_workspace import init_multishot_project
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_shot_keyframe,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _png(path: Path, name: str = "img.png") -> Path:
    p = path / name
    img = Image.new("RGB", (16, 16), color=(128, 64, 32))
    img.save(str(p))
    return p


def _setup_session(project_dir: Path) -> tuple[MultishotSession, dict, dict]:
    """Initialize a two-shot session with a real keyframe; return session + store + review."""
    from tests.fixtures.multishot_mochi import all_project_data
    data = all_project_data()
    shots = data["shot_plan"]["shots"][:2]
    planning = {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": {"shots": shots, "target_duration_sec": 10, "version": "1.0"},
    }
    init_multishot_project(project_dir.name, title="test-project", pipeline_dir=project_dir.parent)

    session = MultishotSession(project_dir)
    session.initialize(planning)

    img_dir = project_dir / "refs"
    img_dir.mkdir(exist_ok=True)
    master_path = _png(img_dir, "master.png")
    kf_path = _png(img_dir, "kf001.png")

    store = new_reference_store()
    register_character_master(store, "char_mochi", master_path)
    register_shot_keyframe(
        store,
        shots[0]["id"],
        kf_path,
        derived_from_character="char_mochi",
    )

    review = {"approved": True, "reviewer": "test-agent", "notes": "looks good"}
    return session, store, review


def _first_shot_id(project_dir: Path) -> str:
    state = MultishotSession(project_dir).get_state()
    return sorted(state["shots"].values(), key=lambda s: s["order"])[0]["id"]


# ---------------------------------------------------------------------------
# spend / budget / estimate guards
# ---------------------------------------------------------------------------

def test_spend_not_approved_is_rejected(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    for bad in (False, None, 1, "yes"):
        with pytest.raises(ValueError, match="spend_approved"):
            prepare_generation(
                tmp_path, shot_id,
                provider="kling_official", model="kling-v1",
                settings={}, spend_approved=bad,
                budget_usd=10.0, estimated_usd=5.0,
                reference_store=store, reference_review=review,
            )


def test_bool_budget_rejected(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    with pytest.raises(ValueError, match="budget_usd"):
        prepare_generation(
            tmp_path, shot_id,
            provider="kling_official", model="kling-v1",
            settings={}, spend_approved=True,
            budget_usd=True, estimated_usd=5.0,
            reference_store=store, reference_review=review,
        )


def test_nonfinite_budget_rejected(tmp_path):
    import math
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    with pytest.raises(ValueError, match="budget_usd"):
        prepare_generation(
            tmp_path, shot_id,
            provider="kling_official", model="kling-v1",
            settings={}, spend_approved=True,
            budget_usd=math.inf, estimated_usd=5.0,
            reference_store=store, reference_review=review,
        )


def test_estimate_exceeds_budget_rejected(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    with pytest.raises(ValueError, match="estimated_usd"):
        prepare_generation(
            tmp_path, shot_id,
            provider="kling_official", model="kling-v1",
            settings={}, spend_approved=True,
            budget_usd=5.0, estimated_usd=10.0,
            reference_store=store, reference_review=review,
        )


# ---------------------------------------------------------------------------
# provider / model guards
# ---------------------------------------------------------------------------

def test_unsupported_provider_rejected(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    with pytest.raises(ValueError, match="provider"):
        prepare_generation(
            tmp_path, shot_id,
            provider="fake_provider", model="m",
            settings={}, spend_approved=True,
            budget_usd=10.0, estimated_usd=1.0,
            reference_store=store, reference_review=review,
        )


def test_empty_model_rejected(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    with pytest.raises(ValueError, match="model"):
        prepare_generation(
            tmp_path, shot_id,
            provider="kling_official", model="",
            settings={}, spend_approved=True,
            budget_usd=10.0, estimated_usd=1.0,
            reference_store=store, reference_review=review,
        )


# ---------------------------------------------------------------------------
# successful spec: hash correctness and binding
# ---------------------------------------------------------------------------

def test_successful_spec_has_kling_prompt_hash(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    spec = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    expected = "sha256:" + hashlib.sha256(spec.prompt.encode("utf-8")).hexdigest()
    assert spec.prompt_hash == expected


def test_successful_spec_fingerprint_stable(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    spec = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    assert spec.fingerprint() == spec.fingerprint()


def test_spec_bound_in_session(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    spec = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    state = session.get_state()
    shot = state["shots"][shot_id]
    assert shot["job_spec"] is not None
    assert shot["job_input_hash"] == spec.fingerprint()


# ---------------------------------------------------------------------------
# idempotent reload
# ---------------------------------------------------------------------------

def test_idempotent_reload_returns_same_fingerprint(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)
    spec1 = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    spec2 = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    assert spec1.fingerprint() == spec2.fingerprint()


# ---------------------------------------------------------------------------
# master mutation blocked
# ---------------------------------------------------------------------------

def test_master_mutation_blocked(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)

    master_path = Path(store["references"]["character_master:char_mochi"]["path"])
    Image.new("RGB", (16, 16), color=(0, 0, 255)).save(str(master_path))

    with pytest.raises(Exception):
        prepare_generation(
            tmp_path, shot_id,
            provider="kling_official", model="kling-v1",
            settings={}, spend_approved=True,
            budget_usd=10.0, estimated_usd=1.0,
            reference_store=store, reference_review=review,
        )


# ---------------------------------------------------------------------------
# regeneration clears and allows new spec
# ---------------------------------------------------------------------------

def test_regenerate_clears_job_spec(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)

    prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    assert session.get_state()["shots"][shot_id]["job_spec"] is not None

    session.regenerate_shot(shot_id)
    shot = session.get_state()["shots"][shot_id]
    assert shot["bound_input"] is None
    assert shot["job_spec"] is None
    assert shot["job_input_hash"] is None


def test_regenerate_allows_new_spec(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)

    spec1 = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    session.regenerate_shot(shot_id)

    spec2 = prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )
    assert spec1.revision != spec2.revision
    assert spec1.fingerprint() != spec2.fingerprint()


# ---------------------------------------------------------------------------
# changed settings on same revision rejected
# ---------------------------------------------------------------------------

def test_changed_settings_same_revision_rejected(tmp_path):
    session, store, review = _setup_session(tmp_path)
    shot_id = _first_shot_id(tmp_path)

    prepare_generation(
        tmp_path, shot_id,
        provider="kling_official", model="kling-v1",
        settings={"mode": "std"}, spend_approved=True,
        budget_usd=10.0, estimated_usd=1.0,
        reference_store=store, reference_review=review,
    )

    # Different settings → prepare_shot_prompt sees different bound_input hash → raises.
    with pytest.raises(ValueError):
        prepare_generation(
            tmp_path, shot_id,
            provider="kling_official", model="kling-v1",
            settings={"mode": "pro"}, spend_approved=True,
            budget_usd=10.0, estimated_usd=1.0,
            reference_store=store, reference_review=review,
        )
