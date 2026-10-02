"""Test init_codex_profile.sh script behaviors."""

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "init_codex_profile.sh"


def _get_current_user():
    """Get current user name for ownership tests."""
    result = subprocess.run(
        ["id", "-u", "-n"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def _run_init_script(
    tmp_path: Path,
    source_dir: Path,
    target_dir: Path,
    *,
    refresh: bool = False,
    target_user: str = None,
):
    """Run init_codex_profile.sh with given directories."""
    env = os.environ.copy()
    if refresh:
        env["REFRESH_CODEX_PROFILE"] = "1"

    args = [str(SCRIPT), str(source_dir), str(target_dir)]
    if target_user:
        args.append(target_user)

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def test_atomic_replacement_validation_failure_preserves_target(tmp_path: Path):
    """If validation fails mid-copy, existing target stays intact."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    # Create valid target
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("model_provider = 'openai'\n")

    # Create invalid source (missing OPENAI_API_KEY)
    (source / "auth.json").write_text(json.dumps({"OTHER_KEY": "value"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target, refresh=True)

    assert result.returncode == 1
    assert "missing or invalid OPENAI_API_KEY" in result.stderr
    # Target should be unchanged
    assert (target / "auth.json").exists()
    original = json.loads((target / "auth.json").read_text())
    assert original["OPENAI_API_KEY"] == "sk-original"


def test_json_validation_requires_valid_json(tmp_path: Path):
    """Source auth.json must be valid JSON."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text("not valid json {")
    (source / "config.toml").write_text("model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "Invalid JSON" in result.stderr


def test_json_validation_requires_openai_api_key(tmp_path: Path):
    """Source auth.json must contain OPENAI_API_KEY."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OTHER_KEY": "value"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "missing or invalid OPENAI_API_KEY" in result.stderr


def test_toml_commented_model_provider_rejected(tmp_path: Path):
    """Source config.toml with model_provider commented out is rejected."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("# model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "model_provider" in result.stderr


def test_toml_validation_requires_model_provider(tmp_path: Path):
    """Source config.toml must contain model_provider."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("other_config = 'value'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "model_provider" in result.stderr


def test_idempotent_validates_existing_target_config_toml(tmp_path: Path):
    """Idempotent check validates existing target config.toml has model_provider."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-new"}))
    (source / "config.toml").write_text("model_provider = 'new'\n")

    # Target has valid auth.json but commented-out model_provider in config.toml
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("# model_provider = 'original'\n")

    result = _run_init_script(tmp_path, source, target, refresh=False)

    assert result.returncode == 1
    assert "Existing target profile is invalid" in result.stderr


def test_idempotent_skip_when_target_valid(tmp_path: Path):
    """If target already has valid auth.json and REFRESH not set, skip."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-new"}))
    (source / "config.toml").write_text("model_provider = 'new'\n")

    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("model_provider = 'original'\n")

    result = _run_init_script(tmp_path, source, target, refresh=False)

    assert result.returncode == 0
    # Target should be unchanged
    original = json.loads((target / "auth.json").read_text())
    assert original["OPENAI_API_KEY"] == "sk-original"
    assert "original" in (target / "config.toml").read_text()


def test_force_refresh_overwrites_valid_target(tmp_path: Path):
    """REFRESH_CODEX_PROFILE=1 forces replacement."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-new"}))
    (source / "config.toml").write_text("model_provider = 'new'\n")

    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("model_provider = 'original'\n")

    result = _run_init_script(tmp_path, source, target, refresh=True)

    assert result.returncode == 0
    assert "SUCCESS" in result.stdout
    # Target should be updated
    new = json.loads((target / "auth.json").read_text())
    assert new["OPENAI_API_KEY"] == "sk-new"
    assert "new" in (target / "config.toml").read_text()


def test_permissions_target_dir_700(tmp_path: Path):
    """After successful init, target dir is mode 700."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    assert target.exists()
    # Check directory permissions (0o700)
    stat_info = target.stat()
    mode = stat_info.st_mode & 0o777
    assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"


def test_permissions_files_600(tmp_path: Path):
    """After successful init, files are mode 600."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    # Check file permissions (0o600)
    for filename in ["auth.json", "config.toml"]:
        file_path = target / filename
        assert file_path.exists()
        stat_info = file_path.stat()
        mode = stat_info.st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600 for {filename}, got {oct(mode)}"


