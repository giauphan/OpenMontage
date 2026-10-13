"""End-to-end contract tests for multi-shot workflows (2-shot 10s and 6-shot 30s)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest
from PIL import Image

from lib.multishot_continuity import initial_continuity
from lib.multishot_media import probe_clip
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
                "-i", "testsrc=size=160x160:rate=24",
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
    data["request"]["target_duration_sec"] = duration
    # Small, silent media keeps this an offline contract test, not a quality demo.
    profile = {
        "name": "multishot-e2e",
        "width": 180,
        "height": 320,
        "aspect_ratio": "9:16",
        "fps": 24,
        "codec": "libx264",
        "audio_codec": "aac",
        "crf": 28,
        "pixel_format": "yuv420p",
    }
    data["request"]["resolution"] = {"width": profile["width"], "height": profile["height"]}
    data["request"]["fps"] = profile["fps"]
    data["request"]["audio"] = {
        "narration": False, "music": False, "sfx": False, "subtitles": False,
    }
    assert [shot["order"] for shot in shots] == list(range(1, n_shots + 1))
    assert sum(shot["duration_sec"] for shot in shots) == duration

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
        ("planning", {"continuity_state": initial_continuity()}),
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

    assets = []
    cost_path = project_dir / "reports" / "cost_log.json"
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

        generated = gen_res.data["shot"]
        continuity_in = generated["bound_input"]["continuity_in"]
        if i == 0:
            assert continuity_in == initial_continuity()
        else:
            predecessor = shots[i - 1]
            assert continuity_in["accepted_through_shot"] == predecessor["id"]
            assert continuity_in["accepted_order"] == predecessor["order"]
            assert continuity_in["accepted_end_state"] == predecessor["end_state"]
            assert continuity_in["accepted_end_state_fingerprint"] == json.dumps(
                predecessor["end_state"], sort_keys=True
            )

        media = generated["media_result"]
        clip_path = Path(media["file_path"])
        assert clip_path.is_file()
        probe = probe_clip(clip_path)
        assert probe["decode_ok"] and probe["has_video"], probe["errors"]
        assert probe["duration_sec"] == pytest.approx(shot["duration_sec"], abs=0.1)
        assert media["validation"]["content_hash"] == media["content_hash"]
        assets.append({
            "id": shot_id,
            "type": "video",
            "path": str(clip_path.relative_to(project_dir)),
            "source_tool": "multishot",
            "scene_id": shot["scene_id"],
            "duration_seconds": probe["duration_sec"],
            "resolution": f"{probe['width']}x{probe['height']}",
            "format": clip_path.suffix.lstrip("."),
        })

        sub_count_before = provider.submissions
        ledger_before = json.loads(cost_path.read_text())
        assert len(ledger_before["entries"]) == i + 1
        # Resume with a fresh tool/provider while GENERATED, before acceptance.
        resume_provider = OfflineProvider()
        resume_tool = Multishot(provider_factory=lambda: resume_provider)
        gen_again = resume_tool.execute({
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
        assert gen_again.success, gen_again.error
        assert gen_again.data["shot"]["status"] == "GENERATED"
        assert gen_again.data["shot"]["bound_input"] == generated["bound_input"]
        assert gen_again.data["shot"]["media_result"] == media
        assert provider.submissions == sub_count_before == i + 1
        assert resume_provider.submissions == 0
        assert json.loads(cost_path.read_text()) == ledger_before

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
        accepted = rev_res.data["shot"]
        assert accepted["status"] == "ACCEPTED"
        assert accepted["review"]["end_state"] == shot["end_state"]
        assert accepted["continuity_before"] == continuity_in
        assert accepted["continuity_after"]["accepted_end_state"] == shot["end_state"]
        assert accepted["continuity_after"]["accepted_through_shot"] == shot_id
        assert accepted["continuity_after"]["accepted_order"] == shot["order"]

    asset_manifest = {"version": "1.0", "assets": assets}
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
        "cuts": [
            {
                "id": asset["id"],
                "source": asset["path"],
                "in_seconds": 0.0,
                "out_seconds": asset["duration_seconds"],
            }
            for asset in assets
        ],
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
        "profile": profile,
    })
    assert fin_res.success, fin_res.error
    assert fin_res.data["shot_order"] == [shot["id"] for shot in shots]
    evidence = fin_res.data["shot_evidence"]
    assert [item["id"] for item in evidence] == [shot["id"] for shot in shots]
    assert [item["planned_duration_sec"] for item in evidence] == [
        shot["duration_sec"] for shot in shots
    ]
    assert [item["file_path"] for item in evidence] == [
        str(project_dir / asset["path"]) for asset in assets
    ]
    assert fin_res.data["validation"]["valid"] is True
    final_path = Path(fin_res.data["final_path"])
    final_probe = probe_clip(final_path)
    assert final_probe["decode_ok"] and final_probe["has_video"], final_probe["errors"]
    assert final_probe["duration_sec"] == pytest.approx(duration, abs=0.1)
    assert (final_probe["width"], final_probe["height"]) == (profile["width"], profile["height"])
    assert final_probe["fps"] == pytest.approx(profile["fps"])

    val_res = tool.execute({
        "operation": "validate_completion",
        "project_id": project_id,
        "root_dir": str(root_dir),
    })
    assert val_res.success, val_res.error
    assert val_res.data["valid"] is True

    report_path = project_dir / "reports" / "render_report.json"
    final_review_path = project_dir / "reports" / "final_review.json"
    assert report_path.is_file()
    assert final_review_path.is_file()
    render_report = json.loads(report_path.read_text())
    final_review = json.loads(final_review_path.read_text())
    assert render_report["version"] == "1.0"
    assert len(render_report["outputs"]) == 1
    rendered_output = render_report["outputs"][0]
    assert rendered_output["path"] == str(final_path.relative_to(project_dir))
    assert rendered_output["duration_seconds"] == pytest.approx(duration, abs=0.1)
    assert render_report["final_review_ref"] == "reports/final_review.json"
    assert final_review["status"] == "pass"
    cp_compose = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(root_dir),
        "stage": "compose",
        "artifacts": {"render_report": render_report, "final_review": final_review},
        "human_approved": True,
    })
    assert cp_compose.success, cp_compose.error
