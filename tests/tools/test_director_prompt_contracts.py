from pathlib import Path

def get_root():
    if Path("/app").is_dir() and (Path("/app") / "scripts").is_dir():
        return Path("/app")
    return Path(__file__).resolve().parents[2]

def test_director_prompts_are_tracked_and_valid():
    """Server director prompts must be tracked in git and follow execution rules."""
    root = get_root()
    prompts_dir = root / "scripts" / "prompts"

    # 1. Must exist
    templates = [
        "director_system.prompt.md",
        "director_generate.prompt.md",
        "director_retry.prompt.md",
    ]
    for name in templates:
        path = prompts_dir / name
        assert path.exists(), f"Missing required prompt template: {name}"
        content = path.read_text(encoding="utf-8")
        assert len(content.strip()) > 0, f"Prompt template {name} is empty"

        # 2. Must not contain conflicting SSH execute instructions
        assert "`ssh" not in content and "\nssh " not in content, f"{name} contains SSH execute instructions which break containers"

        # 3. Must not attempt to invoke shell wrappers
        assert "run_daily_news_pipeline.sh" not in content, f"{name} instructs agent to run pipeline wrappers"

        # 4. Must require the exact placeholder
        assert "{{PROJECT_DIR}}" in content, f"{name} missing {{{{PROJECT_DIR}}}} placeholder"

        # 5. Must forbid visible brand names in narration/text
        if name in ["director_system.prompt.md", "director_generate.prompt.md"]:
            assert "OpenMontage" in content or "Montage" in content, f"{name} should explicitly mention forbidden branding"

def test_director_prompt_interpolation():
    """Ensure template interpolation replaces {{PROJECT_DIR}} completely."""
    root = get_root()
    prompts_dir = root / "scripts" / "prompts"
    dummy_dir = "/app/projects/cand_test123"

    for name in ["director_system.prompt.md", "director_generate.prompt.md", "director_retry.prompt.md"]:
        path = prompts_dir / name
        content = path.read_text(encoding="utf-8")
        rendered = content.replace("{{PROJECT_DIR}}", dummy_dir)
        assert "{{PROJECT_DIR}}" not in rendered
        assert dummy_dir in rendered

def test_scripts_prevent_recursive_invocation():
    """Regression: ensure we don't hit infinite loop from bad prompt instructions."""
    root = get_root()
    system_prompt = root / "scripts" / "prompts" / "director_system.prompt.md"
    if system_prompt.exists():
        content = system_prompt.read_text(encoding="utf-8")
        assert "run_daily_news_pipeline.sh" not in content, "System prompt instructs agent to run shell loop"
        assert "run_directors" not in content, "System prompt instructs agent to invoke directors recursively"
        assert "Do not publish" in content or "not publish" in content
