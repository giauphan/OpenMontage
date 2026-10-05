"""Multi-shot pipeline manifest contract tests (M0).

Ensures the multi-shot manifest loads, validates, and is discoverable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.pipeline_loader import (
    load_pipeline,
    list_pipelines,
    get_stage_order,
    get_stage_skill,
    get_stage_review_focus,
    get_required_tools,
)


class TestMultishotManifest:
    def test_manifest_loads(self):
        manifest = load_pipeline("multi-shot")
        assert manifest["name"] == "multi-shot"
        assert manifest["version"] == "1.0"
        assert manifest["category"] == "generated"
        assert manifest["stability"] == "beta"

    def test_manifest_listed(self):
        assert "multi-shot" in list_pipelines()

    def test_stages_defined(self):
        manifest = load_pipeline("multi-shot")
        stages = get_stage_order(manifest)
        expected = ["idea", "story", "identity", "shot_plan",
                    "planning", "assets", "edit", "compose"]
        assert stages == expected

    def test_stages_have_skills(self):
        manifest = load_pipeline("multi-shot")
        for stage in manifest["stages"]:
            skill = get_stage_skill(manifest, stage["name"])
            assert skill is not None, f"Stage {stage['name']} missing skill"
            assert isinstance(skill, str) and len(skill) > 0

    def test_stages_have_review_focus(self):
        manifest = load_pipeline("multi-shot")
        for stage in manifest["stages"]:
            focus = get_stage_review_focus(manifest, stage["name"])
            assert isinstance(focus, list)

    def test_first_stage_no_required_artifacts(self):
        manifest = load_pipeline("multi-shot")
        first = manifest["stages"][0]
        assert first["name"] == "idea"
        assert "required_artifacts_in" not in first or not first.get("required_artifacts_in")

    def test_last_stage_produces_render_report(self):
        manifest = load_pipeline("multi-shot")
        last = manifest["stages"][-1]
        assert last["name"] == "compose"
        assert "render_report" in last["produces"]

    def test_human_approval_on_key_stages(self):
        manifest = load_pipeline("multi-shot")
        approval_required = {"story", "identity", "shot_plan", "planning",
                             "assets", "edit", "compose"}
        for stage in manifest["stages"]:
            if stage["name"] in approval_required:
                assert stage.get("human_approval_default", False) is True, (
                    f"Stage {stage['name']} should require human approval"
                )
            else:
                assert stage.get("human_approval_default", False) is False
