"""Contract tests for public multishot generate operation via registry and tool."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.tool_registry import ToolRegistry
from tools.video.multishot import Multishot
from lib.multishot_session import MultishotSession
from lib.multishot_workspace import init_multishot_project
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_shot_keyframe,
)


class OfflineProvider:
    provider = "kling_official"

    def __init__(self, *, unknown=False):
        self.unknown = unknown
        self.submissions = 0

    def validate_spec(self, spec):
        assert spec.provider == self.provider

    def submit(self, spec, attempt, idempotency_key):
        self.submissions += 1
        if self.unknown:
            raise RuntimeError("transport interrupted")
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


def test_multishot_generate_discovery():
    registry = ToolRegistry()
    registry.discover("tools.video.multishot")
    tool = registry.get("multishot")
    assert tool is not None
    assert isinstance(tool, Multishot)
    info = tool.get_info()
    assert "generate" in info["capabilities"]


def test_public_generate_success(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    tool = Multishot(provider_factory=lambda: provider)

    result = tool.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
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
    })

    assert result.success
    assert result.data["status"] == "completed"
    assert result.data["shot"]["status"] == "GENERATED"
    assert provider.submissions == 1
    assert result.data["cost_entry_status"] == "completed"


def test_public_generate_no_approval_zero_submits(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    tool = Multishot(provider_factory=lambda: provider)

    result = tool.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {},
        "spend_approved": False,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
    })

    assert not result.success
    assert provider.submissions == 0


def test_public_generate_fresh_instance_reuse(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    first_provider = OfflineProvider()
    tool1 = Multishot(provider_factory=lambda: first_provider)
    tool1.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {},
        "spend_approved": True,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
    })

    second_provider = OfflineProvider()
    tool2 = Multishot(provider_factory=lambda: second_provider)
    result = tool2.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {},
        "spend_approved": True,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
    })

    assert result.success
    assert first_provider.submissions == 1
    assert second_provider.submissions == 0
    ledger = json.loads((tmp_path / "reports" / "cost_log.json").read_text())
    assert len(ledger["entries"]) == 1


def test_public_generate_changed_settings_rejected(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    tool = Multishot(provider_factory=lambda: provider)
    tool.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {},
        "spend_approved": True,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
    })

    result = tool.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {"mode": "pro"},
        "spend_approved": True,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
    })

    assert not result.success


def test_public_generate_no_provider_factory_from_inputs(tmp_path):
    _, shot_id, store, review = _setup(tmp_path)
    provider = OfflineProvider()
    tool = Multishot()

    result = tool.execute({
        "operation": "generate",
        "project_id": tmp_path.name,
        "root_dir": str(tmp_path.parent),
        "shot_id": shot_id,
        "provider": "kling_official",
        "model": "kling-v1",
        "settings": {},
        "spend_approved": True,
        "budget_usd": 10.0,
        "estimated_usd": 1.0,
        "reference_store": store,
        "reference_review": review,
        "provider_factory": lambda: provider,
    })

    assert not result.success
    assert provider.submissions == 0
