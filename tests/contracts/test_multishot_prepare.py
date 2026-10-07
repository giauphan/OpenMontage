import os
import json
import pytest
from pathlib import Path

from tools.tool_registry import ToolRegistry
from tools.video.multishot import Multishot
from lib.multishot_jobs import JobSpec

# Define local fixtures for inputs

@pytest.fixture
def local_mochi_data():
    from tests.fixtures.multishot_mochi import all_project_data
    return all_project_data()

@pytest.fixture
def local_schema_valid_planning(local_mochi_data):
    data = local_mochi_data
    return {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": {"shots": data["shot_plan"]["shots"][:3], "target_duration_sec": 15, "version": "1.0"}
    }


def create_fake_video(tmp_path: Path, filename: str) -> Path:
    import subprocess
    vid_path = tmp_path / filename
    subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=blue:s=16x16:d=5", "-y", str(vid_path)], check=True, capture_output=True)
    return vid_path

def create_fake_image(tmp_path: Path, filename: str) -> Path:
    import subprocess
    img_path = tmp_path / filename
    subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=red:s=16x16", "-frames:v", "1", "-y", str(img_path)], check=True, capture_output=True)
    return img_path

def test_multishot_tool_discovery():
    registry = ToolRegistry()
    registry.discover("tools.video.multishot")
    tool = registry.get("multishot")
    assert tool is not None
    assert isinstance(tool, Multishot)
    info = tool.get_info()
    assert info["capability"] == "multishot_orchestration"

def test_multishot_prepare_and_bind(tmp_path: Path, local_schema_valid_planning):
    import lib.multishot_operations # Ensure operations are patched
    registry = ToolRegistry()
    registry.discover("tools.video.multishot")
    tool = registry.get("multishot")

    project_id = "test_run_prep"

    # Init Project
    init_res = tool.execute({
        "operation": "init",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "planning_artifacts": local_schema_valid_planning
    })
    assert init_res.success

    # Prepare shot 1
    # Missing / unapproved reference_review should reject
    prep_res_err = tool.execute({
        "operation": "prepare_shot",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "reference_store": {},
        "reference_review": {"approved": False, "reviewer": "me", "notes": "bad"}
    })
    assert not prep_res_err.success
    assert "rejected by reference review notes: bad" in prep_res_err.error

    # Add a valid reference image
    img_path = create_fake_image(tmp_path, "ref_img.png")
    from lib.multishot_jobs import file_hash
    ref_hash = file_hash(img_path)
    ref_store = {
        "character:Aria": {"path": str(img_path), "sha256": ref_hash, "owner": "character:Aria", "key": "character:Aria"}
    }

    # Successful prepare
    prep_res = tool.execute({
        "operation": "prepare_shot",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "reference_store": ref_store,
        "reference_review": {"approved": True, "reviewer": "me", "notes": "ok"}
    })
    assert prep_res.success
    assert "prompt" in prep_res.data
    assert "references" in prep_res.data

    prompt = prep_res.data["prompt"]
    refs = prep_res.data["references"]

    # Try preparing shot 2 before shot 1 is accepted, should fail
    prep_s2_err = tool.execute({
        "operation": "prepare_shot",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_002",
        "reference_store": ref_store,
        "reference_review": {"approved": True, "reviewer": "me", "notes": "ok"}
    })
    assert not prep_s2_err.success
    assert "predecessor shot_001 is not ACCEPTED" in prep_s2_err.error

    # Bind the spec
    from lib.multishot_jobs import canonical_input_hash
    ref_hashes = [r["sha256"] for r in refs]
    prompt_hash = canonical_input_hash(provider="mochi", model="v1", settings={}, prompt=prompt, reference_hashes=ref_hashes)

    spec = JobSpec(
        shot_id="shot_001",
        prompt=prompt,
        prompt_hash=prompt_hash,
        reference_hashes=ref_hashes,
        provider="mochi",
        model="v1",
        duration_sec=5.0,
        settings={},
        references=refs,
        revision=1
    )

    bind_res = tool.execute({
        "operation": "bind_input",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "revision": 1,
        "job_spec": spec.to_dict()
    })
    assert bind_res.success
    assert bind_res.data["shot"]["status"] == "BOUND"

    # Change spec should fail idempotent check
    spec2 = JobSpec(
        shot_id="shot_001",
        prompt=prompt,
        prompt_hash=prompt_hash,
        reference_hashes=ref_hashes,
        provider="changed",
        model="v1",
        duration_sec=5.0,
        settings={},
        references=refs,
        revision=1
    )
    bind_err = tool.execute({
        "operation": "bind_input",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "revision": 1,
        "job_spec": spec2.to_dict()
    })
    assert not bind_err.success
    assert "Cannot bind changed job_spec in the same revision" in bind_err.error

    # Record result still works
    job_input_hash = bind_res.data["shot"]["bound_input"]["job_input_hash"]
    vid_path = create_fake_video(tmp_path, "test_shot_001.mp4")
    from lib.multishot_media import probe_clip
    rpt1 = probe_clip(vid_path)
    rpt1["input_hash"] = job_input_hash
    rpt1["valid"] = True
    rpt1["content_hash"] = file_hash(vid_path)

    valid_outcome = {
        "shot_id": "shot_001",
        "status": "completed",
        "file_path": str(vid_path),
        "format": "mp4",
        "attempts": [],
        "input_hash": job_input_hash,
        "duration": 5.0,
        "content_hash": rpt1["content_hash"],
        "validation": rpt1
    }

    r1_res = tool.execute({
         "operation": "record_result",
         "project_id": project_id,
         "root_dir": str(tmp_path),
         "shot_id": "shot_001",
         "revision": 1,
         "outcome": valid_outcome
    })
    assert r1_res.success
    assert r1_res.data["shot"]["status"] == "GENERATED"
