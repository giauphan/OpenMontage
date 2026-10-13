import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from lib.media_profiles import AspectRatio, MediaProfile
from lib.multishot_media import probe_clip
from lib.multishot_session import _file_hash
from tests.fixtures.multishot_mochi import all_project_data
from tools.tool_registry import ToolRegistry


PROFILE = MediaProfile(
    name="test",
    width=320,
    height=240,
    aspect_ratio=AspectRatio.STANDARD_4_3,
    fps=30,
    codec="libx264",
    audio_codec="aac",
    crf=28,
)


def profile_payload():
    payload = asdict(PROFILE)
    payload["aspect_ratio"] = PROFILE.aspect_ratio.value
    return payload


@pytest.fixture
def mochi_two_shot():
    data = all_project_data()
    data["shot_plan"]["shots"] = data["shot_plan"]["shots"][:2]
    for shot in data["shot_plan"]["shots"]:
        shot["duration_sec"] = 1.0
    data["shot_plan"]["target_duration_sec"] = 2.0
    return {
        "request": data["request"],
        "story": data["story"],
        "character_bible": data["character_bible"],
        "style_bible": data["style_bible"],
        "shot_plan": data["shot_plan"],
    }


def new_tool():
    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("multishot")
    assert tool is not None
    return tool


def execute(tool, operation, project_id, root_dir, **kwargs):
    return tool.execute({
        "operation": operation,
        "project_id": project_id,
        "root_dir": str(root_dir),
        **kwargs,
    })


def initialize(tool, tmp_path, artifacts):
    result = execute(
        tool,
        "init",
        "public-finalize",
        tmp_path,
        title="Public Finalize Contract",
        planning_artifacts=artifacts,
    )
    assert result.success, result.error
    return Path(result.data["project_dir"])


def make_clip(path, color):
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:s={PROFILE.width}x{PROFILE.height}:d=1:r={PROFILE.fps}",
            "-c:v", PROFILE.codec,
            "-pix_fmt", PROFILE.pixel_format,
            "-an",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def accept_two_shots(tool, project_dir, artifacts):
    for shot, color in zip(artifacts["shot_plan"]["shots"], ("red", "blue")):
        shot_id = shot["id"]
        bound = execute(
            tool,
            "bind_input",
            project_dir.name,
            project_dir.parent,
            shot_id=shot_id,
            prompt=f"Generate {shot_id}",
            references=[],
        )
        assert bound.success, bound.error
        revision = bound.data["shot"]["revision"]
        input_hash = bound.data["shot"]["bound_input"]["input_hash"]

        clip_path = project_dir / f"{shot_id}.mp4"
        make_clip(clip_path, color)
        content_hash = _file_hash(clip_path)
        probe = probe_clip(str(clip_path))
        validation = {
            **probe,
            "valid": True,
            "input_hash": input_hash,
            "content_hash": content_hash,
        }
        recorded = execute(
            tool,
            "record_result",
            project_dir.name,
            project_dir.parent,
            shot_id=shot_id,
            revision=revision,
            outcome={
                "status": "completed",
                "file_path": str(clip_path),
                "content_hash": content_hash,
                "input_hash": input_hash,
                "validation": validation,
            },
        )
        assert recorded.success, recorded.error
        assert recorded.data["shot"]["status"] == "GENERATED"

        reviewed = execute(
            tool,
            "review",
            project_dir.name,
            project_dir.parent,
            shot_id=shot_id,
            revision=revision,
            accepted=True,
            end_state=shot["end_state"],
            reviewer="contract-tester",
            notes="Accepted in planned order.",
        )
        assert reviewed.success, reviewed.error
        assert reviewed.data["shot"]["status"] == "ACCEPTED"


def test_finalize_rejects_missing_and_malformed_profile(tmp_path, mochi_two_shot):
    for profile in (None, {"name": "incomplete"}):
        tool = new_tool()
        project_dir = initialize(tool, tmp_path / ("missing" if profile is None else "malformed"), mochi_two_shot)
        inputs = {}
        if profile is not None:
            inputs["profile"] = profile
        result = execute(
            tool,
            "finalize",
            project_dir.name,
            project_dir.parent,
            **inputs,
        )
        assert result.success is False
        assert "profile" in result.error


def test_completion_and_compose_block_without_final_evidence(tmp_path, mochi_two_shot):
    tool = new_tool()
    project_dir = initialize(tool, tmp_path, mochi_two_shot)

    completion = execute(
        tool,
        "validate_completion",
        project_dir.name,
        project_dir.parent,
    )
    assert completion.success is False
    assert completion.data == {"valid": False, "reason": "No final_evidence present"}

    compose = execute(
        tool,
        "checkpoint",
        project_dir.name,
        project_dir.parent,
        stage="compose",
        artifacts={},
    )
    assert compose.success is False
    assert "Cannot complete compose" in compose.error


def test_public_finalize_survives_fresh_tool_and_rejects_mutated_final(
    tmp_path, mochi_two_shot
):
    tool = new_tool()
    project_dir = initialize(tool, tmp_path, mochi_two_shot)
    accept_two_shots(tool, project_dir, mochi_two_shot)

    finalized = execute(
        tool,
        "finalize",
        project_dir.name,
        project_dir.parent,
        profile=profile_payload(),
    )
    assert finalized.success, finalized.error
    final_path = Path(finalized.data["final_path"])
    report_path = project_dir / "reports" / "render_report.json"
    final_review_path = project_dir / "reports" / "final_review.json"
    assert final_path.is_file()
    assert report_path.is_file()
    assert final_review_path.is_file()
    assert str(final_path) in finalized.artifacts
    assert str(report_path) in finalized.artifacts
    assert str(final_review_path) in finalized.artifacts

    fresh_completion = execute(
        new_tool(),
        "validate_completion",
        project_dir.name,
        project_dir.parent,
    )
    assert fresh_completion.success is True
    assert fresh_completion.data == {"valid": True, "reason": "Pass"}

    final_review = json.loads(final_review_path.read_text())
    final_review["status"] = "fail"
    final_review["issues_found"] = ["regression sentinel"]
    final_review_path.write_text(json.dumps(final_review))

    invalid_review_completion = execute(
        new_tool(),
        "validate_completion",
        project_dir.name,
        project_dir.parent,
    )
    assert invalid_review_completion.success is False
    assert invalid_review_completion.data["valid"] is False
    assert "Final review failed" in invalid_review_completion.data["reason"]

    final_review["status"] = "pass"
    final_review["issues_found"] = []
    final_review_path.write_text(json.dumps(final_review))

    final_path.write_bytes(final_path.read_bytes() + b"mutated")

    invalid_completion = execute(
        new_tool(),
        "validate_completion",
        project_dir.name,
        project_dir.parent,
    )
    assert invalid_completion.success is False
    assert invalid_completion.data["valid"] is False
    assert "tampered" in invalid_completion.error

    rejected_compose = execute(
        new_tool(),
        "checkpoint",
        project_dir.name,
        project_dir.parent,
        stage="compose",
        artifacts={},
    )
    assert rejected_compose.success is False
    assert "Cannot complete compose" in rejected_compose.error
