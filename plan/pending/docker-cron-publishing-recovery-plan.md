# Pending: Docker cron publishing recovery

**Status:** PENDING — live deployment access required
**Incident date:** September 29, 2026
**Timezone:** `Asia/Ho_Chi_Minh` (UTC+7)
**Reference:** `OpenMontage/plan/docker-cron-publishing-recovery.md`
**Author:** Automated recovery task
**Requires approvals:** implementation, deployment, and publishing (for any non-incident-day retries)

## Objective

Identify the actual cause of the missed social posts, deploy verified fixes, safely retry
affected videos, and confirm platform-side publication without duplicates.

**Date rule:** The incident date is **September 29, 2026**. If this plan is executed on a
later date, obtain explicit approval before publishing overdue content or changing
publication timing. All metadata, uniqueness claims, and remote IDs must retain their
original incident-day identity.

## Scope and execution boundary

This plan authorizes nothing by itself. It describes a narrow, evidence-backed recovery
flow to be executed only after deployment access and the required approvals are in place.

The previous diagnostic session produced a detailed incident report but could not confirm
the live failure cause because the inspected environment was not connected to production:

- Docker CLI was unavailable; `/var/run/docker.sock` was present but inaccessible.
- `projects/` and `logs/` were empty.
- `config/publish_schedule.json` had no active projects.
- No local `.env` was accessible.

Those are observations of one checkout only, not proof of the deployment state. Do **not**
overwrite live queue, projects, or credentials from this empty checkout.

## Previously completed local work — reported, not newly deployed

The prior investigation reports:

- `scripts/run_strict_docker_publish.sh` prefetch now checks and reports Codex, and calls
  `scripts/codex_agent_validation.py` directly (compatibility shim preserved externally).
- `scripts/publish_manual_video.py` now handles validation-history lists and legacy
  dictionaries while preserving stale-media and approval checks.
- Regression tests added: `tests/scripts/test_strict_cli_preflight.py` and coverage in
  `tests/test_publish_manual_video.py`.
- Test report: **66 passed** for the strict/cron/publish test set, plus `bash -n` and
  `git diff --check` clean.

**Verification duty of the implementing agent:** confirm this diff is what you expect and
matches the deployed revision before relying on it. Do not assume the fixes are committed
or deployed.

## Phase 1 — Establish deployment access and diagnose

- [ ] Read `AGENT_GUIDE.md` and `plan/docker-cron-publishing-recovery.md`.
- [ ] Connect using the user's established Docker-host access method.
- [ ] Confirm repository path, deployed revision (`git rev-parse HEAD`), running
  containers, bind mounts, host clock, and timezone.
- [ ] Inspect, in order:
  - `docker-compose.yml`
  - `Dockerfile`
  - `deploy/openmontage.cron`
  - Installed crontab: `crontab -l` and the effective scheduler startup.
  - `/var/log` or in-container scheduler logs.
  - `logs/cron_pipeline.log`
  - `logs/cron_publish.log`
  - Incident records under `logs/strict_docker_publish/`.
- [ ] Identify the first failing stage and capture redacted evidence.
- [ ] Verify required executables and authentication readiness **without exposing
  credentials** (Codex session, YouTube OAuth, Firestore, Meta/Instagram+R2).

**Deliverable:** confirmed root cause, affected projects/platforms, and remaining
blockers.

**Stop condition:** if live access is unavailable, mark BLOCKED and report. The inspected
checkout has an empty queue and cannot support a real publishing retry.

## Phase 2 — Protect production state

- [ ] Back up the live queue (`config/publish_schedule.json`), affected project
  metadata, approvals, validation records, and scheduler configuration.
- [ ] Snapshot affected Firestore canonical and uniqueness records in a secrets-safe
  location.
- [ ] Preserve media assets, credentials, and existing remote video IDs.
- [ ] Coordinate a bounded maintenance window and prevent overlapping cron/manual
  processing of the affected projects.
- [ ] Check for and report any in-flight scheduler or manual publisher processes; pausing
  cron does not stop a publisher already in flight.

**Do not overwrite the live schedule with this checkout's empty schedule.**

## Phase 3 — Verify and deploy targeted fixes

- [ ] Inspect the existing local fixes and regression tests.
- [ ] Confirm: Codex-present/Claude-absent preflight passes and reports the version.
- [ ] Confirm: missing Codex blocks before the next stage.
- [ ] Confirm: validation-history lists and legacy dictionaries both work.
- [ ] Confirm: changed-media reviews still block.
- [ ] Confirm: missing approvals still block.
- [ ] Run the suite in Phase 5 before deployment.
- [ ] Deploy only reviewed changes; preserve live queue, projects, and credentials.
- [ ] Verify the running container resolves the intended code (paths, mounts, restart
  policy).

### Conditional scheduler repairs

Implement only if deployment evidence shows they are the cause:

- [ ] Move required package installation from container startup into the image build.
- [ ] Use exactly one valid cron installation method:
  - user crontab, OR
  - system file under `/etc/cron.d/` including the required user column.
- [ ] Remove duplicate job installation without changing the intended schedule.
- [ ] Repair evidenced PATH, working-directory, credential-mount, permission, or
  authentication problems.
