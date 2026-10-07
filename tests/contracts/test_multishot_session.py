import pytest
import copy
from pathlib import Path
import json
import subprocess
import hashlib

from lib.multishot_session import MultishotSession, _file_hash
from lib.multishot_workspace import init_multishot_project

from tests.fixtures.multishot_mochi import all_project_data

@pytest.fixture
def fake_artifacts():
    data = all_project_data()
    return {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": {"shots": data["shot_plan"]["shots"][:3], "target_duration_sec": 15, "version": "1.0"}
    }


def test_session_lifecycle(tmp_path, fake_artifacts, monkeypatch):
    project_dir = tmp_path / "project"
    init_multishot_project("project", title="Test", pipeline_dir=tmp_path)

    session = MultishotSession(project_dir)
    session.initialize(fake_artifacts)

    # Persists via workspace helpers correctly
    state = session.get_state()
    assert state["project_id"] == "project"
    assert state["revision"] == 1
    assert len(state["shots"]) == 3
    assert state["shots"]["shot_001"]["status"] == "PENDING"

    # Bind input for shot 1
    session.bind_input("shot_001", "some prompt", [{"id": "ref1"}])
    state = session.get_state()
    assert state["shots"]["shot_001"]["status"] == "BOUND"
    assert state["shots"]["shot_001"]["bound_input"]["prompt"] == "some prompt"

    # Input binding fails if changed without regen
    with pytest.raises(ValueError, match="Cannot re-bind"):
        session.bind_input("shot_001", "another prompt", [])

    # Needs acceptance before next shot can bind input with continuity
    with pytest.raises(ValueError, match="requires immediately preceding shot"):
        session.bind_input("shot_002", "prompt 2", [])

    # Record Media Result
    # Create valid video for tests
    vid_path = tmp_path / "vid1.mp4"
    subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=5:r=30", "-y", str(vid_path)], check=True, capture_output=True)
    from lib.multishot_media import probe_clip
    report = probe_clip(str(vid_path), timeout=10.0)
    state = session.get_state()
    report["input_hash"] = state["shots"]["shot_001"]["bound_input"]["input_hash"]

    file_checksum = _file_hash(vid_path)
    report["content_hash"] = file_checksum
    report["file_hash"] = file_checksum
    report["valid"] = True

    session.record_result("shot_001", 1, {"status": "completed", "duration": 5.0, "format": "mp4", "file_path": str(vid_path), "input_hash": report["input_hash"], "content_hash": file_checksum, "validation": report})

    # Complete Review via continuity
    session.review_shot("shot_001", 1, True, state["shots"]["shot_001"]["planned_end_state"], "system", "looks good")
    state = session.get_state()
    assert state["shots"]["shot_001"]["status"] == "ACCEPTED"
    assert state["continuity"]["accepted_through_shot"] == "shot_001"

    # Now bind shot 2
    session.bind_input("shot_002", "prompt 2", [])
    report2 = probe_clip(str(vid_path), timeout=10.0)
    state = session.get_state()
    report2["input_hash"] = state["shots"]["shot_002"]["bound_input"]["input_hash"]
    report2["content_hash"] = file_checksum
    report2["file_hash"] = file_checksum
    report2["valid"] = True
    session.record_result("shot_002", 1, {"status": "completed", "duration": 5.0, "format": "mp4", "file_path": str(vid_path), "input_hash": report2["input_hash"], "content_hash": file_checksum, "validation": report2})
    session.review_shot("shot_002", 1, True, state["shots"]["shot_002"]["planned_end_state"], "system", "ok")

    # Regen shot 1 with changed state -> shot 2 goes STALE
    new_end_state = copy.deepcopy(state["shots"]["shot_001"]["planned_end_state"])
    if "character" not in new_end_state:
        new_end_state["character"] = ""
    new_end_state["character"] = new_end_state["character"] + " with apron stained"

    stale = session.regenerate_shot("shot_001", end_state=new_end_state)
    assert stale == ["shot_002", "shot_003"]
    state = session.get_state()
    assert state["shots"]["shot_001"]["status"] == "PENDING"
    assert state["shots"]["shot_001"]["revision"] == 2
    assert state["shots"]["shot_002"]["status"] == "STALE"
    assert state["shots"]["shot_002"]["revision"] == 2
    assert state["shots"]["shot_003"]["status"] == "STALE"
    assert state["continuity"]["accepted_through_shot"] is None # Should revert


