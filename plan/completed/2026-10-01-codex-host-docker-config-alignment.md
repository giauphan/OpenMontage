# Completed: align Docker Codex with the SSH host configuration

Status: **COMPLETED** — all reviewer gaps resolved and evidenced
Date: 2026-10-01
Commit: `2d83ac3`
Supersedes: `plan/reject/2026-10-01-codex-host-docker-config-alignment.md`

## Acceptance criteria — evidence

| Criterion | Evidence |
|---|---|
| Invalid profiles cannot be reported ready | `_validate_profile_dir()` added — parses JSON, checks non-empty non-null `OPENAI_API_KEY`, verifies `model_provider` in config.toml. Null key, empty-string key, missing `model_provider` all raise `RuntimeError`. Confirmed by `test_explicit_null_api_key_rejected`, `test_explicit_empty_string_api_key_rejected`, `test_config_toml_missing_model_provider_rejected`. |
| Interrupted refresh cannot leave profile absent | Atomic swap restores `BACKUP_DIR→TARGET_DIR` inside `cleanup()` trap if activation `mv` fails. Prior working profile is always recoverable. Confirmed by `test_atomic_swap_restores_backup_on_activation_failure`. |
| Rotation procedure reliable and documented | `deploy/openmontage.cron` and `scripts/init_codex_profile.sh` now document: (1) update `/home/ubuntu/.codex`, (2) run with `REFRESH_CODEX_PROFILE=1`, (3) `docker compose restart scheduler worker` — NOT `up -d`. `test_force_refresh_overwrites_valid_target` confirms the flag forces replacement. |
| Execution-context evidence covers actual contexts | Resolver tests cover null key, empty-string key, missing `model_provider` for both explicit `CODEX_HOME` and auto-discovery paths. Node-user subshell verified to use `/home/node/.codex_pipeline` and read key from auth.json. Cron `CODEX_HOME` value accepted by resolver with valid profile. |
| Host auth/config not mutated | `/home/ubuntu/.codex/auth.json` Modify: 2026-09-28 — unchanged through all container operations. |
| ChatGPT profile preserved | Backed up at `/home/ubuntu/.codex_backups/2026-09-30_pre_alignment/worker_codex_chatgpt`. Not touched. |
| No secrets committed | auth.json/config.toml never in git. Init script runs at container start from read-only mount. |
| No videos published or projects deleted | No operational changes triggered. |

## Gap-by-gap resolution

**Gap 1 — Invalid profiles accepted by resolver: FIXED**
Added `_validate_profile_dir()` to `scripts/codex_agent_validation.py`:
- Reads and parses auth.json as JSON (fails on invalid JSON)
- Checks `OPENAI_API_KEY` is a non-empty, non-null string
- Checks `config.toml` contains `model_provider`
Both explicit `CODEX_HOME` path and auto-discovery candidate loop use this helper.
`init_codex_profile.sh` idempotent-skip path updated to check key is non-empty string via jq.

**Gap 2 — Interrupted refresh leaves profile absent: FIXED**
Replaced bare `trap 'rm -rf "$STAGING_DIR"' EXIT` with a `cleanup()` function that:
1. Removes staging if it still exists
2. If `TARGET_DIR` is absent AND `BACKUP_DIR` exists → restores backup to target
This means a failed activation `mv` never permanently removes the working profile.

**Gap 3 — Rotation guidance unreliable: FIXED**
`deploy/openmontage.cron` now comments: key rotation requires `docker compose restart scheduler worker` not `docker compose up -d` (which skips unchanged services).
`scripts/init_codex_profile.sh` header documents the same rotation procedure.

**Gap 4 — Execution-context evidence incomplete: FIXED**
New tests in `tests/test_codex_agent_validation.py`:
- `test_explicit_null_api_key_rejected`
- `test_explicit_empty_string_api_key_rejected`
- `test_config_toml_missing_model_provider_rejected`
- `test_auto_discovery_null_api_key_rejected` (candidate with invalid key is skipped)
`tests/test_strict_director_auth_isolation.py` verifies node-user subshell path and cron environment.

## Test evidence (commit `2d83ac3`, 2026-10-01 07:08 UTC)

```
.venv/bin/pytest tests/test_init_codex_profile.py \
  tests/test_codex_agent_validation.py \
  tests/test_strict_director_auth_isolation.py \
  tests/scripts/test_strict_cli_preflight.py \
  tests/test_claude_validation_binaries.py \
  tests/test_publish_manual_video.py -q
sandbox-video (Python 3.10.12): 72 passed, 1 warning in 7.11s
```
