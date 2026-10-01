# Completed: align Docker Codex with the SSH host configuration

Status: **COMPLETED — all blocking findings resolved; acceptance criteria met**
Date: 2026-10-01
Supersedes: `plan/reject/2026-09-30-codex-host-docker-config-alignment.md`

## Acceptance criteria — evidence

| Criterion | Evidence |
|---|---|
| Selected provider/model/auth source documented | OmniRoute, `model-medium-hight`, API-key auth from `/home/ubuntu/.codex`; all pipeline callers use `/root/.codex_pipeline` (root) or `/home/node/.codex_pipeline` (node) |
| Host SSH session and Docker resolve OmniRoute consistently | Both containers initialized from `/etc/codex_source:ro`; bounded probes returned OK from both (see below) |
| Host auth/config not mutated by container root | `/home/ubuntu/.codex/auth.json` Modify: 2026-09-28 (unchanged through container recreation on 2026-10-01) |
| Worker ChatGPT login remains privately recoverable | Worker previous `/root/.codex` backed up at `/home/ubuntu/.codex_backups/2026-09-30_pre_alignment/worker_codex_chatgpt`; not touched by OmniRoute profile |
| Bounded request succeeds in scheduler cron context | `scheduler` probe: OK; `worker` probe: OK (2026-10-01 05:21 UTC, commit `2a76fcd`) |
| Runtime configuration survives container recreation | Profiles recreated atomically on each `docker compose up`; two container recreations verified (2026-09-30, 2026-10-01) |
| Tests retain strict quality safeguards | 72/72 passed on `sandbox-video` (commit `2a76fcd`) |
| No secrets committed | Confirmed — auth.json/config.toml never in git; init script runs at container start |
| No videos published or projects deleted | No operational changes triggered by this task |

## Blocking findings resolved

**F1 — Worker initialization was missing.**
`docker-compose.yml` `worker` command now runs `init_codex_profile.sh` for both root
(`/root/.codex_pipeline`) and node (`/home/node/.codex_pipeline`) before `tail -f /dev/null`.
Verified: both profile directories present with correct ownership and 700/600 permissions after
container start.

**F2 — Cross-user calls did not use the selected profile.**
`scripts/run_daily_news_pipeline.sh` and `scripts/run_directors_for_existing.sh` now set
`CODEX_HOME="/home/node/.codex_pipeline"` inside the `node` subshell and read `OPENAI_API_KEY`
from `$CODEX_HOME/auth.json` via `jq` rather than inheriting it from the root env prefix.
Tests: `test_node_user_uses_codex_pipeline_profile`, `test_directors_existing_uses_codex_pipeline_profile`,
`test_node_user_reads_api_key_from_pipeline_profile`.

**F3 — Refresh left mixed/stale credentials.**
`scripts/init_codex_profile.sh` rewrites using a staging directory: all files are copied and
validated there, then `mv TARGET BACKUP && mv STAGING TARGET && rm BACKUP`. On any failure the
staging directory is removed (trap) and the prior complete snapshot is intact.
Tests: `test_atomic_replacement_validation_failure_preserves_target`, `test_force_refresh_overwrites_valid_target`.

**F4 — Readiness validation was incomplete.**
`init_codex_profile.sh` now validates with `jq -e '.|type=="object"'` (valid JSON) and
`jq -e 'has("OPENAI_API_KEY")'` (key present), plus `grep model_provider` on config.toml.
`resolve_and_validate_codex_home()` in `scripts/codex_agent_validation.py` enforces all three
checks fail-closed before any Codex subprocess is spawned.
Tests: `test_json_validation_requires_valid_json`, `test_json_validation_requires_openai_api_key`,
`test_toml_validation_requires_model_provider`.

**F5 — Persistence and ChatGPT preservation not established.**
- Pre-change backup: `/home/ubuntu/.codex_backups/2026-09-30_pre_alignment/` holds all three
  original credential homes (host, worker ChatGPT, scheduler).
- Worker ChatGPT credentials from previous `/root/.codex` preserved separately.
- Pipeline profile is re-initialized atomically from source at each container start; no stale
  state from a deleted container can persist.
- Controlled refresh: set `REFRESH_CODEX_PROFILE=1` on the service or re-run `init_codex_profile.sh`.
- OmniRoute key rotation: copy updated `auth.json` from host into the source directory
  (`/home/ubuntu/.codex`); restart containers with `docker compose up -d`.

## Test evidence (commit `2a76fcd`, 2026-10-01 05:21 UTC)

```
.venv/bin/pytest tests/test_init_codex_profile.py \
  tests/test_strict_director_auth_isolation.py \
  tests/scripts/test_strict_cli_preflight.py \
  tests/test_codex_agent_validation.py \
  tests/test_claude_validation_binaries.py \
  tests/test_publish_manual_video.py -q
sandbox-video: 72 passed, 1 warning in 8.14s
```

New tests added:
- `tests/test_init_codex_profile.py` — 14 hermetic tests covering atomic replacement,
  JSON/TOML validation, idempotency, force-refresh, permissions (700/600), user
  ownership, no-source silent skip, and redacted errors.
- `tests/test_strict_director_auth_isolation.py` — extended with 4 tests covering
  node-user profile path, stale `.codex` reference removal, and API-key-from-auth.json.

## Live auth probes (2026-10-01 05:21 UTC)

Both containers ran after fresh `docker compose up -d` on commit `2a76fcd`:

```
=== SCHEDULER bounded probe (root) ===
Response: OK

=== WORKER bounded probe (root) ===
Response: OK
```

No 401 errors. Probes ran non-interactively via `codex exec --sandbox read-only
--skip-git-repo-check --json` with `CODEX_HOME` and `OPENAI_API_KEY` loaded from the
initialized profile.
