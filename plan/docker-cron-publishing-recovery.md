# Docker cron publishing recovery — 2026-09-29

## Incident status and scope

The request is to diagnose today's missing social posts, fix confirmed errors, and retry today's pipeline. This checkout is not currently connected to an operational deployment:

- Environment clock: 2026-09-29 UTC; schedule timezone: Asia/Ho_Chi_Minh (UTC+7).
- Docker CLI is absent. `/var/run/docker.sock` exists but a read-only `/version` request cannot connect.
- `logs/` and `projects/` are empty; `config/publish_schedule.json` contains no active projects.
- No local `.env` was found. Do not print credentials or copy them into incident reports.

Therefore the live failure cause, deployed version, remote upload state, and today's posting outcome cannot yet be confirmed. Do not run a full generation pipeline from this empty checkout or clear uniqueness claims to manufacture a retry.

## Confirmed code defects and targeted repair

### 1. Daily preflight requires the wrong CLI

Evidence: `Dockerfile` installs `@openai/codex`; `scripts/claude_agent_validation.py` is a compatibility shim that delegates to `scripts/codex_agent_validation.py`. However, `scripts/run_strict_docker_publish.sh` checks for `claude` before scheduling today's batch.

Repair: require and report Codex in preflight. Call the canonical `scripts/codex_agent_validation.py` entrypoint directly from the wrapper, while preserving `scripts/claude_agent_validation.py` as an external compatibility shim and keeping existing validation gates unchanged. This is not a provider switch: it aligns preflight with the existing validator. Test the preflight with mocked executables: Codex present / Claude absent must pass; Codex absent must fail before production.

### 2. Publishing crashes on normal validation history

Evidence: `scripts/validation_status.py` writes a JSON list of validation entries. The stale-review check in `scripts/publish_manual_video.py` calls `.get()` on the loaded value as if it were always a dictionary.

Repair: accept the logger's history format as well as legacy dictionary status; use the latest applicable review and retain stale-media hash rejection. Test normal history, legacy status, and mismatched hashes. Do not bypass approval or validation requirements.

## Deployment investigation (before any retry)

1. Connect to the actual Docker host using the user's established access method. Confirm repository location, deployment revision, UTC/local time, and queue timezone.
2. Inspect `docker compose ps -a`, scheduler logs, installed `crontab -l`, and availability of Codex, Python, FFmpeg, ffprobe, and jq inside the scheduler.
3. Read `logs/cron_pipeline.log`, `logs/cron_publish.log`, and the latest files under `logs/strict_docker_publish/`. Identify the first failing stage rather than guessing from missing posts.
4. Back up the live schedule and incident logs. Inventory today's queued project IDs, dates, slots, media, approval checkpoints, and validation state. This checkout's empty schedule must NOT overwrite the live schedule.
5. Check authentication readiness without exposing secrets: Codex session, YouTube OAuth, Firestore, and Instagram/Meta plus R2 where applicable.
6. Reconcile each selected project's Firestore canonical and uniqueness records against actual YouTube/Instagram media IDs. A failed local record can follow a successful remote upload; never assume it is safe to upload again solely because a command failed.

## Additional recovery hazards requiring live investigation

- `schedule_today_native.py` rejects elapsed/near slots before checking existing upload state. It uploads only when a new claim succeeds, so existing failed/in-progress claims are not a reliable retry path.
- The manual YouTube route reads scheduling time from metadata, not merely the queue date; without scheduling time it may upload unlisted. Do not report such an upload as public.
- `publish_active_projects.py --slot` includes overdue entries and excludes certain failed statuses even when `--retry-failed` is present. Review its selected scope before using it.
- Resuming an in-progress claim is not proof no remote upload exists. Avoid concurrent cron/manual runs for the same project.
- The full strict wrapper can regenerate content and append queue entries. `STRICT_PUBLISH_SKIP_GENERATE` chooses the latest generation log, not necessarily the intended incident run. Do not use the full wrapper as a blind upload retry.
- The scheduler installs packages on every startup and places a user-format crontab in `/etc/cron.d` as well as installing it with `crontab`. The user crontab can work, but the system-cron copy has the wrong format. Inspect actual startup/cron errors before attributing the outage to this.
- Facebook is explicitly disabled in the strict workflow. Do not enable additional destinations without approval.

These hazards are not evidence of which failure occurred today. Keep broader retry/concurrency refactoring separate from the two targeted fixes unless live evidence requires it.

## Safe retry procedure on the live host

1. Deploy tested code fixes without replacing `.env`, queue, credentials, or projects. Confirm the running container sees the changed bind-mounted files; rebuild only if needed for image changes.
2. Ensure no overlapping cron/manual processing of selected projects. Preserve original queue date, project identity, approvals, remote IDs, and deduplication records.
3. For an Instagram project confirmed not already published, use the existing single-project manual publisher with its actual project path, original `--date`, `--only-platform instagram`, and `--retry-failed`. Retain validation and approval gates. Do not use `--force` or uniqueness-clearing scripts.
4. For YouTube, first determine whether the video already exists privately/scheduled/publicly. An existing upload should be reconciled rather than uploaded again. Use native scheduling only for genuinely unclaimed future slots more than 20 minutes ahead; failed claims or elapsed slots need a separately reviewed recovery, not a blind rerun. Do not silently move the publication date or mistake an unlisted upload for publication.
5. If no completed video exists, resume the failed production stage using its actual artifacts and approvals. Preserve the selected providers, models, and runtime. Do not generate substitute content without approval.
6. Verify platform-side status and retain video IDs/URLs, publish timestamps, Firestore state, queue status, and command exit results. YouTube `scheduled` and Instagram `processing` are not yet proof of a public post.
7. Leave assets and logs intact until successful remote publication is verified; confirm the next cron slot remains enabled.

## Acceptance criteria

- Targeted regression tests and shell syntax checks pass.
- On the deployment, preflight accepts the installed Codex validator.
- No approved publishing path crashes on a normal validation-history list; changed-media reviews remain blocked.
- Each intended retry is reconciled with platform state, does not duplicate an existing post, and preserves approvals.
- Today's public URLs/statuses are verified remotely, or the remaining blocker is explicitly reported.

## Current execution boundary

Local repairs and tests can proceed. Live deployment, retry, and publication verification are blocked until a reachable Docker host with the actual run data is available. No live publishing was attempted from this empty checkout.

## Local validation outcome — 2026-09-29

- Added `tests/scripts/test_strict_cli_preflight.py`: extracts the wrapper's actual preflight block, stubs cleanup/logging/state writes, and uses a closed mock executable PATH. Codex present / Claude absent passes and reports the Codex version; Codex absent fails before the next-stage marker, both with and without Claude installed. Each subprocess has a 10-second timeout. Isolated result: **3 passed in 0.07s**.
- Ran `python3 -m pytest tests/scripts/test_strict_cli_preflight.py tests/test_strict_cron_retry.py tests/test_strict_generation_failure_cleanup.py tests/test_strict_schedule_only.py tests/test_publish_manual_video.py tests/tools/test_strict_publish_preflight.py -q` with a 180-second command timeout: **66 passed in 8.30s**.
- `bash -n scripts/run_strict_docker_publish.sh` and `git diff --check` passed (10-second command timeout).
- No unrelated failures required changes. This validation follow-up only adds the isolated test file and updates this plan; existing implementation and fixture changes are unchanged. No live deployment, generation, scheduling, publishing, or recovery retry was performed. Deployment verification remains blocked as described above.
