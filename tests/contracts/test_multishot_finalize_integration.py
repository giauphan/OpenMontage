import pytest
import os
import shutil
from pathlib import Path

from lib.media_profiles import MediaProfile
from lib.multishot_finalize_operations import finalize_session, validate_completion
from lib.multishot_session import MultishotSession

@pytest.fixture
def custom_profile():
    return MediaProfile(
        name="test",
        width=320,
        height=240,
        aspect_ratio="1.33",
        fps=30.0,
        codec="libx264",
        audio_codec="aac",
        crf=28
    )

@pytest.fixture
def temp_project(tmp_path):
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    (project_dir / "reports").mkdir()
    (project_dir / "artifacts").mkdir()
    return project_dir

def generate_color_clip(out_path, color, duration=2.0, profile=None):
    from unittest.mock import patch
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        f"-i", f"color=c={color}:s={profile.width}x{profile.height}:d={duration}:r={profile.fps}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    from lib.multishot_session import _file_hash
    final_hash = _file_hash(Path(out_path))

    return {
         "status": "completed",
         "file_path": str(out_path),
         "content_hash": final_hash,
         "validation": {
              "valid": True,
              "input_hash": None,
              "content_hash": final_hash,
              "duration_sec": duration,
              "decode_ok": True,
              "has_video": True,
              "width": profile.width,
              "height": profile.height,
              "fps": profile.fps,
              "video_codec": profile.codec
         }
    }


from tests.fixtures.multishot_mochi import all_project_data

@pytest.fixture
def mochi_artifacts():
    data = all_project_data()
    # Slice first 2 shots for happy path tests
    data["shot_plan"]["shots"] = data["shot_plan"]["shots"][:2]
    for s in data["shot_plan"]["shots"]:
        s["duration_sec"] = 1.0
    data["shot_plan"]["target_duration_sec"] = 2.0

    return {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": data["shot_plan"]
    }

def test_finalize_and_validate_success(temp_project, custom_profile, mochi_artifacts):
    session = MultishotSession(temp_project)

    # Init
    artifacts = mochi_artifacts
    session.initialize(artifacts)

    # Shot 1
    session.bind_input("shot_001", "prompt1", [])
    out1 = temp_project / "s1.mp4"
    res1 = generate_color_clip(out1, "red", 1.0, custom_profile)
    res1["validation"]["input_hash"] = session.get_state()["shots"]["shot_001"]["bound_input"]["input_hash"]
    res1["input_hash"] = res1["validation"]["input_hash"]
    session.record_result("shot_001", 1, res1)
    session.review_shot("shot_001", 1, True, artifacts["shot_plan"]["shots"][0]["end_state"], "tester", "ok")

    # Shot 2
    session.bind_input("shot_002", "prompt2", [])
    out2 = temp_project / "s2.mp4"
    res2 = generate_color_clip(out2, "blue", 1.0, custom_profile)
    res2["validation"]["input_hash"] = session.get_state()["shots"]["shot_002"]["bound_input"]["input_hash"]
    res2["input_hash"] = res2["validation"]["input_hash"]
    session.record_result("shot_002", 1, res2)
    session.review_shot("shot_002", 1, True, artifacts["shot_plan"]["shots"][1]["end_state"], "tester", "ok")

    # New session read to simulate clean state crossing
    evidence = finalize_session(temp_project, custom_profile)
    assert evidence["final_path"].endswith(".mp4")
    assert evidence["validation"]["valid"] is True

    comp = validate_completion(temp_project)
    assert comp["valid"] is True

@pytest.fixture
def mochi_artifacts_3shot():
    data = all_project_data()
    # Slice first 3 shots for failure path tests
    data["shot_plan"]["shots"] = data["shot_plan"]["shots"][:3]
    for s in data["shot_plan"]["shots"]:
        s["duration_sec"] = 1.0
    data["shot_plan"]["target_duration_sec"] = 3.0

    return {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": data["shot_plan"]
    }

