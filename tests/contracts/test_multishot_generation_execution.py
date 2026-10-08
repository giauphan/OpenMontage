"""Contract tests for approval-gated one-shot generation execution."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lib.multishot_generation import execute_generation, prepare_generation
from lib.multishot_session import MultishotSession
from lib.multishot_workspace import init_multishot_project
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_shot_keyframe,
)


class OfflineProvider:
    provider = "kling_official"

    def __init__(self, *, unknown=False, error_code=None):
        self.unknown = unknown
        self.error_code = error_code
        self.submissions = 0

    def validate_spec(self, spec):
        assert spec.provider == self.provider

    def submit(self, spec, attempt, idempotency_key):
        self.submissions += 1
        if self.unknown:
            raise RuntimeError("transport interrupted")
        if self.error_code:
            from lib.multishot_jobs import JobOutcome
            return JobOutcome(status="failed", error_code=self.error_code, message="error").to_dict()
        return f"offline-{self.submissions}"

    def reconcile(self, spec, idempotency_key):
        return None

    def poll(self, handle):
        return "completed"

    def download(self, handle, dest_dir):
        target = Path(dest_dir) / "output.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=24",
                "-t", "5", "-an", "-pix_fmt", "yuv420p", str(target),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return str(target)


def _setup(tmp_path):
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
    init_multishot_project(tmp_path.name, title="test-project", pipeline_dir=tmp_path.parent)
    session = MultishotSession(tmp_path)
    session.initialize(planning)

    from PIL import Image

    refs = tmp_path / "refs"
    refs.mkdir()
    master = refs / "master.png"
    keyframe = refs / "keyframe.png"
    Image.new("RGB", (16, 16), color=(128, 64, 32)).save(master)
    Image.new("RGB", (16, 16), color=(64, 128, 32)).save(keyframe)
    store = new_reference_store()
    register_character_master(store, "char_mochi", master)
    register_shot_keyframe(store, shots[0]["id"], keyframe, derived_from_character="char_mochi")
    return session, shots[0]["id"], store, {"approved": True, "reviewer": "test", "notes": "ok"}


def _kwargs(tmp_path, shot_id, store, review, **overrides):
    values = {
        "project_dir": tmp_path,
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {},
        "spend_approved": True,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
        "deadline_seconds": 30.0,
        "max_polls": 2,
        "poll_interval": 0.0,
    }
    return {**values, **overrides}


def test_success_records_generated_result(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()

    result = execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: provider))

    assert result["status"] == "completed"
    assert result["shot"]["status"] == "GENERATED"
    assert provider.submissions == 1
    assert result["cost_entry_status"] == "completed"


def test_fresh_instance_resume_reuses_completed_job_and_cost(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    first = OfflineProvider()
    execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: first))

    second = OfflineProvider()
    result = execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: second))

    assert result["status"] == "completed"
    assert first.submissions == 1
    assert second.submissions == 0
    ledger = json.loads((tmp_path / "reports" / "cost_log.json").read_text())
    assert len(ledger["entries"]) == 1


def test_missing_approval_makes_zero_provider_calls(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()

    with pytest.raises(ValueError, match="spend_approved"):
        execute_generation(**_kwargs(tmp_path, shot_id, store, review, spend_approved=False,
                                     provider_factory=lambda: provider))

    assert provider.submissions == 0


def test_changed_settings_block_existing_revision(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: provider))

    with pytest.raises(ValueError):
        execute_generation(**_kwargs(tmp_path, shot_id, store, review, settings={"mode": "pro"},
                                     provider_factory=lambda: provider))

    assert provider.submissions == 1


def test_unknown_submission_preserves_reservation_without_resubmit(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    first = OfflineProvider(unknown=True)
    first_result = execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: first))
    assert first_result["status"] == "submission_unknown"
    assert first_result["cost_entry_status"] == "reserved"

    second = OfflineProvider()
    second_result = execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: second))
    assert second_result["status"] == "submission_unknown"
    assert first.submissions == 1
    assert second.submissions == 0
    assert second_result["cost_entry_status"] == "reserved"


def test_corrupted_master_reference_blocks_eligibility(tmp_path):
    session, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    kw = _kwargs(tmp_path, shot_id, store, review)
    prepare_generation(
        project_dir=kw["project_dir"],
        shot_id=kw["shot_id"],
        provider=kw["provider"],
        model=kw["model"],
        settings=kw["settings"],
        spend_approved=kw["spend_approved"],
        budget_usd=kw["budget_usd"],
        estimated_usd=kw["estimated_usd"],
        reference_store=kw["reference_store"],
        reference_review=kw["reference_review"],
    )

    master_path = Path(store["references"]["character_master:char_mochi"]["path"])
    master_path.write_bytes(b"corrupted image content")

    with pytest.raises(Exception):
        execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: provider))


def test_budget_total_mismatch_rejected(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: provider))

    with pytest.raises(ValueError, match="Ledger budget_total_usd"):
        execute_generation(**_kwargs(tmp_path, shot_id, store, review, budget_usd=20.0,
                                     provider_factory=lambda: provider))


def test_accepted_shot_cannot_re_execute(tmp_path):
    session, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: provider))

    state = session.get_state()
    state["shots"][shot_id]["status"] = "ACCEPTED"
    session._write(state["revision"], state)

    with pytest.raises(ValueError, match="already ACCEPTED"):
        execute_generation(**_kwargs(tmp_path, shot_id, store, review, provider_factory=lambda: provider))
