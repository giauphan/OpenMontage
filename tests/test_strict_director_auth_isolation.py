from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_nested_director_uses_codex_exec():
    """Verify directors run via codex exec, not claude CLI."""
    script = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(
        encoding="utf-8"
    )
    codex_launches = [
        line for line in script.splitlines()
        if "CODEX_BIN" in line and "exec" in line and "dangerously" in line
    ]

    assert len(codex_launches) >= 1, "Expected at least one codex exec invocation"
    assert all("--dangerously-bypass-approvals-and-sandbox" in line for line in codex_launches)


def test_no_claude_cli_invocations():
    """Verify no claude --bare -p invocations remain in pipeline."""
    script = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(
        encoding="utf-8"
    )
    claude_launches = [
        line for line in script.splitlines() if "claude --bare -p" in line
    ]

    assert len(claude_launches) == 0, f"Found {len(claude_launches)} claude CLI invocations that should have been removed"


def test_node_user_uses_codex_pipeline_profile():
    """Verify node user subshell uses .codex_pipeline, not .codex."""
    script = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(encoding="utf-8")
    assert (
        'CODEX_HOME="/home/node/.codex_pipeline"' in script
        or "CODEX_HOME='/home/node/.codex_pipeline'" in script
    ), "node user subshell must set CODEX_HOME to /home/node/.codex_pipeline"
    old_path_lines = [
        ln for ln in script.splitlines()
        if "/home/node/.codex\"" in ln and ".codex_pipeline" not in ln
    ]
    assert old_path_lines == [], f"Found stale /home/node/.codex references: {old_path_lines}"


def test_directors_existing_uses_codex_pipeline_profile():
    """Verify run_directors_for_existing also uses .codex_pipeline for node user."""
    script = (ROOT / "scripts" / "run_directors_for_existing.sh").read_text(encoding="utf-8")
    assert (
        'CODEX_HOME="/home/node/.codex_pipeline"' in script
        or "CODEX_HOME='/home/node/.codex_pipeline'" in script
    ), "node user subshell must set CODEX_HOME to /home/node/.codex_pipeline"
    old_path_lines = [
        ln for ln in script.splitlines()
        if "/home/node/.codex\"" in ln and ".codex_pipeline" not in ln
    ]
    assert old_path_lines == [], f"Found stale /home/node/.codex references: {old_path_lines}"


def test_director_invocations_pin_documented_gateway_model():
    script = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(encoding="utf-8")
    launches = [line for line in script.splitlines() if "CODEX_BIN" in line and "exec" in line]
    assert launches
    assert all('--config "model=\\\"$CODEX_MODEL\\\""' in line for line in launches)
    assert 'CODEX_MODEL="${CODEX_MODEL:-gpt-5.6-sol}"' in script


def test_node_user_reads_api_key_from_pipeline_profile():
    """Verify node user shell reads OPENAI_API_KEY from the pipeline profile auth.json."""
    for script_name in ("run_daily_news_pipeline.sh", "run_directors_for_existing.sh"):
        script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        # Key must be read from the profile's auth.json (via $CODEX_HOME/auth.json or literal path)
        assert "OPENAI_API_KEY" in script, \
            f"{script_name}: must set OPENAI_API_KEY"
        # Must reference auth.json from the pipeline profile home
        has_codex_home_auth = "$CODEX_HOME/auth.json" in script and ".codex_pipeline" in script
        has_literal_auth = ".codex_pipeline/auth.json" in script
        assert has_codex_home_auth or has_literal_auth, \
            f"{script_name}: node user must read OPENAI_API_KEY from .codex_pipeline auth.json (via $CODEX_HOME or literal path)"
        bad_su_lines = [
            ln for ln in script.splitlines()
            if "su node" in ln and "OPENAI_API_KEY=" in ln
        ]
        assert bad_su_lines == [], \
            f"{script_name}: OPENAI_API_KEY must not be passed directly as su env prefix: {bad_su_lines}"

