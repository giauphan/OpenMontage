"""Public workspace/checkpoint integration and recovery regression tests."""
import copy
import json

import pytest

from lib.checkpoint import (
    CheckpointValidationError, get_next_stage, read_checkpoint, write_checkpoint,
)
from lib.multishot_workspace import init_multishot_project
from lib.pipeline_loader import load_pipeline_readonly

BRIEF = {
    "version": "1.0", "title": "Test", "hook": "A beginning",
    "key_points": ["A story"], "tone": "playful", "style": "custom",
    "target_platform": "generic", "target_duration_seconds": 10,
}
REQUEST = {
    "topic": "Test", "aspect_ratio": "16:9",
    "resolution": {"width": 640, "height": 360}, "fps": 24,
    "shot_policy": {"min_shots": 2, "max_shots": 4},
}
STORY = {
    "version": "1.0", "title": "Test", "topic": "Test",
    "beats": [
        {"id": f"beat_{i:02d}", "type": kind, "summary": kind}
        for i, kind in enumerate(("hook", "escalation", "climax", "resolution"), 1)
    ],
}


def test_manifest_outputs_work_through_public_checkpoint(tmp_path):
    project = init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    outputs = load_pipeline_readonly("multi-shot")["stages"][0]["produces"]
    payloads = {"brief": BRIEF, "request": REQUEST}
    write_checkpoint(tmp_path, project.name, "idea", "completed",
                     {name: payloads[name] for name in outputs})
    cp = read_checkpoint(tmp_path, project.name, "idea")
    assert cp["artifacts"] == payloads
    assert cp["pipeline_type"] == "multi-shot"
    assert get_next_stage(tmp_path, project.name, "multi-shot") == "story"


def test_legacy_request_only_mismatch_still_rejected(tmp_path):
    init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="canonical artifact 'brief'"):
        write_checkpoint(tmp_path, "recovery", "idea", "completed", {"request": REQUEST})


def test_custom_schema_validation_on_write_and_reload(tmp_path):
    project = init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="request"):
        write_checkpoint(tmp_path, project.name, "idea", "completed",
                         {"brief": BRIEF, "request": {}})
    path = write_checkpoint(tmp_path, project.name, "idea", "completed",
                            {"brief": BRIEF, "request": REQUEST})
    data = json.loads(path.read_text())
    data["artifacts"]["request"] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(CheckpointValidationError, match="request"):
        read_checkpoint(tmp_path, project.name, "idea")


def test_approval_prerequisites_and_history_preserved(tmp_path):
    project = init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    write_checkpoint(tmp_path, project.name, "idea", "completed",
                     {"brief": BRIEF, "request": REQUEST})
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(tmp_path, project.name, "story", "completed", {"story": STORY})
    write_checkpoint(tmp_path, project.name, "story", "awaiting_human", {"story": STORY})
    with pytest.raises(CheckpointValidationError, match="PREREQUISITE"):
        write_checkpoint(tmp_path, project.name, "identity", "awaiting_human", {})
    write_checkpoint(tmp_path, project.name, "story", "completed", {"story": STORY},
                     human_approved=True)
    before = read_checkpoint(tmp_path, project.name, "story")
    marker = (project / "project.json").read_bytes()
    init_multishot_project(project.name, title="Do not rename", pipeline_dir=tmp_path)
    assert read_checkpoint(tmp_path, project.name, "story") == before
    assert (project / "project.json").read_bytes() == marker
    assert list((project / "history").rglob("*.json"))


def test_custom_required_output_and_unknown_record_fail_closed(tmp_path):
    init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    write_checkpoint(tmp_path, "recovery", "idea", "completed", {"brief": BRIEF, "request": REQUEST})
    with pytest.raises(CheckpointValidationError, match="story"):
        write_checkpoint(tmp_path, "recovery", "story", "awaiting_human", {})
    with pytest.raises(CheckpointValidationError, match="Unknown artifact"):
        write_checkpoint(tmp_path, "recovery", "idea", "in_progress", {"requset": REQUEST})


@pytest.mark.parametrize("name", ["request", "story", "character_bible", "style_bible", "shot_plan", "continuity_state", "job", "run_manifest"])
def test_every_supporting_record_registered_and_validated(tmp_path, name):
    from schemas.artifacts import ARTIFACT_NAMES, list_schemas, load_schema
    assert name in ARTIFACT_NAMES
    assert name in list_schemas()
    assert load_schema(name)["type"] == "object"
    init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match=name):
        write_checkpoint(tmp_path, "recovery", "idea", "in_progress", {name: {}})


def test_explicit_pipeline_override_cannot_bypass_marker(tmp_path):
    init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="identity mismatch"):
        write_checkpoint(tmp_path, "recovery", "idea", "completed", {"brief": BRIEF},
                         pipeline_type="unknown")


def test_request_cross_field_rejection(tmp_path):
    init_multishot_project("recovery", title="Recovery", pipeline_dir=tmp_path)
    request = copy.deepcopy(REQUEST)
    request["shot_policy"] = {"min_shots": 4, "max_shots": 2}
    with pytest.raises(CheckpointValidationError):
        write_checkpoint(tmp_path, "recovery", "idea", "completed", {"brief": BRIEF, "request": request})