def test_missing_middle_3_shot_failure(temp_project, custom_profile, mochi_artifacts_3shot):
    session = MultishotSession(temp_project)

    artifacts = mochi_artifacts_3shot
    session.initialize(artifacts)

    # 1 bound/completed
    session.bind_input("shot_001", "prompt1", [])
    out1 = temp_project / "s1.mp4"
    res1 = generate_color_clip(out1, "red", 1.0, custom_profile)
    res1["validation"]["input_hash"] = session.get_state()["shots"]["shot_001"]["bound_input"]["input_hash"]
    res1["input_hash"] = res1["validation"]["input_hash"]
    session.record_result("shot_001", 1, res1)
    session.review_shot("shot_001", 1, True, artifacts["shot_plan"]["shots"][0]["end_state"], "tester", "ok")

    # Shot 2 remains pending, so finalization must reject the incomplete sequence.
    with pytest.raises(ValueError, match="Shot shot_002 status is PENDING but must be ACCEPTED"):
        finalize_session(temp_project, custom_profile)

def test_stale_source_invalidation(temp_project, custom_profile, mochi_artifacts):
    session = MultishotSession(temp_project)
    artifacts = mochi_artifacts
    session.initialize(artifacts)

    session.bind_input("shot_001", "prompt1", [])
    out1 = temp_project / "s1.mp4"
    res1 = generate_color_clip(out1, "red", 1.0, custom_profile)
    res1["validation"]["input_hash"] = session.get_state()["shots"]["shot_001"]["bound_input"]["input_hash"]
    res1["input_hash"] = res1["validation"]["input_hash"]
    session.record_result("shot_001", 1, res1)
    session.review_shot("shot_001", 1, True, artifacts["shot_plan"]["shots"][0]["end_state"], "tester", "ok")

    session.bind_input("shot_002", "prompt2", [])
    out2 = temp_project / "s2.mp4"
    res2 = generate_color_clip(out2, "blue", 1.0, custom_profile)
    res2["validation"]["input_hash"] = session.get_state()["shots"]["shot_002"]["bound_input"]["input_hash"]
    res2["input_hash"] = res2["validation"]["input_hash"]
    session.record_result("shot_002", 1, res2)
    session.review_shot("shot_002", 1, True, artifacts["shot_plan"]["shots"][1]["end_state"], "tester", "ok")

    finalize_session(temp_project, custom_profile)
    assert validate_completion(temp_project)["valid"] is True

    # Regenerate S1 with its existing schema-valid end state.
    session.regenerate_shot(
        "shot_001",
        artifacts["shot_plan"]["shots"][0]["end_state"],
    )

    assert validate_completion(temp_project)["valid"] is False

def test_completion_rejects_corrupted_accepted_source(temp_project, custom_profile, mochi_artifacts):
    session = MultishotSession(temp_project)
    artifacts = mochi_artifacts
    session.initialize(artifacts)
    for shot_id, color in (("shot_001", "red"), ("shot_002", "blue")):
        session.bind_input(shot_id, shot_id, [])
        output = temp_project / f"{shot_id}.mp4"
        result = generate_color_clip(output, color, 1.0, custom_profile)
        input_hash = session.get_state()["shots"][shot_id]["bound_input"]["input_hash"]
        result["input_hash"] = input_hash
        result["validation"]["input_hash"] = input_hash
        session.record_result(shot_id, 1, result)
        session.review_shot(
            shot_id, 1, True,
            artifacts["shot_plan"]["shots"][int(shot_id[-1]) - 1]["end_state"],
            "tester", "ok",
        )

    finalize_session(temp_project, custom_profile)
    source = temp_project / "shot_001.mp4"
    source.write_bytes(source.read_bytes() + b"corrupt")

    result = validate_completion(temp_project)
    assert result["valid"] is False
    assert "tampered" in result["reason"]


def test_completion_rejects_mutated_audio(temp_project, custom_profile, mochi_artifacts):
    session = MultishotSession(temp_project)
    artifacts = mochi_artifacts
    session.initialize(artifacts)
    for shot_id, color in (("shot_001", "red"), ("shot_002", "blue")):
        session.bind_input(shot_id, shot_id, [])
        output = temp_project / f"{shot_id}.mp4"
        result = generate_color_clip(output, color, 1.0, custom_profile)
        input_hash = session.get_state()["shots"][shot_id]["bound_input"]["input_hash"]
        result["input_hash"] = input_hash
        result["validation"]["input_hash"] = input_hash
        session.record_result(shot_id, 1, result)
        session.review_shot(
            shot_id, 1, True,
            artifacts["shot_plan"]["shots"][int(shot_id[-1]) - 1]["end_state"],
            "tester", "ok",
        )

    audio = temp_project / "narration.wav"
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(audio)],
        check=True, capture_output=True,
    )
    finalize_session(temp_project, custom_profile, narration=str(audio), ducking_ratio=3.0)
    audio.write_bytes(audio.read_bytes() + b"changed")

    result = validate_completion(temp_project)
    assert result["valid"] is False
    assert "mismatched" in result["reason"] or "tampered" in result["reason"]


