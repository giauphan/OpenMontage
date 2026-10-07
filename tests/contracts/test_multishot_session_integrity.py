import pytest
import subprocess
from pathlib import Path

from lib.multishot_session import MultishotSession, _file_hash
from lib.multishot_workspace import init_multishot_project
from lib.multishot_media import probe_clip
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

def create_valid_vid(tmp_path):
    vid_path = tmp_path / "vid1.mp4"
    if not vid_path.exists():
        subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=5:r=30", "-y", str(vid_path)], check=True, capture_output=True)
    return vid_path

def test_session_integrity_negatives(tmp_path, fake_artifacts):
    project_dir = tmp_path / "integrity"
    init_multishot_project(project_dir.name, title="Integrity", pipeline_dir=tmp_path)
    session = MultishotSession(project_dir)

    # 1. Reject init with missing artifacts
    del fake_artifacts["style_bible"]
    with pytest.raises(ValueError, match="exact 5 artifacts"):
        session.initialize(fake_artifacts)

    # put it back and initialize
    data = all_project_data()
    fake_artifacts["style_bible"] = data["style_bible"]
    session.initialize(fake_artifacts)

    # 2. Corrupt / forged output rejection
    vid_path = create_valid_vid(tmp_path)
    file_checksum = _file_hash(vid_path)

    session.bind_input("shot_001", "some prompt", [])
    s1 = session.get_state()["shots"]["shot_001"]

    # forge probe duration
    forged_probe = probe_clip(str(vid_path), timeout=5.0)
    forged_probe["duration_sec"] = 100.0 # deviates from physical
    forged_probe["valid"] = True
    forged_probe["input_hash"] = s1["bound_input"]["input_hash"]
    forged_probe["content_hash"] = file_checksum

    with pytest.raises(ValueError, match="contradicts current media|failed clip constraints"):
        session.record_result("shot_001", 1, {
            "status": "completed",
            "file_path": str(vid_path),
            "input_hash": s1["bound_input"]["input_hash"],
            "content_hash": file_checksum,
            "validation": forged_probe # The session will ignore this and reprobe, and original is 5s, matching planned, wait, original 5s matches 5s planned!
        })

    # To test forged failure, let's create a real clip of wrong length
    bad_vid = tmp_path / "bad.mp4"
    subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=10:r=30", "-y", str(bad_vid)], check=True, capture_output=True)
    real_failing_probe = probe_clip(str(bad_vid), timeout=5.0)
    real_failing_probe["valid"] = True
    real_failing_probe["input_hash"] = s1["bound_input"]["input_hash"]
    real_failing_probe["content_hash"] = _file_hash(bad_vid)

    with pytest.raises(ValueError, match="failed clip constraints|failed clip constraints"):
        session.record_result("shot_001", 1, {
            "status": "completed",
            "file_path": str(bad_vid),
            "input_hash": s1["bound_input"]["input_hash"],
            "content_hash": _file_hash(bad_vid),
            "validation": real_failing_probe
        })

    # 3. Failed outcome preserves continuity
    valid_probe = probe_clip(str(vid_path), timeout=5.0)
    valid_probe["valid"] = True
    valid_probe["input_hash"] = s1["bound_input"]["input_hash"]
    valid_probe["content_hash"] = file_checksum
    session.record_result("shot_001", 1, {
        "status": "failed",
        "error": "some issue",
        "input_hash": s1["bound_input"]["input_hash"]
    })

    state = session.get_state()
    assert state["shots"]["shot_001"]["status"] == "FAILED"
    assert state["shots"]["shot_001"].get("media_result")["error"] == "some issue"
    assert state["continuity"]["version"] == 1 # unchanged

    # 3b. Recovery from FAILED by re-binding exact same input
    # First test that a different input is rejected without formal regeneration
    with pytest.raises(ValueError, match="Cannot re-bind a different input"):
        session.bind_input("shot_001", "some DIFFERENT prompt", [])

    # Now bind the exact same input to recover to BOUND state, keeping revision intact
    session.bind_input("shot_001", "some prompt", [])
    state_recovered = session.get_state()
    assert state_recovered["shots"]["shot_001"]["status"] == "BOUND"
    assert state_recovered["shots"]["shot_001"]["revision"] == 1
    assert len(state_recovered["shots"]["shot_001"]["history"]) == 1
    assert state_recovered["shots"]["shot_001"]["history"][0]["status"] == "FAILED"

    # Now we can record the successful result
    session.record_result("shot_001", 1, {
        "status": "completed",
        "file_path": str(vid_path),
        "input_hash": s1["bound_input"]["input_hash"],
        "content_hash": file_checksum,
        "validation": valid_probe
    })

    # 4. Immediate predecessor check (cannot bind shot 2 when shot 1 isn't accepted)
    with pytest.raises(ValueError, match="requires immediately preceding shot"):
        session.bind_input("shot_002", "some prompt", [])

    # Test review boolean validation
    with pytest.raises(ValueError, match="boolean"):
        session.review_shot("shot_001", 1, "yes", s1["planned_end_state"], "system", "notes")