def test_regenerate_preserves_downstream_media_if_state_unchanged(tmp_path, fake_artifacts, monkeypatch):
    project_dir = tmp_path / "project2"
    init_multishot_project("project2", title="Test", pipeline_dir=tmp_path)
    session = MultishotSession(project_dir)
    session.initialize(fake_artifacts)

    import subprocess
    vid_path = tmp_path / "vid1.mp4"
    subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=5:r=30", "-y", str(vid_path)], check=True, capture_output=True)
    from lib.multishot_media import probe_clip

    file_checksum = _file_hash(vid_path)

    session.bind_input("shot_001", "p1", [])
    s1 = session.get_state()
    rpt1 = probe_clip(str(vid_path), timeout=10.0)
    rpt1["input_hash"] = s1["shots"]["shot_001"]["bound_input"]["input_hash"]
    rpt1["content_hash"] = file_checksum
    rpt1["file_hash"] = file_checksum
    rpt1["valid"] = True
    session.record_result("shot_001", 1, {"status": "completed", "file_path": str(vid_path), "input_hash": rpt1["input_hash"], "content_hash": file_checksum, "validation": rpt1})
    session.review_shot("shot_001", 1, True, s1["shots"]["shot_001"]["planned_end_state"], "u", "n")

    session.bind_input("shot_002", "p2", [])
    s2 = session.get_state()
    rpt2 = probe_clip(str(vid_path), timeout=10.0)
    rpt2["input_hash"] = s2["shots"]["shot_002"]["bound_input"]["input_hash"]
    rpt2["content_hash"] = file_checksum
    rpt2["file_hash"] = file_checksum
    rpt2["valid"] = True
    session.record_result("shot_002", 1, {"status": "completed", "file_path": str(vid_path), "input_hash": rpt2["input_hash"], "content_hash": file_checksum, "validation": rpt2})
    session.review_shot("shot_002", 1, True, s2["shots"]["shot_002"]["planned_end_state"], "u", "n")

    session.bind_input("shot_003", "p3", [])
    s3 = session.get_state()
    rpt3 = probe_clip(str(vid_path), timeout=10.0)
    rpt3["input_hash"] = s3["shots"]["shot_003"]["bound_input"]["input_hash"]
    rpt3["content_hash"] = file_checksum
    rpt3["file_hash"] = file_checksum
    rpt3["valid"] = True
    session.record_result("shot_003", 1, {"status": "completed", "file_path": str(vid_path), "input_hash": rpt3["input_hash"], "content_hash": file_checksum, "validation": rpt3})
    session.review_shot("shot_003", 1, True, s3["shots"]["shot_003"]["planned_end_state"], "u", "n")

    # Regenerate shot 2, state the exact same!
    stale = session.regenerate_shot("shot_002", end_state=s2["shots"]["shot_002"]["planned_end_state"])
    # Should not invalidate shot 3!
    assert stale == []
    state = session.get_state()
    assert state["shots"]["shot_002"]["status"] == "PENDING"
    assert state["shots"]["shot_003"]["status"] == "ACCEPTED"
    assert state["continuity"]["accepted_through_shot"] == "shot_001"

def test_invalidate_reference(tmp_path, fake_artifacts, monkeypatch):
    project_dir = tmp_path / "project3"
    init_multishot_project("project3", title="Test", pipeline_dir=tmp_path)
    session = MultishotSession(project_dir)
    session.initialize(fake_artifacts)

    import subprocess
    vid_path = tmp_path / "vid1.mp4"
    subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=5:r=30", "-y", str(vid_path)], check=True, capture_output=True)
    from lib.multishot_media import probe_clip

    file_checksum = _file_hash(vid_path)

    session.bind_input("shot_001", "p1", ["refA"])
    s1 = session.get_state()
    rpt1 = probe_clip(str(vid_path), timeout=10.0)
    rpt1["input_hash"] = s1["shots"]["shot_001"]["bound_input"]["input_hash"]
    rpt1["content_hash"] = file_checksum
    rpt1["file_hash"] = file_checksum
    rpt1["valid"] = True
    session.record_result("shot_001", 1, {"status": "completed", "file_path": str(vid_path), "input_hash": rpt1["input_hash"], "content_hash": file_checksum, "validation": rpt1})
    session.review_shot("shot_001", 1, True, s1["shots"]["shot_001"]["planned_end_state"], "u", "n")

    session.bind_input("shot_002", "p2", [{"some": "refB"}])
    s2 = session.get_state()
    rpt2 = probe_clip(str(vid_path), timeout=10.0)
    rpt2["input_hash"] = s2["shots"]["shot_002"]["bound_input"]["input_hash"]
    rpt2["content_hash"] = file_checksum
    rpt2["file_hash"] = file_checksum
    rpt2["valid"] = True
    session.record_result("shot_002", 1, {"status": "completed", "file_path": str(vid_path), "input_hash": rpt2["input_hash"], "content_hash": file_checksum, "validation": rpt2})
    session.review_shot("shot_002", 1, True, s2["shots"]["shot_002"]["planned_end_state"], "u", "n")

    session.bind_input("shot_003", "p3", [])
    s3 = session.get_state()
    rpt3 = probe_clip(str(vid_path), timeout=10.0)
    rpt3["input_hash"] = s3["shots"]["shot_003"]["bound_input"]["input_hash"]
    rpt3["content_hash"] = file_checksum
    rpt3["file_hash"] = file_checksum
    rpt3["valid"] = True
    session.record_result("shot_003", 1, {"status": "completed", "file_path": str(vid_path), "input_hash": rpt3["input_hash"], "content_hash": file_checksum, "validation": rpt3})
    session.review_shot("shot_003", 1, True, s3["shots"]["shot_003"]["planned_end_state"], "u", "n")


    stale = session.invalidate_reference("refB")
    assert stale == ["shot_002", "shot_003"] # shot 3 is downstream of shot 2, so it's stale
    state = session.get_state()
    assert state["shots"]["shot_002"]["status"] == "PENDING"
    assert state["shots"]["shot_003"]["status"] == "STALE"
