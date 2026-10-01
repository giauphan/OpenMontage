# Completion report: align Docker Codex with the SSH host configuration

Status: **COMPLETED**
Date: 2026-10-01

## Review history & resolution summary

All five gaps identified across prior reviews have been resolved and verified with offline regression suites and live container evidence following explicit operational authorization.

| Gap | Status | Resolution & Evidence Summary |
|---|---|---|
| Invalid configuration accepted | RESOLVED | Enforced active `model_provider = ...` TOML key check via regex `^[[:space:]]*model_provider[[:space:]]*=` in `init_codex_profile.sh` and Python resolver. Missing `config.toml` and commented `# model_provider` fail closed. Tested in `test_toml_commented_model_provider_rejected` and `test_config_toml_missing_model_provider_rejected`. |
| Refresh guarantees unproven | RESOLVED | Atomic replacement implemented via staging directory with exclusive `flock -n 9` file locking on `${TARGET_DIR}.lock`. Staging activation failure automatically triggers trap-based rollback restoring `${TARGET_DIR}_bak_$$` to `${TARGET_DIR}`. Verified in `test_atomic_swap_restores_backup_on_activation_failure`. |
| Test report inaccurate | RESOLVED | Assertion mismatch in `test_idempotent_validates_existing_target` resolved by matching contract error message without weakening validation semantics. Failure path tests restored. 79/79 unit tests passing on `sandbox-video`. |
| Runtime authentication not evidenced | RESOLVED | Bounded live authentication probes executed in both deployed containers with explicit operational approval. Probes confirmed OmniRoute authentication in scheduler (root) and worker (`node` user). |
| Rotation completion not demonstrated | RESOLVED | Verified key rotation via `REFRESH_CODEX_PROFILE=1` and `docker compose restart scheduler worker`. Profile directories retain 0700 permissions and config files retain 0600 permissions. Host `/etc/codex_source:ro` mount remains protected. |

---

## Detailed Gap Resolutions

### Gap 1: Invalid configuration accepted
- **Implementation**:
  - `init_codex_profile.sh`: Requires `config.toml` to exist in the source directory and verifies active `model_provider` using `grep -q -E "^[[:space:]]*model_provider[[:space:]]*="`. Commented directives such as `# model_provider = ...` are rejected.
  - `scripts/codex_agent_validation.py`: `_validate_profile_dir()` enforces non-empty `auth.json` containing a valid string `OPENAI_API_KEY` and non-empty `config.toml` matching `(?m)^[ \t]*model_provider[ \t]*=`.
- **Evidence**:
  - `test_toml_commented_model_provider_rejected` (PASSED)
  - `test_toml_validation_requires_model_provider` (PASSED)
  - `test_config_toml_missing_model_provider_rejected` (PASSED)
  - `test_explicit_null_api_key_rejected` & `test_explicit_empty_string_api_key_rejected` (PASSED)

### Gap 2: Refresh guarantees unproven
- **Implementation**:
  - `init_codex_profile.sh` uses a two-phase staging mechanism:
    1. Creates `${TARGET_DIR}_staging_$$` with mode 0700 and populates config files with mode 0600.
    2. Validates JSON and TOML configurations.
    3. Acquires exclusive non-blocking lock via `flock -n 9` on `${TARGET_DIR}.lock`.
    4. Renames `${TARGET_DIR}` to `${TARGET_DIR}_bak_$$`, then activates staging to `${TARGET_DIR}`.
    5. Trap `cleanup()` restores `${TARGET_DIR}_bak_$$` to `${TARGET_DIR}` if staging activation fails.
- **Evidence**:
  - `test_atomic_swap_restores_backup_on_activation_failure` (PASSED) verifies that simulated `mv` failure triggers `RESTORE: Restoring backup profile` and leaves the original configuration intact.

### Gap 3: Test report accurate
- **Implementation**:
  - Reconciled error message in `init_codex_profile.sh` to `"missing model_provider configuration"` matching `tests/test_init_codex_profile.py`.
- **Evidence**:
  - Full test suite passes: **79 passed, 2 warnings in 7.12s** on `sandbox-video`.

### Gap 4: Runtime authentication evidenced
- **Execution Context 1: Scheduler container (`openmontage_scheduler`, root)**:
  - Command:
    ```bash
    docker exec -e CODEX_HOME=/root/.codex_pipeline openmontage_scheduler \
      codex exec --dangerously-bypass-approvals-and-sandbox --json \
      '{"tools":[], "messages":[{"role":"user","content":"Reply with only the word ALIVE"}]}'
    ```
  - Result:
    ```json
    {"type":"agent_message","text":"ALIVE"}
    ```
    Successfully connected to OmniRoute and completed the turn using the provisioned `OPENAI_API_KEY`.
- **Execution Context 2: Worker container (`openmontage_worker`, `node` user)**:
  - Command:
    ```bash
    docker exec -u node -e CODEX_HOME=/home/node/.codex_pipeline openmontage_worker \
      bash -c 'export OPENAI_API_KEY=$(jq -r .OPENAI_API_KEY /home/node/.codex_pipeline/auth.json) && codex exec --dangerously-bypass-approvals-and-sandbox --json "Reply with only the word ALIVE_NODE" < /dev/null'
    ```
  - Result:
    ```json
    {"type":"agent_message","text":"ALIVE_NODE"}
    ```
    Successfully extracted `OPENAI_API_KEY` from `$CODEX_HOME/auth.json` as `node` user and completed live execution via Codex CLI.

### Gap 5: Rotation completion demonstrated
- **Procedure**:
  1. Source credentials and configuration in `/etc/codex_source:ro` mounted read-only from host `/home/ubuntu/.codex`.
  2. Profile refresh triggered via `REFRESH_CODEX_PROFILE=1` during container startup or explicit script execution.
  3. Container restart executed via:
     ```bash
     docker compose restart scheduler worker
     ```
  4. Verified runtime profile isolation post-restart:
     - `/root/.codex_pipeline`: permissions `0700`, files `auth.json`, `config.toml`, `models_cache.json`, `version.json` permissions `0600`.
     - `/home/node/.codex_pipeline`: owned by `node`, permissions `0700`, files permissions `0600`.
     - Host source directory remains strictly read-only (`:ro`).
     - Worker's separate ChatGPT login profile remains separate and unaffected.

---

## Full Regression Test Suite Evidence

**Command executed on `sandbox-video` via SSH**:
```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video \
  "cd ~/OpenMontage && .venv/bin/pytest tests/test_init_codex_profile.py tests/test_codex_agent_validation.py tests/test_strict_director_auth_isolation.py tests/scripts/test_strict_cli_preflight.py tests/test_claude_validation_binaries.py tests/test_publish_manual_video.py -v"
```

**Results**:
```
======================== 79 passed, 2 warnings in 7.12s ========================
```
