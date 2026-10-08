"""End-to-end contract tests for multi-shot workflows (2-shot 10s and 6-shot 30s)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest
from PIL import Image

from tools.tool_registry import ToolRegistry
from tools.video.multishot import Multishot
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_shot_keyframe,
)
from tests.fixtures.multishot_mochi import all_project_data


class OfflineProvider:
    provider = "kling_official"

    def __init__(self):
        self.submissions = 0

    def validate_spec(self, spec):
        assert spec.provider == self.provider

    def submit(self, spec, attempt, idempotency_key):
        self.submissions += 1
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
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "color=c=black:s=160x160:r=24",
                "-t", "5", "-an", "-pix_fmt", "yuv420p", str(target),
            ],
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return str(target)


@pytest.mark.parametrize("n_shots,duration", [(2, 10), (6, 30)])
def test_multishot_end_to_end_workflow(tmp_path, n_shots, duration):
    data = all_project_data()
    shots = data["shot_plan"]["shots"][:n_shots]
    data["shot_plan"]["shots"] = shots
    data["shot_plan"]["target_duration_sec"] = duration

    planning = {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": data["shot_plan"],
    }

    provider = OfflineProvider()
    tool = Multishot(provider_factory=lambda: provider)
    project_id = f"e2e_{n_shots}_shot"
    root_dir = tmp_path

    init_res = tool.execute({
        "operation": "init",
        "project_id": project_id,
        "root_dir": str(root_dir),
        "title": f"E2E {n_shots} Shot",
        "planning_artifacts": planning,
    })
    assert init_res.success, init_res.error
    project_dir = Path(init_res.data["project_dir"])

    brief = {
        "version": "1.0",
        "title": data["project_title"],
        "hook": data["story"]["beats"][0]["summary"],
        "key_points": [b["summary"] for b in data["story"]["beats"]],
        "tone": "playful",
        "style": "cartoon",
        "target_platform": "tiktok",
        "target_duration_seconds": duration,
    }

    stages_data = [
        ("idea", {"brief": brief, "request": data["request"]}),
        ("story", {"story": data["story"]}),
        ("identity", {"character_bible": data["character_bible"], "style_bible": data["style_bible"]}),
        ("shot_plan", {"shot_plan": data["shot_plan"]}),
        ("planning", {"continuity_state": {"version": 1, "accepted_through_shot": None, "character_state": {}, "environment_state": {"kitchen": "clean"}, "object_state": {}}}),
    ]

    for stage, artifacts in stages_data:
        cp_res = tool.execute({
            "operation": "checkpoint",
            "project_id": project_id,
            "root_dir": str(root_dir),
            "stage": stage,
            "artifacts": artifacts,
            "human_approved": stage != "idea",
        })
        assert cp_res.success, f"Stage {stage} failed: {cp_res.error}"

    refs = project_dir / "refs"
    refs.mkdir(exist_ok=True)
    master = refs / "master.png"
    Image.new("RGB", (32, 32), color=(255, 128, 0)).save(master)
    store = new_reference_store()
    register_character_master(store, "char_mochi", master)

    for shot in shots:
        kf = refs / f"{shot['id']}.png"
        Image.new("RGB", (32, 32), color=(128, 128, 128)).save(kf)
        register_shot_keyframe(store, shot["id"], kf, derived_from_character="char_mochi")

    review = {"approved": True, "reviewer": "tester", "notes": "ok"}

    for i, shot in enumerate(shots):
        shot_id = shot["id"]
        gen_res = tool.execute({
            "operation": "generate",
            "project_id": project_id,
            "root_dir": str(root_dir),
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
        assert gen_res.success, f"Generate {shot_id} failed: {gen_res.error}"
        assert gen_res.data["status"] == "completed"
        assert gen_res.data["shot"]["status"] == "GENERATED"

        sub_count_before = provider.submissions
        gen_again = tool.execute({
            "operation": "generate",
            "project_id": project_id,
            "root_dir": str(root_dir),
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
        assert gen_again.success
        assert provider.submissions == sub_count_before

        rev_res = tool.execute({
            "operation": "review",
            "project_id": project_id,
            "root_dir": str(root_dir),
            "shot_id": shot_id,
            "revision": gen_res.data["shot"]["revision"],
            "accepted": True,
            "end_state": shot["end_state"],
            "reviewer": "tester",
            "notes": "continuity verified",
        })
        assert rev_res.success, rev_res.error

    asset_manifest = {
        "version": "1.0",
        "assets": [{"shot_id": s["id"], "path": str(project_dir / f"{s['id']}.mp4"), "status": "accepted"} for s in shots],
    }
    cp_assets = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(root_dir),
        "stage": "assets",
        "artifacts": {"asset_manifest": asset_manifest},
        "human_approved": True,
    })
    assert cp_assets.success, cp_assets.error

    edit_decisions = {
        "version": "1.0",
        "cuts": [{"shot_id": s["id"], "action": "keep"} for s in shots],
        "render_runtime": "ffmpeg",
    }
    cp_edit = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(root_dir),
        "stage": "edit",
        "artifacts": {"edit_decisions": edit_decisions},
        "human_approved": True,
    })
    assert cp_edit.success, cp_edit.error

    fin_res = tool.execute({
        "operation": "finalize",
        "project_id": project_id,
        "root_dir": str(root_dir),
    })
    assert fin_res.success, fin_res.error

    val_res = tool.execute({
        "operation": "validate_completion",
        "project_id": project_id,
        "root_dir": str(root_dir),
    })
    assert val_res.success, val_res.error
    assert val_res.data["valid"] is True

    render_report = {
        "version": "1.0",
        "output_path": str(project_dir / "renders" / "final.mp4"),
        "duration_sec": float(duration),
        "status": "success",
    }
    cp_compose = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(root_dir),
        "stage": "compose",
        "artifacts": {"render_report": render_report},
        "human_approved": True,
    })
    assert cp_compose.success, cp_compose.error
