"""Unit tests for docker/entrypoint.sh."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


def test_entrypoint_passes_through_commands():
    result = subprocess.run(
        ["bash", str(ENTRYPOINT), "echo", "test-pass-through"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "test-pass-through"


def test_entrypoint_preserves_exit_code():
    result = subprocess.run(
        ["bash", str(ENTRYPOINT), "bash", "-c", "exit 42"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 42


def test_entrypoint_triggers_profile_init_when_source_has_auth(tmp_path: Path):
    source_dir = tmp_path / "codex_source"
    source_dir.mkdir()
    (source_dir / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}), encoding="utf-8")

    mock_init = tmp_path / "mock_init.sh"
    calls_file = tmp_path / "calls.txt"
    mock_init.write_text(
        f"""#!/usr/bin/env bash
echo "$@" >> "{calls_file}"
exit 0
""",
        encoding="utf-8",
    )
    mock_init.chmod(0o755)

    env = {
        **os.environ,
        "OPENMONTAGE_ROOT": str(tmp_path),
        "CODEX_SOURCE_DIR": str(source_dir),
    }
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "init_codex_profile.sh").symlink_to(mock_init)

    result = subprocess.run(
        ["bash", str(ENTRYPOINT), "echo", "done"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "done"
    assert calls_file.is_file()
    lines = calls_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "/root/.codex_pipeline root" in lines[0]
    assert "/home/node/.codex_pipeline node" in lines[1]


def test_entrypoint_skips_init_when_source_lacks_auth(tmp_path: Path):
    empty_source = tmp_path / "empty_codex_source"
    empty_source.mkdir()

    calls_file = tmp_path / "calls.txt"
    mock_init = tmp_path / "mock_init.sh"
    mock_init.write_text(
        f"""#!/usr/bin/env bash
echo "CALLED" >> "{calls_file}"
exit 0
""",
        encoding="utf-8",
    )
    mock_init.chmod(0o755)

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "init_codex_profile.sh").symlink_to(mock_init)

    env = {
        **os.environ,
        "OPENMONTAGE_ROOT": str(tmp_path),
        "CODEX_SOURCE_DIR": str(empty_source),
    }

    result = subprocess.run(
        ["bash", str(ENTRYPOINT), "echo", "done"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert not calls_file.exists()