- [ ] Verify startup and restart behavior.

**Deliverable:** minimal tested patch and confirmed deployed revision.

## Phase 4 — Reconcile uploads and repair retry behavior if needed

For each affected project/platform:

- [ ] Compare live queue state, media identity, Firestore records, and actual platform media.
- [ ] Classify as: public, uploaded but not public, confirmed absent, or ambiguous.
- [ ] Reconcile existing uploads rather than replacing them.
- [ ] Preserve original project id, date, account id, and uniqueness protection.
- [ ] Block retries when remote state is ambiguous or another publisher owns the work.

If evidence demonstrates a bounded retry defect, restrict changes to the named components
and never broaden the scope:

| File | Responsibility |
|---|---|
| `scripts/schedule_today_native.py` | Existing-upload reconciliation and elapsed-slot handling |
| `scripts/publish_active_projects.py` | Precisely bounded retry selection |
| `scripts/publish_manual_video.py` | Single-project/platform retry, timing, approval enforcement |
| `tools/publish_store.py` | Atomic ownership and guarded state transitions |

Required properties for any retry code:

- [ ] Concurrent retries cannot both upload for the same platform item.
- [ ] Existing remote video IDs are retained, not orphaned or duplicated.
- [ ] Upload success + local persistence failure must not trigger blind re-upload.
- [ ] Repeated execution is idempotent.
- [ ] Failed/in-progress claims are not resumed through unconditional writes.
- [ ] Overdue entries are not accidentally pulled into a slot-only retry.
- [ ] Queue date alone is not mistaken for YouTube scheduling time.
- [ ] No broad publishing-system rewrite.

## Phase 5 — Validate

Run with a 180-second timeout:

```sh
python3 -m pytest tests/scripts/test_strict_cli_preflight.py tests/test_strict_cron_retry.py tests/test_strict_generation_failure_cleanup.py tests/test_strict_schedule_only.py tests/test_publish_manual_video.py tests/tools/test_strict_publish_preflight.py -q
bash -n scripts/run_strict_docker_publish.sh
git diff --check
```

Add focused tests for any newly repaired behavior:

- [ ] Failed and in-progress claim handling.
- [ ] Concurrent ownership acquisition.
- [ ] Existing platform uploads (no double upload).
- [ ] Upload success followed by local persistence failure.
- [ ] Original-date preservation and timezone boundaries.
- [ ] Approval and stale-media rejection.

Validate Docker and cron on the actual host (not on this checkout). Record current
results; the earlier 66-test result is not substituted for new validation.

## Phase 6 — Retry approved affected videos only

- [ ] Confirm the exact projects, platforms, and publication timing authorized for recovery.
- [ ] Re-check remote state immediately before each attempt.
- [ ] Use the smallest supported single-project/platform scope.
- [ ] Retain quality checks, approvals, original identity, and deduplication.
- [ ] For existing YouTube uploads: reconcile visibility/scheduling instead of uploading.
- [ ] For elapsed slots: obtain approval for the recovery timing.
- [ ] For missing media: resume the failed production stage using its existing artifacts
  and approvals; do not substitute providers/models/runtimes.

**Forbidden recovery shortcuts:**

- `--force` or uniqueness-clearing scripts.
- Blind full-wrapper reruns as a retry.
- Bypassing validation or human approval.
- Switching providers/models/runtimes without approval.
- Enabling Facebook (disabled in the strict workflow) without approval.
- Logging credentials or secrets.

## Phase 7 — Verify publication and restore normal scheduling

- [ ] Record each platform's remote video id, public URL, visibility/status, and
  publication timestamp.
- [ ] Confirm actual publication — not merely upload/queue success.
- [ ] Mark scheduled, private, unlisted, or processing videos accurately.
- [ ] Reconcile the queue and Firestore with the verified platform state.
- [ ] Preserve evidence and assets until verification is complete.
- [ ] Restore the intended scheduler state and confirm the next execution.
- [ ] If restoration is unsafe, document an explicit approved hold.

## Rollback

- [ ] Stop further retries.
- [ ] Restore prior code/config when rollback is appropriate.
- **Never** blindly restore an old queue or Firestore snapshot after a successful upload.
- [ ] Preserve newly created remote ids and reconcile external side effects.
- [ ] Do not automatically delete remote posts.
- [ ] Restore safe scheduling or explicitly report an approved hold.

## Completion criteria

Report these three statuses separately:

1. **Local-ready:** repairs reviewed and tests pass on the inspected checkout.
2. **Deployed:** the intended code and scheduler are verified live.
3. **Published:** authorized videos have verified public URLs/statuses and no duplicate uploads.

## Agent prompt (ready to reuse)

> Implement this pending plan phase by phase. Read the project guide and existing incident
> report first. Verify prior fixes rather than repeating them. Stop at missing deployment
> access, ambiguous remote state, or missing approvals. Preserve the September 29, 2026
> incident identity and obtain approval for any later publication. Make only
> evidence-backed repairs, test them, perform narrowly scoped retries, and verify actual
> public posts. Report local readiness, deployment, and publication separately.
