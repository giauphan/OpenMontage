import os
import json
import pytest
from pathlib import Path

from tools.tool_registry import ToolRegistry
from tools.video.multishot import Multishot

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

# We want to use discovery to register the tool
def test_multishot_tool_discovery():
    registry = ToolRegistry()
    registry.discover("tools.video.multishot")
    tool = registry.get("multishot")
    assert tool is not None
    assert isinstance(tool, Multishot)
    info = tool.get_info()
    assert info["capability"] == "multishot_orchestration"

def test_multishot_tool_public_api(tmp_path: Path, local_schema_valid_planning):
    registry = ToolRegistry()
    registry.discover("tools.video.multishot")
    tool = registry.get("multishot")

    project_id = "test_run_01"

    # 1. Unknown operation
    res = tool.execute({"operation": "fake", "project_id": project_id})
    assert not res.success
    assert "Unknown operation" in res.error

    # 3. Init Project
    init_res = tool.execute({
        "operation": "init",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "planning_artifacts": local_schema_valid_planning
    })

    assert init_res.success
    project_dir = Path(init_res.data["project_dir"])
    assert project_dir.exists()

    # 4. Status
    status_res = tool.execute({
        "operation": "status",
        "project_id": project_id,
        "root_dir": str(tmp_path)
    })

    assert status_res.success
    assert status_res.data["revision"] == 1
    assert "shot_001" in status_res.data["shots"]

    # 5. Complete a valid idea checkpoint FIRST
    from tests.contracts.test_multishot_checkpoint_recovery import BRIEF, REQUEST
    valid_idea_res = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "stage": "idea",
        "artifacts": {"brief": BRIEF, "request": REQUEST},
        "human_approved": True
    })
    assert valid_idea_res.success

    # 5b. Invalid Artifact Checkpoint Rejection (at story stage so idea is satisfied)
    cp_res = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "stage": "story",
        "artifacts": {"bad": {}},
        "human_approved": True
    })
    assert not cp_res.success
    assert "Stage 'story' must include artifact 'story'" in cp_res.error

    # 5c. Invalid Artifact Payload Rejection (present but empty/invalid story dict)
    cp_res_inv = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "stage": "story",
        "artifacts": {"story": {}},
        "human_approved": True
    })
    assert not cp_res_inv.success
    assert "validation" in cp_res_inv.error.lower() or "schema" in cp_res_inv.error.lower() or "required" in cp_res_inv.error.lower()


    # 6. Unapproved Checkpoint Rejection
    cp_res_2 = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "stage": "story",
        "artifacts": {"story": local_schema_valid_planning["story"]},
        "human_approved": False
    })
    assert not cp_res_2.success
    assert ("GATE VIOLATION" in cp_res_2.error or "without human_approved=True" in cp_res_2.error or "requires human approval" in cp_res_2.error)

    # 6b. True -> persisted valid checkpoint readback
    cp_res_3 = tool.execute({
        "operation": "checkpoint",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "stage": "story",
        "artifacts": {"story": local_schema_valid_planning["story"]},
        "human_approved": True
    })
    assert cp_res_3.success
    from lib.checkpoint import read_checkpoint
    chk = read_checkpoint(Path(tmp_path), project_id, "story")
    assert chk is not None
    assert chk["status"] == "completed"

    # 7. Safe Rejection of bad Input
    bind_res = tool.execute({
        "operation": "bind_input",
        "project_id": project_id,
        "root_dir": str(tmp_path),
        "shot_id": "shot_xyz", # Unknown shot id
        "prompt": "Test"
    })
    assert not bind_res.success
    assert "Unknown shot" in bind_res.error

    # 8. Valid generation flows
    b1_res = tool.execute({
         "operation": "bind_input",
         "project_id": project_id,
         "root_dir": str(tmp_path),
         "shot_id": "shot_001",
         "prompt": "Valid Prompt"
    })

    assert b1_res.success
    b1_input_hash = b1_res.data["shot"]["bound_input"]["input_hash"]

    # Use actual video checks to make record_result pass validation
    vid_path = create_fake_video(tmp_path, "test_shot_001.mp4")
    from lib.multishot_jobs import file_hash
    from lib.multishot_media import probe_clip
    rpt1 = probe_clip(vid_path)
    rpt1["input_hash"] = b1_input_hash
    rpt1["valid"] = True
    rpt1["content_hash"] = file_hash(vid_path)

    valid_outcome = {
        "shot_id": "shot_001",
        "status": "completed",
        "file_path": str(vid_path),
        "format": "mp4",
        "attempts": [],
        "input_hash": b1_input_hash,
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

    end_s = local_schema_valid_planning["shot_plan"]["shots"][0]["end_state"]
    rv1_res = tool.execute({
         "operation": "review",
         "project_id": project_id,
         "root_dir": str(tmp_path),
         "shot_id": "shot_001",
         "revision": 1,
         "accepted": True,
         "end_state": end_s,
         "reviewer": "me",
         "notes": "looks good"
    })
    assert rv1_res.success
    assert rv1_res.data["shot"]["status"] == "ACCEPTED"

    # 9. Invalidate reference
    inv_res = tool.execute({
         "operation": "invalidate_reference",
         "project_id": project_id,
         "root_dir": str(tmp_path),
         "reference_key": "some_ref"
    })
    assert inv_res.success

    # 10. Regenerate shot preserves history
    reg_res = tool.execute({
         "operation": "regenerate",
         "project_id": project_id,
         "root_dir": str(tmp_path),
         "shot_id": "shot_001"
    })
    assert reg_res.success

    s_res = tool.execute({
        "operation": "status",
        "project_id": project_id,
        "root_dir": str(tmp_path)
    })
    assert s_res.data["shots"]["shot_001"]["status"] == "PENDING"
    assert s_res.data["shots"]["shot_001"]["revision"] == 2
    assert len(s_res.data["shots"]["shot_001"]["history"]) == 1
