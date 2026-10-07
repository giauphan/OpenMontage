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

    # 3 bound/completed
    # Notice we try to bind shot 3 while shot 2 is still PENDING
    # This might fail earlier depending on continuity logic, but if we assume it works:
    session.bind_input("shot_003", "prompt3", [])
    out3 = temp_project / "s3.mp4"
    res3 = generate_color_clip(out3, "green", 1.0, custom_profile)
    res3["validation"]["input_hash"] = session.get_state()["shots"]["shot_003"]["bound_input"]["input_hash"]
    res3["input_hash"] = res3["validation"]["input_hash"]
    session.record_result("shot_003", 1, res3)

    # We shouldn't be able to review/accept shot 3 if shot 2 is not accepted!
    with pytest.raises(ValueError, match="Predecessor no longer accepted|predecessor"):
        session.review_shot("shot_003", 1, True, artifacts["shot_plan"]["shots"][2]["end_state"], "tester", "ok")

    # Even if we bypassed the review error, finalizer should reject it on pending shot 2
    with pytest.raises(ValueError, match="status is PENDING but must be ACCEPTED"):
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

    # Regenerate S1
    session.regenerate_shot("shot_001", {})

    assert validate_completion(temp_project)["valid"] is False

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

    assert os.path.exists(prev_path)

    # Introduce bad data implicitly dropping status via regen and attempting arbitrary finalize
    # Mock status check to force failure in FFmpeg
    session.regenerate_shot("shot_001", {})

    # Re-completing the newly bound s1 with bad file
    session.bind_input("shot_001", "prompt1a", [])
    out_bad = temp_project / "s1bad.txt"
    with open(out_bad, "w") as f:
        f.write("corrupt video data")
    from lib.multishot_session import _file_hash
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
              "decode_ok": True, # Forged
              "has_video": True,
              "width": custom_profile.width,
              "height": custom_profile.height,
              "fps": custom_profile.fps,
              "video_codec": custom_profile.codec
         }
    }
    session.record_result("shot_001", 2, res_bad)
    session.review_shot("shot_001", 2, True, {}, "tester", "ok")

    with pytest.raises(ValueError):
         finalize_session(temp_project, custom_profile)

    # Previous final path was untouched
    assert os.path.exists(prev_path)
