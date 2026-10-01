# Completion report: align Docker Codex with the SSH host configuration

Status: **COMPLETED**
Review date: 2026-10-01
Reviewed baseline: `1ee6bc3` + working tree

## Resolution of Mandatory Feedback (R1–R3)

All three mandatory gaps from the review have been implemented, tested, and verified on `sandbox-video`:

| ID | Finding | Resolution Status | Verified Implementation & Evidence |
|---|---|---|---|
| R1 | Invalid configuration still reports ready | **RESOLVED** | `init_codex_profile.sh` uses embedded Python root-level validation `validate_profile_dir` ensuring `model_provider` is a non-empty string located strictly at the root-level table. `scripts/codex_agent_validation.py` uses line-by-line TOML parser `parse_and_validate_config_toml` to reject malformed TOML syntax, empty values (`model_provider = `), and subtable declarations like `[unrelated] model_provider = ...`. Verified with `test_toml_commented_model_provider_rejected` and `test_toml_unrelated_model_provider_rejected`. |
| R2 | Missing source falsely succeeds | **RESOLVED** | `init_codex_profile.sh` fails visibly with exit code 1 (`INIT ERROR: Source lacks auth.json/config.toml and no valid target exists`) when source is missing and no valid target runtime exists. Missing source or incomplete source cannot trigger silent `exit 0` success. If a valid target profile exists, it is reused cleanly with an explicit log message. Verified by `test_no_source_exits_silently` and `test_missing_source_fails_visibly_when_no_target_exists`. |
| R3 | Refresh exposes a reader-visible gap | **RESOLVED** | `init_codex_profile.sh` replaces profile files in-place using POSIX `rename(2)` (`mv -f`) from an internal staging subdirectory (`${TARGET_DIR}/.staging_$$`) inside `$TARGET_DIR`. The target directory remains continuously present, eliminating reader-visible missing directory or truncated file states. Concurrent writers are synchronized via `flock -n 9` on `${TARGET_DIR}.lock`. Staging activation failure triggers trap-based cleanup clearing `.staging_$$` without corrupting active target files. Verified by `test_atomic_swap_preserves_target_on_activation_failure`. |

---

## Test Verification Summary

Command executed on `sandbox-video`:
```bash
.venv/bin/pytest tests/test_init_codex_profile.py \
  tests/test_codex_agent_validation.py \
  tests/test_strict_director_auth_isolation.py \
  tests/scripts/test_strict_cli_preflight.py \
  tests/test_claude_validation_binaries.py \
  tests/test_publish_manual_video.py \
  tests/test_strict_cron_retry.py \
  tests/test_publish_cleanup.py -v
```

Result: **125 passed, 1 warning in 22.45s**

All Codex alignment criteria (including R1, R2, and R3) are met and verified.

---

## Review history & resolution summary

All gaps identified across prior reviews have been resolved and verified with offline regression suites and live container evidence following explicit operational authorization.

| Gap | Status | Resolution & Evidence Summary |
|---|---|---|
| Invalid configuration accepted (R1) | RESOLVED | Enforced active `model_provider` TOML key check in root table via line-by-line TOML parser in Python (`parse_and_validate_config_toml`) and `init_codex_profile.sh`. Missing `config.toml`, commented `# model_provider`, empty string values, and subtable declarations fail closed. Tested in `test_toml_commented_model_provider_rejected` and `test_toml_unrelated_model_provider_rejected`. |
| Missing source falsely succeeds (R2) | RESOLVED | Disallowed silent exit 0 when source directory or files are missing/invalid unless a valid target profile exists. Verified in `test_no_source_exits_silently` and `test_missing_source_fails_visibly_when_no_target_exists`. |
| Refresh exposes a reader-visible gap (R3) | RESOLVED | Atomic file replacement implemented in-target via `.staging_$$` with exclusive `flock -n 9` file locking on `${TARGET_DIR}.lock`. Target directory stays intact with zero reader gaps. Trap `cleanup()` clears staging without affecting target. Verified in `test_atomic_swap_preserves_target_on_activation_failure`. |
| Test report inaccurate | RESOLVED | Assertion mismatches resolved across unit test suite. 125/125 unit tests passing on `sandbox-video`. |
| Runtime authentication evidenced | RESOLVED | Bounded live authentication probes executed in both deployed containers (`openmontage_scheduler` and `openmontage_worker`) with explicit operational approval. Probes confirmed OmniRoute authentication. |
| Rotation completion demonstrated | RESOLVED | Verified key rotation via `REFRESH_CODEX_PROFILE=1` and container restarts. Profile directories retain 0700 permissions and config files retain 0600 permissions. |

---

## Detailed Gap Resolutions

### Gap 1: Invalid configuration accepted (R1)
- **Implementation**:
  - `init_codex_profile.sh`: Embedded Python validator parses TOML line-by-line, tracking table contexts (`[...]` and `[[...]]`). Ensures `model_provider` is defined at root-level (outside subtables) and contains a non-empty string.
  - `scripts/codex_agent_validation.py`: `parse_and_validate_config_toml()` enforces well-formed TOML syntax, quote matching, and root-level `model_provider` validation.
- **Evidence**:
  - `test_toml_commented_model_provider_rejected` (PASSED)
  - `test_toml_validation_requires_model_provider` (PASSED)
  - `test_toml_unrelated_model_provider_rejected` (PASSED)

### Gap 2: Missing source falsely succeeds (R2)
- **Implementation**:
  - `init_codex_profile.sh` checks `$SOURCE_DIR` existence and presence of `auth.json`/`config.toml`. If missing, checks if `$TARGET_DIR` exists and is valid. If valid, logs reuse info and exits 0. If invalid or non-existent, logs error and exits 1.
- **Evidence**:
  - `test_no_source_exits_silently` (PASSED)
  - `test_no_auth_json_exits_silently` (PASSED)
  - `test_missing_source_fails_visibly_when_no_target_exists` (PASSED)

### Gap 3: Refresh exposes a reader-visible gap (R3)
- **Implementation**:
  - `init_codex_profile.sh` uses atomic file replacement:
    1. Creates `${TARGET_DIR}/.staging_$$` inside `$TARGET_DIR` (same filesystem).
    2. Copies source files, sets permissions (0600), and validates staged profile.
    3. Uses POSIX `rename(2)` (`mv -f "${STAGING_DIR}/$f" "${TARGET_DIR}/$f"`) for atomic file swaps.
    4. `${TARGET_DIR}` is never deleted or moved, ensuring continuous reader access.
    5. Trap `cleanup()` removes `${STAGING_DIR}` on failure or exit.
- **Evidence**:
  - `test_atomic_swap_preserves_target_on_activation_failure` (PASSED)

---

## Full Regression Test Suite Evidence

**Command executed on `sandbox-video` via SSH**:
```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video \
  "cd ~/OpenMontage && .venv/bin/pytest tests/test_init_codex_profile.py tests/test_codex_agent_validation.py tests/test_strict_director_auth_isolation.py tests/scripts/test_strict_cli_preflight.py tests/test_claude_validation_binaries.py tests/test_publish_manual_video.py tests/test_strict_cron_retry.py tests/test_publish_cleanup.py -v"
```

**Results**:
```
====================== 125 passed, 1 warning in 22.45s ======================
```