def test_completion_remains_valid_after_session_reload(temp_project, custom_profile, mochi_artifacts):
    session = MultishotSession(temp_project)
    artifacts = mochi_artifacts
    session.initialize(artifacts)
    for shot_id, color in (("shot_001", "red"), ("shot_002", "blue")):
        session.bind_input(shot_id, shot_id, [])
        output = temp_project / f"{shot_id}.mp4"
        result = generate_color_clip(output, color, 1.0, custom_profile)
        input_hash = session.get_state()["shots"][shot_id]["bound_input"]["input_hash"]
        result["input_hash"] = input_hash
        result["validation"]["input_hash"] = input_hash
        session.record_result(shot_id, 1, result)
        session.review_shot(
            shot_id, 1, True,
            artifacts["shot_plan"]["shots"][int(shot_id[-1]) - 1]["end_state"],
            "tester", "ok",
        )

    finalize_session(temp_project, custom_profile)
    reloaded_session = MultishotSession(temp_project)
    assert reloaded_session.get_state()["final_evidence"]
    assert validate_completion(temp_project) == {"valid": True, "reason": "Pass"}


def test_preserved_previous_final_on_failure(temp_project, custom_profile, mochi_artifacts):
    session = MultishotSession(temp_project)
    artifacts = mochi_artifacts
    session.initialize(artifacts)

    session.bind_input("shot_001", "prompt1", [])
    out1 = temp_project / "s1.mp4"
    res1 = generate_color_clip(out1, "red", 1.0, custom_profile)
    res1["validation"]["input_hash"] = session.get_state()["shots"]["shot_001"]["bound_input"]["input_hash"]
    res1["input_hash"] = res1["validation"]["input_hash"]
    session.record_result("shot_001", 1, res1)
    session.review_shot("shot_001", 1, True, artifacts["shot_plan"]["shots"][0]["end_state"], "tester", "ok")

    session.bind_input("shot_002", "prompt2", [])
    out2 = temp_project / "s2.mp4"
    res2 = generate_color_clip(out2, "blue", 1.0, custom_profile)
    res2["validation"]["input_hash"] = session.get_state()["shots"]["shot_002"]["bound_input"]["input_hash"]
    res2["input_hash"] = res2["validation"]["input_hash"]
    session.record_result("shot_002", 1, res2)
    session.review_shot("shot_002", 1, True, artifacts["shot_plan"]["shots"][1]["end_state"], "tester", "ok")

    prev_evidence = finalize_session(temp_project, custom_profile)
    prev_path = prev_evidence["final_path"]
    from lib.multishot_session import _file_hash
    prev_bytes = Path(prev_path).read_bytes()
    prev_hash = _file_hash(Path(prev_path))

    assert os.path.exists(prev_path)

    session.regenerate_shot(
        "shot_001",
        artifacts["shot_plan"]["shots"][0]["end_state"],
    )

    session.bind_input("shot_001", "prompt1a", [])
    out_bad = temp_project / "s1bad.txt"
    out_bad.write_text("corrupt video data")
    ch = _file_hash(out_bad)

    res_bad = {
         "status": "completed",
         "file_path": str(out_bad),
         "content_hash": ch,
         "input_hash": session.get_state()["shots"]["shot_001"]["bound_input"]["input_hash"],
         "validation": {
              "valid": True,
              "input_hash": session.get_state()["shots"]["shot_001"]["bound_input"]["input_hash"],
              "content_hash": ch,
              "duration_sec": 1.0,
              "decode_ok": True,
              "has_video": True,
              "width": custom_profile.width,
              "height": custom_profile.height,
              "fps": custom_profile.fps,
              "video_codec": custom_profile.codec
         }
    }
    with pytest.raises(ValueError, match="Media file is unreadable or has no video stream"):
        session.record_result("shot_001", 2, res_bad)

    with pytest.raises(ValueError, match="Shot shot_001 status is BOUND but must be ACCEPTED"):
        finalize_session(temp_project, custom_profile)

    assert Path(prev_path).read_bytes() == prev_bytes
    assert _file_hash(Path(prev_path)) == prev_hash
    assert validate_completion(temp_project)["valid"] is False
