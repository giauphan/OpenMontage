"""Contract test for pipeline reference integrity and manifest loading.

Verifies that all pipeline definitions load, validate against JSON schema,
and reference valid skills and tools.
"""

from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from lib.pipeline_loader import load_pipeline, load_pipeline_readonly, PIPELINE_DEFS_DIR
from tools.tool_registry import ToolRegistry


class TestPipelineReferenceIntegrity:
    """Verifies pipeline definitions and referenced skills."""

    @classmethod
    def setup_class(cls):
        cls.tool_registry = ToolRegistry()
        cls.tool_registry.discover()

    def test_all_manifests_parse_yaml(self):
        """Every YAML file in pipeline_defs/ must parse without YAML syntax errors."""
        yaml_files = list(PIPELINE_DEFS_DIR.glob("*.yaml"))
        assert len(yaml_files) >= 10, f"Expected at least 10 pipeline manifests, found {len(yaml_files)}"

        for yf in yaml_files:
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            assert isinstance(data, dict), f"Failed parsing {yf.name}"
            assert "name" in data
            assert "stages" in data

    def test_standard_manifests_validate_against_schema(self):
        """Standard manifests must validate cleanly via pipeline_loader.load_pipeline."""
        # Note: screen-demo.yaml contains extra 'production_modes' which is tracked as a legacy schema variance.
        standard_manifests = [
            "animated-explainer",
            "talking-head",
            "clip-factory",
            "podcast-repurpose",
            "cinematic",
            "animation",
            "character-animation",
            "hybrid",
            "avatar-spokesperson",
            "localization-dub",
            "framework-smoke",
            "documentary-montage",
            "multi-shot",
        ]
        for name in standard_manifests:
            if (PIPELINE_DEFS_DIR / f"{name}.yaml").is_file():
                manifest = load_pipeline(name)
                assert manifest is not None
                assert manifest.get("name") == name

    def test_load_pipeline_readonly_caching(self):
        """load_pipeline_readonly returns the exact cached dictionary."""
        p1 = load_pipeline_readonly("animated-explainer")
        p2 = load_pipeline_readonly("animated-explainer")
        assert p1 is p2

    def test_referenced_skills_and_tools_exist(self):
        """All stage director skills referenced in manifests must exist on disk."""
        repo_root = PIPELINE_DEFS_DIR.parent
        yaml_files = list(PIPELINE_DEFS_DIR.glob("*.yaml"))
        agent_native_tools = {"ffmpeg", "manual_review", "web_search", "browser", "python_interpreter"}

        for yf in yaml_files:
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            stages = data.get("stages", [])
            assert isinstance(stages, list), f"Stages in {yf.name} is not a list"

            for stage in stages:
                stage_name = stage.get("name")
                skill_path_str = stage.get("skill")
                if skill_path_str:
                    # Skill paths may be relative to skills/ or root
                    skill_file = repo_root / "skills" / f"{skill_path_str}.md"
                    if not skill_file.is_file():
                        skill_file = repo_root / f"{skill_path_str}.md"
                    if not skill_file.is_file():
                        skill_file = repo_root / skill_path_str

                    assert skill_file.exists(), (
                        f"Pipeline {yf.stem} stage {stage_name} references missing skill: {skill_path_str}"
                    )

                # Check tools_available
                tools_available = stage.get("tools_available", [])
                for t in tools_available:
                    assert (
                        t in self.tool_registry._tools
                        or t.endswith("_selector")
                        or t in agent_native_tools
                    ), f"Pipeline {yf.stem} stage {stage_name} references unknown tool: {t}"
