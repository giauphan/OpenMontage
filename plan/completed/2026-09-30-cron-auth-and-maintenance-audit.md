# Pending: cron authentication and maintenance recovery

Status: **PENDING — inspection only; operational fixes not authorized**

Inspected on 2026-09-30 around 14:03–14:15 UTC (21:03–21:15 ICT), via SSH to
`sandbox-video`. User authorized status checks and this plan, plus a separate
commit/push/pull of existing local code changes. Do not publish, generate videos,
clear projects, restart containers, or alter cron under this inspection request.

## Confirmed observations

- `openmontage_scheduler`: running for four days; PID 1 is `cron`; restart policy
  `unless-stopped`, restart count 0. User crontab is installed.
- `openmontage_worker`: running for three days; idle shell plus Chromium processes;
  restart policy `no`, restart count 0. Running does not prove pipeline health.
- Scheduler daily cron: `0 23 * * *` UTC, equivalent to 06:00 ICT next day.
  Instagram-only slot jobs remain enabled at 02:15, 07:15, 14:15 UTC (09:15,
  14:15, 21:15 ICT). These are not YouTube upload jobs. YouTube scheduling is
  performed by the daily strict workflow using platform-native scheduling.
- The latest inspected run started 2026-09-29 23:00:01 UTC and failed at generate
  on 2026-09-30 00:46:39 UTC after two attempts. Preflight and today-batch passed.
  Logs report `Codex Agent Review Gate` failures with
  `workspace routing discovery unauthorized (401)`, followed by
  `ERROR: no candidate passed strict generation and validation`.
- Three preceding inspected runs also ended at generate failure. Their specific
  causes were not exhaustively classified; do not assume all were the same 401.
- `config/publish_schedule.json`: timezone `Asia/Ho_Chi_Minh`, `active_projects: []`.
  No local queue entries exist for September 30 or October 1. This does not prove
  that no videos were previously scheduled directly on YouTube; remote video
  reconciliation was not performed in this read-only audit.
- The scheduler sees a Codex auth file, but `CODEX_HOME` is unset and its live
  Docker mounts include Claude credentials rather than the Codex mounts declared
  in the current compose file. Credential presence is not proof of working auth.
- Scheduler `State.Health` is null, despite a healthcheck in current compose.
  The running scheduler command also lacks the current compose `mkdir -p` step.
  This demonstrates deployment configuration drift. No recreation was attempted.
- Historical Instagram log (September 26) reports HTTP 400 access unavailable.
  Later cron lines report no active projects. This is historical evidence, not a
  fresh test of Meta credentials. YouTube auth was successfully refreshed in the
  prior authorized task; this audit did not refresh/write tokens again.
- Host `crontab -l` returned permission denied. Container cron is confirmed active;
  host-level duplicate schedules could not be ruled out from this command.
- Root disk: 78 GiB total, 59 GiB used, 19 GiB available (76%).
- Inventory: 43 `cand_*` project directories (41 under `projects`, 2 under
  `projects/instagram`), approximately 0.47 GiB of regular-file logical size;
  23 directories contain MP4 renders. No root-level `project_*` directories found.
  These are not automatically trash; no publication/cleanup eligibility was
  inferred from folder names, age, or absence from the queue.

## Follow-up: SSH versus Docker credentials

Read-only comparison on September 30 found three distinct auth/config file
fingerprints (credential values were not printed):

| Context | Home | Current auth/provider | Model |
|---|---|---|---|
| SSH host (`ubuntu`) | `/home/ubuntu/.codex` | API key present, `omniroute` | `model-medium-hight` |
| Scheduler (`root`) | `/root/.codex` | `apikey`, `omniroute` | `model-medium-hight` |
| Worker (`root`) | `/root/.codex` | `chatgpt`, default provider | `gpt-5.6-sol` |

Both containers report Codex CLI 0.157.0. The host binary exists under
`/home/ubuntu/.nvm/versions/node/v22.23.2/bin/codex`, but was absent from the
non-interactive SSH PATH used for inspection. That does not mean interactive
SSH cannot run Codex. The validator selects a container-local credential home
when `CODEX_HOME` is unset (`scripts/codex_agent_validation.py:813-846`).

**Important timing correction:** scheduler config was modified at September 30
06:58:15 UTC and auth at 07:06:08 UTC, after the failing run ended at 00:46:39 UTC.
Consequently the historical 401 does not establish that the current scheduler
credentials are still failing. File timestamps do not prove successful repair
either. No live model request was sent. The exact historical rejection cause
(expired/rejected credential, workspace entitlement or routing configuration)
remains unconfirmed; test the current scheduler context before changing login or
provider settings. Successful SSH use alone is insufficient to validate cron.

## Evidence paths on server

