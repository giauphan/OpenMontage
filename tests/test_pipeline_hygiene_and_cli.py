"""Tests ensuring sanitization of environment paths, permissions, and CLI exit codes."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPT = ROOT / "scripts" / "run_daily_news_pipeline.sh"
VALIDATION_SCRIPT = ROOT / "scripts" / "codex_agent_validation.py"


def test_orchestrator_and_selector_scripts_have_no_hardcoded_nvm_paths():
    for rel_path in (
        "scripts/run_strict_docker_publish.sh",
        "scripts/run_daily_news_pipeline.sh",
        "scripts/run_directors_for_existing.sh",
        "scripts/codex_agent_validation.py",
        "lib/codex_news_selector.py",
    ):
        path = ROOT / rel_path
        content = path.read_text(encoding="utf-8")
        assert "/home/ubuntu/.nvm" not in content, f"Found hardcoded /home/ubuntu/.nvm path in {rel_path}"


def test_codex_validation_cli_exits_2_on_missing_project(tmp_path: Path):
    nonexistent = tmp_path / "nonexistent_project"
    result = subprocess.run(
        [sys.executable, str(VALIDATION_SCRIPT), str(nonexistent)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, f"Expected exit code 2 for missing project, got {result.returncode}"


def test_codex_validation_cli_exits_2_on_deterministic_contract_failure(tmp_path: Path):
    project_dir = tmp_path / "cand_broken"
    project_dir.mkdir()
    # Missing video files in renders/ and missing publish_metadata.json
    result = subprocess.run(
        [sys.executable, str(VALIDATION_SCRIPT), str(project_dir), "--strict"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, f"Expected exit code 2 on deterministic check failure, got {result.returncode}"
    assert "FAIL" in result.stdout or "VALIDATION FAILED" in result.stdout


def test_daily_pipeline_does_not_chmod_entire_repo():
    content = PIPELINE_SCRIPT.read_text(encoding="utf-8")
    assert "chmod -R 777 ." not in content
    assert 'chmod 777 "$ROOT"' not in content


def test_dockerfile_configures_entrypoint_and_copies_script():
    dockerfile = ROOT / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")
    assert "COPY docker/entrypoint.sh /entrypoint.sh" in content
    assert 'ENTRYPOINT ["/entrypoint.sh"]' in content


def test_docker_compose_uses_entrypoint_without_redundant_profile_init():
    compose = ROOT / "docker-compose.yml"
    content = compose.read_text(encoding="utf-8")
    assert "init_codex_profile.sh" not in content


def test_docker_md_documents_codex_and_mount_structure():
    doc = ROOT / "docs" / "DOCKER.md"
    content = doc.read_text(encoding="utf-8")
    assert "codex" in content
    assert "~/.codex" in content
    assert "auth.json" in content


def test_publish_active_projects_supports_include_overdue_flag():
    pub_script = ROOT / "scripts" / "publish_active_projects.py"
    result = subprocess.run(
        [sys.executable, str(pub_script), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "--include-overdue" in result.stdout