def test_user_ownership_uses_current_user(tmp_path: Path):
    """When target user is current user, files are owned by current user."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")

    current_user = _get_current_user()
    result = _run_init_script(tmp_path, source, target, target_user=current_user)

    assert result.returncode == 0
    assert f"user {current_user}" in result.stdout
    # Verify files exist and are accessible
    assert (target / "auth.json").exists()
    assert (target / "config.toml").exists()


def test_no_source_exits_silently(tmp_path: Path):
    """If source dir doesn't exist and no target exists, script fails visibly."""
    source = tmp_path / "nonexistent_source"
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "lacks auth.json/config.toml and no valid target exists" in result.stderr
    assert not target.exists()


def test_no_auth_json_exits_silently(tmp_path: Path):
    """If source has no auth.json and no target exists, script fails visibly."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    # Create only config.toml, no auth.json
    (source / "config.toml").write_text("model_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "lacks auth.json/config.toml and no valid target exists" in result.stderr
    assert not target.exists()


def test_redacted_errors_no_key_leakage(tmp_path: Path):
    """Error output must never echo the value of OPENAI_API_KEY."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    secret_key = "sk-secret-should-not-appear-in-output-12345"
    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": secret_key}))
    # Missing model_provider to trigger error
    (source / "config.toml").write_text("other_config = 'value'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    # Verify the secret does not appear in stdout or stderr
    assert secret_key not in result.stdout
    assert secret_key not in result.stderr
    # Verify error message is present
    assert "model_provider" in result.stderr


def test_successful_initialization_copies_all_files(tmp_path: Path):
    """Successful init copies auth.json, config.toml, and optional files."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")
    (source / "version.json").write_text('{"version": "1.0"}')
    (source / "models_cache.json").write_text('{"models": []}')

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    assert "SUCCESS" in result.stdout
    assert (target / "auth.json").exists()
    assert (target / "config.toml").exists()
    assert (target / "version.json").exists()
    assert (target / "models_cache.json").exists()


def test_idempotent_validates_existing_target(tmp_path: Path):
    """Idempotent check validates existing target has OPENAI_API_KEY."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-new"}))
    (source / "config.toml").write_text("model_provider = 'new'\n")

    # Create invalid target (missing OPENAI_API_KEY)
    (target / "auth.json").write_text(json.dumps({"OTHER_KEY": "value"}))

    result = _run_init_script(tmp_path, source, target, refresh=False)

    assert result.returncode == 1
    assert "Existing target profile is invalid" in result.stderr


def test_atomic_swap_preserves_target_on_activation_failure(tmp_path: Path):
    """If activation mv fails, trap clears staging and target remains valid."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    bin_dir = tmp_path / "bin"
    source.mkdir()
    target.mkdir()
    bin_dir.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-new"}))
    (source / "config.toml").write_text("model_provider = 'new'\n")

    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("model_provider = 'original'\n")

    mock_mv = bin_dir / "mv"
    mock_mv.write_text(
        "#!/usr/bin/env bash\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$arg\" == *\".staging_\"* ]]; then\n"
        "    echo 'MOCK MV ACTIVATION FAILURE' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "done\n"
        "exec /bin/mv \"$@\"\n"
    )
    mock_mv.chmod(0o755)

    import os, subprocess
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["REFRESH_CODEX_PROFILE"] = "1"

    result = subprocess.run(
        [str(SCRIPT), str(source), str(target)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    assert result.returncode == 1
    assert "MOCK MV ACTIVATION FAILURE" in result.stderr
    assert target.exists()
    assert (target / "auth.json").exists()
    # The original active auth.json remains exactly as it was, no files deleted.
    original = json.loads((target / "auth.json").read_text())
    assert original["OPENAI_API_KEY"] == "sk-original"


def test_toml_unrelated_model_provider_rejected(tmp_path: Path):
    """Source config.toml with model_provider only in a subtable is rejected."""
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()

    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    (source / "config.toml").write_text("[unrelated]\nmodel_provider = 'test'\n")

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "config.toml missing model_provider" in result.stderr

def test_missing_source_fails_visibly_when_no_target_exists(tmp_path: Path):
    """Missing source and missing target must fail visibly."""
    source = tmp_path / "missing_source"
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 1
    assert "lacks auth.json/config.toml and no valid target exists" in result.stderr