- `/app/logs/strict_docker_publish/state_20260929T230001Z.json`
- `/app/logs/strict_docker_publish/run_20260929T230001Z.log`
- `/app/logs/strict_docker_publish/generate_20260929T230001Z_attempt1.log`
- `/app/logs/strict_docker_publish/generate_20260929T230001Z_attempt2.log`
- `/app/logs/cron_publish.log`
- `/app/config/publish_schedule.json`
- Actual `docker inspect` mounts/command/health vs `docker-compose.yml`

## Proposed recovery — requires separate approval

### P0: Restore Codex authorization in the scheduler

1. Preserve evidence, queue and publication records. Inspect effective Codex user,
   auth location and provider configuration without printing secrets.
2. Compare worker and scheduler credentials and host mounts. Repair login/workspace
   entitlement or auth location based on the actual 401; do not assume the token
   file alone is valid. Do not bypass review or switch provider to hide the error.
3. Run one bounded, explicitly authorized Codex authentication/review probe under
   the same user and environment as cron. Abort before media generation on failure.
4. Add/test an early auth readiness gate and bounded retry/backoff so a known auth
   failure does not trigger hours of rendering and repeated review retries.

### P1: Reconcile deployment and platform scope

1. Compare effective compose configuration with the running scheduler and worker.
   After approval, recreate only affected services with correct credential mounts
   and healthchecks; preserve bind-mounted projects, queue, and secrets.
2. Install cron in one valid format: current startup copies a user crontab into
   `/etc/cron.d` (which expects a user column) and also installs it with `crontab`.
   User cron is demonstrably running; the duplicate-format issue is not established
   as the cause of this incident.
3. Confirm whether future automation is YouTube-only. `MULTI_PLATFORM=0` on the
   daily job does not disable the three independent Instagram cron jobs. Do not
   enable/disable destinations without approval. Investigate Meta only if retained.
4. Decide whether the manual worker should auto-restart and whether residual
   Chromium processes need bounded lifecycle cleanup; do not kill them blindly.
5. Check host cron through approved privileges to rule out duplicate schedules.

### P1: Recover the queue without duplicate publications

1. Inventory the 23 directories containing rendered MP4s, metadata, media hashes,
   validation records and hash-bound human approval. Render existence is not
   release readiness. Reconcile canonical publication records against remote IDs.
2. For any approved recovery date, use fresh future slots with scheduling lead
   time. September 30 / October 1 are incident dates, not evergreen retry dates.
3. Keep strict validation, human approval, uniqueness and native scheduling gates.
   Do not run the whole strict wrapper as a diagnostic: it generates/publishes and
   performs cleanup. Do not force-upload failed claims or clear deduplication data.
4. Verify public/processed or scheduled platform state explicitly, record URLs and
   IDs, then verify the next unattended cron cycle before claiming recovery.

### P2: Maintenance and cleanup safety

1. Produce a read-only manifest of paths, sizes, queue references, required routes,
   hashes, approval status and publication evidence. Use
   `scripts/check_cleanup_eligibility.py` for per-project inspection; never call
   mutating reconciliation during a read-only audit.
2. Keep scheduled, failed, unverified and partially published projects. The
   `clear_stale_projects.sh --all` option broadens inventory, not deletion rights;
   cleanup must still meet the unified verified-publication contract.
3. Review failed-generation deletion separately: `cleanup_failed_generation()` in
   `run_strict_docker_publish.sh` checks queue membership then directly removes
   project directories, without the canonical publication eligibility check.
   The generation log also reports removing rejected candidates. Preserve forensic
   evidence and define an explicit disposable-workspace boundary before changing
   retention. This is a code-review risk, not evidence of lost published assets.
4. Propose archive/quarantine and retention policy for explicit approval. Project
   folders account for only about 0.47 GiB; profile Docker layers, caches and logs
   before assuming project deletion is the meaningful disk-space fix.

## Separately authorized code synchronization

Existing local edits cover the Claude/Codex compatibility shim, inaccessible Codex
credential-directory handling, list-form human approval handling, corresponding
regression tests, and moving the earlier recovery plan to `plan/completed`.
These edits do not resolve the observed provider-side 401 by themselves.

Before commit, an isolated tracked-source checkout in the server worker ran:

```text
pytest -q tests/scripts/test_strict_cli_preflight.py \
  tests/test_claude_validation_binaries.py tests/test_codex_agent_validation.py \
  tests/test_publish_manual_video.py tests/scripts/test_youtube_auth_status.py
55 passed in 4.82s
```

No production pipeline, upload, cleanup, or container restart was run for this test.

## Acceptance criteria

- Scheduler auth probe succeeds in cron's effective environment; no repeated 401s.
- Required service mounts and healthchecks match approved compose configuration.
- One authorized end-to-end run passes all gates; subsequent cron run is observed.
- Approved future queue entries and remote YouTube IDs/status agree; no duplicates.
- Cleanup dry-run lists only verified eligible projects, with hashes and audit trail.
- No credential files are committed and no assets are deleted under this audit.
