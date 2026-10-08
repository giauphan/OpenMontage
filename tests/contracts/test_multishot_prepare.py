import os
import json
import pytest
from pathlib import Path
from dataclasses import asdict
from PIL import Image

from tools.tool_registry import ToolRegistry
from tools.video.multishot import Multishot
from lib.multishot_jobs import JobSpec
from lib.multishot_references import (
    new_reference_store,
    register_character_master,
    register_environment_reference,
    register_shot_keyframe,
)

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

    non_bool_review = tool.execute({
        "operation": "prepare_shot",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "reference_store": {},
        "reference_review": {"approved": 1, "reviewer": "me", "notes": "bad"}
    })
    assert not non_bool_review.success
    assert "boolean 'approved'" in non_bool_review.error

    missing_reviewer_review = tool.execute({
        "operation": "prepare_shot",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "reference_store": {},
        "reference_review": {"approved": True, "notes": "missing reviewer"}
    })
    assert not missing_reviewer_review.success
    assert "boolean 'approved' and string 'reviewer'" in missing_reviewer_review.error

    # Register valid PNG references with character provenance.
    from lib.multishot_jobs import file_hash
    master_path = tmp_path / "char_mochi_master.png"
    keyframe_path = tmp_path / "shot_001_keyframe.png"
    environment_path = tmp_path / "kitchen_environment.png"
    Image.new("RGB", (16, 16), "orange").save(master_path)
    Image.new("RGB", (16, 16), "blue").save(keyframe_path)
    Image.new("RGB", (16, 16), "green").save(environment_path)

    ref_store = new_reference_store()
    register_character_master(ref_store, "char_mochi", master_path)
    register_environment_reference(ref_store, environment_path)
    register_shot_keyframe(
        ref_store,
        "shot_001",
        keyframe_path,
        derived_from_character="char_mochi",
    )

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
        "operation": "bind_job_spec",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "revision": 1,
        "job_spec": asdict(spec)
    })
    assert bind_res.success
    assert bind_res.data["shot"]["status"] == "BOUND"

    # Change spec should fail idempotent check
    changed_prompt_hash = canonical_input_hash(
        provider="changed",
        model="v1",
        settings={},
        prompt=prompt,
        reference_hashes=ref_hashes,
    )
    spec2 = JobSpec(
        shot_id="shot_001",
        prompt=prompt,
        prompt_hash=changed_prompt_hash,
        reference_hashes=ref_hashes,
        provider="changed",
        model="v1",
        duration_sec=5.0,
        settings={},
        references=refs,
        revision=1
    )
    bind_err = tool.execute({
        "operation": "bind_job_spec",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_001",
        "revision": 1,
        "job_spec": asdict(spec2)
    })
    assert not bind_err.success
    assert "Cannot bind changed job_spec in the same revision" in bind_err.error

    # Record result still works
    job_input_hash = bind_res.data["shot"]["job_input_hash"]
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
