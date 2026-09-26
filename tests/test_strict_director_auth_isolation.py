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
