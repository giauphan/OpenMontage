"""Tests for init_codex_profile.sh (reader-consistent symlink activation + strict validation)."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "init_codex_profile.sh"


def _get_current_user():
    result = subprocess.run(["id", "-u", "-n"], capture_output=True, text=True, timeout=5)
    return result.stdout.strip()


def _run_init_script(
    tmp_path: Path,
    source_dir: Path,
    target_dir: Path,
    *,
    refresh: bool = False,
    target_user: str = None,
    env_extra: dict = None,
):
    env = os.environ.copy()
    if refresh:
        env["REFRESH_CODEX_PROFILE"] = "1"
    if env_extra:
        env.update(env_extra)

    args = [str(SCRIPT), str(source_dir), str(target_dir)]
    if target_user:
        args.append(target_user)

    return subprocess.run(args, capture_output=True, text=True, timeout=30, env=env)


def _make_source(tmp_path: Path, name: str, key: str, config: str = "model_provider = 'openai'\n", extra: dict = None):
    src = tmp_path / name
    src.mkdir()
    (src / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": key}))
    (src / "config.toml").write_text(config)
    if extra:
        for fn, body in extra.items():
            (src / fn).write_text(body)
    return src


# ---------------------------------------------------------------------------
# Reader-consistent activation (symlink model)
# ---------------------------------------------------------------------------

def test_target_becomes_symlink_to_generation_dir(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-first")
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    assert target.is_symlink(), "TARGET_DIR should be a symlink to a versioned generation"
    assert target.resolve().is_dir(), "Symlink must resolve to a valid directory"
    # The live generation holds the files.
    assert (target / "auth.json").is_file()
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-first"


def test_reader_steady_state_observes_no_missing_window(tmp_path: Path):
    """A concurrent reader must never observe an absent dir or mixed-generation
    files during a refresh. This is the exact defect reproduced with the old
    two-directory-move activation (reader saw 89 'MISSING' samples)."""
    target = tmp_path / "target"
    src1 = _make_source(tmp_path, "src1", "sk-v1")
    r0 = _run_init_script(tmp_path, src1, target)
    assert r0.returncode == 0

    src2 = _make_source(tmp_path, "src2", "sk-v2")

    anomalies = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            if not target.is_dir():
                anomalies.append("MISSING")
            elif not (target / "auth.json").is_file() or not (target / "config.toml").is_file():
                anomalies.append("INCONSISTENT")

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    r1 = _run_init_script(tmp_path, src2, target, refresh=True)
    stop.set()
    t.join(timeout=5)

    assert r1.returncode == 0
    assert not anomalies, f"reader observed anomalies during refresh: {set(anomalies)}"
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-v2"


def test_first_time_initialization_creates_generation_atomically(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-first")
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    assert "SUCCESS" in result.stdout
    assert target.is_symlink()
    assert (target / "auth.json").is_file()
    assert (target / "config.toml").is_file()
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-first"


def test_successful_refresh_retains_recent_generations(tmp_path: Path):
    """Successful refresh is lifetime-aware, not count-based: every recent (non-
    aged-out) generation is retained regardless of how many refreshes occur, so a
    long-running reader's held generation is never pruned. 7 refreshes spaced in
    seconds therefore leave all 7 intact (none exceeds the 72h horizon)."""
    target = tmp_path / "target"
    store = tmp_path / "target.store"

    # First init + 6 more refreshes => 7 total generations.
    for i in range(7):
        key = f"sk-v{i + 1}"
        src = _make_source(tmp_path, f"src_{key}", key)
        if i == 0:
            r = _run_init_script(tmp_path, src, target)
        else:
            r = _run_init_script(tmp_path, src, target, refresh=True)
        assert r.returncode == 0, r.stderr

    remaining = []
    for d in sorted(store.iterdir()):
        if d.is_dir() and (d / "auth.json").is_file():
            remaining.append(json.loads((d / "auth.json").read_text())["OPENAI_API_KEY"])
    # Age-gated pruning retains all recent generations; only aged-out ones go.
    for i in range(1, 8):
        assert f"sk-v{i}" in remaining, f"expected sk-v{i} retained (not aged out): {remaining}"
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-v7"


def test_reader_holds_generation_across_more_than_five_refreshes(tmp_path: Path):
    """Regression for the fixed-count defect: a reader that resolved the live
    generation must still find that generation present after MORE than five
    further refreshes (a count-5 prune would have deleted it)."""
    target = tmp_path / "target"

    src0 = _make_source(tmp_path, "src_reader", "sk-reader")
    assert _run_init_script(tmp_path, src0, target).returncode == 0
    # The reader pins the current live generation path (what a real consumer does
    # at process start via home_path.resolve()).
    held = target.resolve()
    assert held.is_dir() and (held / "auth.json").is_file()

    for i in range(6):
        key = f"sk-{i + 1}"
        src = _make_source(tmp_path, f"src_{key}", key)
        r = _run_init_script(tmp_path, src, target, refresh=True)
        assert r.returncode == 0, r.stderr

    # The generation the reader pinned must not have been removed.
    assert held.exists(), f"reader-held generation {held} was pruned despite being live at read time"


def test_prune_is_age_gated_not_count_gated(tmp_path: Path):
    """Generations older than the retention horizon are pruned; recent ones are
    kept. Backdate the oldest two gens past a 1-hour horizon and verify only
    they are removed."""
    target = tmp_path / "target"
    store = tmp_path / "target.store"

    for i in range(3):
        key = f"sk-age{i + 1}"
        src = _make_source(tmp_path, f"src_{key}", key)
        r = _run_init_script(
            tmp_path, src, target,
            refresh=(i > 0),
            env_extra={"CODEX_PROFILE_RETENTION_HOURS": "1"},
        )
        assert r.returncode == 0, r.stderr

    # Backdate the two oldest generations beyond the 1-hour horizon.
    gens = sorted(d for d in store.iterdir() if d.is_dir() and d.name.startswith("gen_"))
    for d in gens[:2]:
        old = __import__("time").time() - (2 * 3600)
        os.utime(d, (old, old))

    # A further refresh (horizon still 1h) must prune only the backdated gens.
    src = _make_source(tmp_path, "src_age4", "sk-age4")
    r = _run_init_script(tmp_path, src, target, refresh=True, env_extra={"CODEX_PROFILE_RETENTION_HOURS": "1"})
    assert r.returncode == 0, r.stderr

    remaining = []
    for d in sorted(store.iterdir()):
        if d.is_dir() and (d / "auth.json").is_file():
            remaining.append(json.loads((d / "auth.json").read_text())["OPENAI_API_KEY"])
    assert "sk-age4" in remaining
    assert "sk-age3" in remaining, f"recent gen pruned by age gate: {remaining}"
    assert "sk-age1" not in remaining, f"aged-out gen sk-age1 should be pruned: {remaining}"
    assert "sk-age2" not in remaining, f"aged-out gen sk-age2 should be pruned: {remaining}"



def test_activation_failure_preserves_previous_generation(tmp_path: Path):
    """If the publish rename fails, the live generation stays intact and the
    unpublished generation is cleaned up (recovery data is never lost)."""
    target = tmp_path / "target"
    src1 = _make_source(tmp_path, "src1", "sk-v1")
    assert _run_init_script(tmp_path, src1, target).returncode == 0

    src2 = _make_source(tmp_path, "src2", "sk-v2")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock_mv = bin_dir / "mv"
    mock_mv.write_text(
        "#!/usr/bin/env bash\n"
        "for a in \"$@\"; do\n"
        "  if [ \"$a\" = \"-T\" ]; then echo 'MOCK PUBLISH FAILURE' >&2; exit 1; fi\n"
        "done\n"
        "exec /bin/mv \"$@\"\n"
    )
    mock_mv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["REFRESH_CODEX_PROFILE"] = "1"
    result = subprocess.run([str(SCRIPT), str(src2), str(target)], capture_output=True, text=True, timeout=30, env=env)

    assert result.returncode == 1
    assert "MOCK PUBLISH FAILURE" in result.stderr
    # The live generation still resolves to the pre-refresh content.
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-v1"
    # The unpublished v2 generation was removed; no gen in the store holds sk-v2.
    for d in (tmp_path / "target.store").iterdir():
        auth = d / "auth.json"
        if d.is_dir() and auth.is_file():
            assert json.loads(auth.read_text())["OPENAI_API_KEY"] != "sk-v2"


def test_legacy_migration_failure_restores_canonical_path(tmp_path: Path):
    """When the legacy real-directory target is migrated away but the publish
    rename fails, the canonical $TARGET_DIR must not be left missing. The
    rollback trap must restore the legacy directory to its original location."""
    target = tmp_path / "target"
    # Create a legacy real-directory target with valid content.
    target.mkdir()
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-legacy"}))
    (target / "config.toml").write_text("model_provider = 'legacy'\n")

    src = _make_source(tmp_path, "src", "sk-v2")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock_mv = bin_dir / "mv"
    mock_mv.write_text(
        "#!/usr/bin/env bash\n"
        "for a in \"$@\"; do\n"
        "  if [ \"$a\" = \"-T\" ]; then echo 'MOCK LEGACY PUBLISH FAILURE' >&2; exit 1; fi\n"
        "done\n"
        "exec /bin/mv \"$@\"\n"
    )
    mock_mv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["REFRESH_CODEX_PROFILE"] = "1"
    result = subprocess.run([str(SCRIPT), str(src), str(target)], capture_output=True, text=True, timeout=30, env=env)

    assert result.returncode == 1
    assert "MOCK LEGACY PUBLISH FAILURE" in result.stderr
    # Rollback must restore the legacy real directory exactly as it was.
    assert target.is_dir(), "legacy directory must be restored after publish failure"
    assert not target.is_symlink(), "no symlink should be left behind"
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-legacy"
    assert "legacy" in (target / "config.toml").read_text()


def test_flock_concurrency_blocks_overlapping_initialization(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test")
    target = tmp_path / "target"

    import fcntl
    lock_file = tmp_path / "target.lock"
    lock_fd = open(lock_file, "w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = _run_init_script(tmp_path, source, target, refresh=True)
        assert result.returncode == 1
        assert "Another profile initialization is running" in result.stderr
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def test_permissions_target_dir_700(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test")
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    assert target.is_symlink()
    gen = target.resolve()
    assert (gen.stat().st_mode & 0o777) == 0o700, f"gen dir expected 0o700, got {oct(gen.stat().st_mode & 0o777)}"


def test_permissions_files_600(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test")
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    for filename in ["auth.json", "config.toml"]:
        fp = target / filename
        assert fp.is_file()
        assert (fp.stat().st_mode & 0o777) == 0o600, f"expected 0o600 for {filename}"


def test_user_ownership_uses_current_user(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test")
    target = tmp_path / "target"
    current_user = _get_current_user()
    result = _run_init_script(tmp_path, source, target, target_user=current_user)

    assert result.returncode == 0
    assert f"user {current_user}" in result.stdout
    assert (target / "auth.json").is_file()


# ---------------------------------------------------------------------------
# R2: missing-source fail-closed + valid-target reuse
# ---------------------------------------------------------------------------

def test_no_source_exits_visibly(tmp_path: Path):
    result = _run_init_script(tmp_path, tmp_path / "nonexistent_source", tmp_path / "target")
    assert result.returncode == 1
    assert "lacks auth.json/config.toml and no valid target exists" in result.stderr
    assert not (tmp_path / "target").exists()


def test_no_auth_json_exits_visibly(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.toml").write_text("model_provider = 'test'\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert "lacks auth.json/config.toml and no valid target exists" in result.stderr


def test_missing_source_reuses_valid_target(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-reused"}))
    (target / "config.toml").write_text("model_provider = 'reused'\n")

    result = _run_init_script(tmp_path, tmp_path / "no_source", target)
    assert result.returncode == 0
    assert "Reusing existing runtime" in result.stdout
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-reused"


def test_missing_source_fails_when_target_invalid(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-x"}))
    (target / "config.toml").write_text("# no provider\n")

    result = _run_init_script(tmp_path, tmp_path / "no_source", target)
    assert result.returncode == 1
    assert "existing target at" in result.stderr


# ---------------------------------------------------------------------------
# Idempotent skip + force refresh
# ---------------------------------------------------------------------------

def test_idempotent_skip_when_target_valid(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-new")
    target = tmp_path / "target"
    target.mkdir()
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("model_provider = 'original'\n")

    result = _run_init_script(tmp_path, source, target, refresh=False)
    assert result.returncode == 0
    assert "Skipping replacement" in result.stdout
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-original"


def test_idempotent_validates_existing_target_config_toml(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-new")
    target = tmp_path / "target"
    target.mkdir()
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("# model_provider = 'original'\n")

    result = _run_init_script(tmp_path, source, target, refresh=False)
    assert result.returncode == 1
    assert "Existing target profile is invalid" in result.stderr


def test_force_refresh_overwrites_valid_target(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-new", config="model_provider = 'new'\n")
    target = tmp_path / "target"
    target.mkdir()
    (target / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-original"}))
    (target / "config.toml").write_text("model_provider = 'original'\n")

    result = _run_init_script(tmp_path, source, target, refresh=True)
    assert result.returncode == 0
    assert "SUCCESS" in result.stdout
    assert json.loads((target / "auth.json").read_text())["OPENAI_API_KEY"] == "sk-new"
    assert "new" in (target / "config.toml").read_text()


def test_successful_initialization_copies_all_files(tmp_path: Path):
    source = _make_source(
        tmp_path, "source", "sk-test",
        extra={"version.json": '{"version": "1.0"}', "models_cache.json": '{"models": []}'},
    )
    target = tmp_path / "target"

    result = _run_init_script(tmp_path, source, target)

    assert result.returncode == 0
    assert "SUCCESS" in result.stdout
    for fn in ("auth.json", "config.toml", "version.json", "models_cache.json"):
        assert (target / fn).is_file()


# ---------------------------------------------------------------------------
# Validation: JSON + strict TOML (fallback is live on the isolated test env)
# ---------------------------------------------------------------------------

def test_json_validation_requires_valid_json(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-x")
    (source / "auth.json").write_text("not valid json {")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert "Invalid JSON" in result.stderr


def test_json_validation_requires_openai_api_key(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "auth.json").write_text(json.dumps({"OTHER_KEY": "value"}))
    (source / "config.toml").write_text("model_provider = 'test'\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert "missing or invalid OPENAI_API_KEY" in result.stderr


def test_redacted_errors_no_key_leakage(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    secret = "sk-secret-should-not-appear-12345"
    (source / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": secret}))
    (source / "config.toml").write_text("other_config = 'value'\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "model_provider" in result.stderr


def test_toml_malformed_array_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "test"\nbroken = [\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert "broken" in result.stderr or "array" in result.stderr or "TOML" in result.stderr


def test_toml_malformed_inline_table_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "test"\nbroken = {\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_valid_array_and_table_accepted(tmp_path: Path):
    source = _make_source(
        tmp_path, "source", "sk-test",
        config='model_provider = "test"\nallowed = ["a", "b"]\nprovider = { base_url = "https://x", weight = 0.5 }\n',
    )
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "target" / "config.toml").is_file()


def test_toml_numeric_model_provider_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test", config="model_provider = 123\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_boolean_model_provider_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test", config="model_provider = true\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_duplicate_model_provider_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "first"\nmodel_provider = "second"\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_duplicate_key_in_table_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "x"\n[profile]\nk = 1\nk = 2\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_uppercase_boolean_rejected(tmp_path: Path):
    """TOML booleans are case-sensitive: TRUE / False must be rejected."""
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "x"\nflag = TRUE\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_leading_zero_decimal_rejected(tmp_path: Path):
    """TOML integers must not have leading zeros (007 is invalid)."""
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "x"\nbad = 007\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_invalid_escape_sequence_rejected(tmp_path: Path):
    r"""Basic-string escapes must be valid: \x is not a TOML escape."""
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "x"\nbad = "foo\\x"\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_duplicate_key_in_inline_table_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "x"\nbad = { a = 1, a = 2 }\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_empty_dotted_key_segment_rejected(tmp_path: Path):
    """Dotted key segments must be non-empty: a..b is invalid."""
    source = _make_source(tmp_path, "source", "sk-test",
                          config='model_provider = "x"\na..b = 1\n')
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1


def test_toml_valid_string_with_escapes_accepted(tmp_path: Path):
    r"""Valid basic-string escapes like \n, \t, \uXXXX must be accepted."""
    source = _make_source(
        tmp_path, "source", "sk-test",
        config='model_provider = "test"\nmsg = "a\\n\\t\\u0041"\n',
    )
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 0, result.stderr


def test_toml_unrelated_model_provider_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test", config="[unrelated]\nmodel_provider = 'test'\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert "model_provider" in result.stderr


def test_toml_commented_model_provider_rejected(tmp_path: Path):
    source = _make_source(tmp_path, "source", "sk-test", config="# model_provider = 'test'\n")
    result = _run_init_script(tmp_path, source, tmp_path / "target")
    assert result.returncode == 1
    assert "model_provider" in result.stderr
