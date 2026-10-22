"""Contract test verifying en-US director prompt assets and pipeline wiring."""
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_en_us_director_prompt_files_exist():
    prompt_dir = REPO_ROOT / "scripts" / "prompts"
    required_prompts = [
        "director_generate_en_US.prompt.md",
        "director_system_en_US.prompt.md",
        "director_templated_generate_en_US.prompt.md",
        "director_templated_system_en_US.prompt.md",
    ]
    for filename in required_prompts:
        path = prompt_dir / filename
        assert path.is_file(), f"Missing required prompt file: {filename}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100
        assert "en-US" in content or "American" in content or "script_en_US.json" in content


def test_run_daily_news_pipeline_branches_on_is_en():
    script_path = REPO_ROOT / "scripts" / "run_daily_news_pipeline.sh"
    assert script_path.is_file()
    content = script_path.read_text(encoding="utf-8")
    assert 'director_generate_en_US.prompt.md' in content
    assert 'director_system_en_US.prompt.md' in content
    assert 'validate_display_language.py' in content


def test_pipeline_defs_include_cultural_skills():
    pipeline_dir = REPO_ROOT / "pipeline_defs"
    explainer = (pipeline_dir / "animated-explainer.yaml").read_text(encoding="utf-8")
    assert "meta/cultural-localization-en-us" in explainer
    assert "meta/claim-bound-visual-director" in explainer
    assert "meta/audience-and-culture-us" in explainer
    assert "meta/factcheck-and-claim-ledger" in explainer

    dub = (pipeline_dir / "localization-dub.yaml").read_text(encoding="utf-8")
    assert "meta/cultural-localization-en-us" in dub
    assert "meta/audience-and-culture-us" in dub

