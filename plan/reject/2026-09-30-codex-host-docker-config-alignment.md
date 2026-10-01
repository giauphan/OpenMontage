# Rejected completion: align Docker Codex with the SSH host configuration

Status: **REJECTED — partially implemented; acceptance criteria not met**

## Review feedback — 2026-10-01

Completion was rejected after reviewing implementation commit `e4e39a3`, checkout
`4aa6cfa`, and the running containers on `sandbox-video`. This rejects the claim
of completion, not the useful changes already implemented. The original plan
below is retained as the requirements baseline; this feedback takes precedence
where earlier status or evidence is outdated.

### Verified progress

- Host Codex source is mounted read-only in both containers.
- Scheduler selects `/root/.codex_pipeline`, initializes it, and is healthy.
- The unattended September 30 23:00 UTC run completed at 23:35:20 UTC (October 1
  06:35 ICT), including successful Codex reviews. The historical 401 did not block
  that run; do not report it as a proven current failure.

### Blocking findings

1. **Worker initialization is missing.** `docker-compose.yml:18–23` sets
   `CODEX_HOME=/root/.codex_pipeline`, but only scheduler startup initializes it
   (`:45–51`). Live inspection confirmed the worker directory does not exist.
   Initialize the approved worker profile before direct review/news tasks run.
2. **Cross-user calls do not use the selected profile.**
   `scripts/run_daily_news_pipeline.sh:151–160` switches to `node` and overrides
   `CODEX_HOME` with `/home/node/.codex`; `scripts/run_directors_for_existing.sh`
   has the same issue. Propagate an explicitly initialized profile accessible to
   that user, without mixing an inherited API key with another provider config.
3. **Refresh can leave mixed or stale credentials/configuration.**
   `scripts/init_codex_profile.sh:13–25` copies files separately and ignores copy
   failures. Validate the source and replace the auth/config snapshot as a unit;
   on failure retain the prior complete snapshot and return an error.
4. **Readiness validation is incomplete.** Presence/nonempty checks do not prove
   valid JSON/TOML, compatible provider/auth, required environment, or live access.
   News-selection error paths also need to fail closed on selected-profile/auth
   failures rather than silently continuing with algorithmic fallback.
5. **Persistence and ChatGPT preservation are not established.** Compose declares
   no persistent runtime-profile storage or selectable preserved ChatGPT profile.
   Provide private backup/recovery evidence and a controlled refresh/recreation
   procedure; do not assume old container-local credentials survive replacement.

### Test evidence and requirements for re-review

The same targeted command was run in both deployed containers:

```text
python3 -m pytest -q tests/test_codex_agent_validation.py \
  tests/scripts/test_strict_cli_preflight.py \
  tests/test_strict_director_auth_isolation.py \
  tests/test_claude_validation_binaries.py
Scheduler: 29 passed
Worker:    27 passed, 2 failed
```

The worker failures encountered the missing configured profile:
`TestCodexFailClosedStrictReview.test_strict_review_fails_on_missing_category` and
`test_strict_review_uses_canonical_codex_result`. Make unit tests independent of
real credentials and add explicit integration checks for both service profiles.
Cover cross-user propagation, unreadable/malformed files, missing provider env,
atomic refresh, private permissions, source immutability and redacted errors.

Re-review requires corrected code, passing isolated tests, verified profiles in
both containers after an approved recreation, and bounded live readiness evidence
in the actual cron context. Do not bypass review or switch providers silently.
No operational changes, publishing or deletion are authorized by this feedback.

---

## Original plan
Date: 2026-09-30
Related evidence: `2026-09-30-cron-auth-and-maintenance-audit.md`

## Proposed interpretation and approval boundary

Use the SSH host's `/home/ubuntu/.codex` OmniRoute configuration as the source for
pipeline execution in Docker. Preserve the worker's current ChatGPT login as a
separate, explicitly selected profile rather than overwriting or merging it.

This is a proposed target, not authorization to change the worker's provider.
Confirm this selection before implementation. If the intent is instead to keep
worker ChatGPT and scheduler OmniRoute permanently, retain those explicit service
profiles and apply the same isolation, cron propagation and tests below.

No automatic fallback between OmniRoute/API-key and ChatGPT/OAuth. Switching can
change model behavior, data destination, cost and account quota. This plan does
not authorize login changes, live model requests, container recreation, generation,
publishing, cleanup, or enabling/disabling social destinations.

## Evidence and diagnosis limits

| Context | Current credential home | Provider / auth | Model |
|---|---|---|---|
| SSH host, `ubuntu` | `/home/ubuntu/.codex` | `omniroute`, API key | `model-medium-hight` |
| Docker scheduler, `root` | `/root/.codex` | `omniroute`, API key | `model-medium-hight` |
| Docker worker, `root` | `/root/.codex` | Default provider, ChatGPT login | `gpt-5.6-sol` |

The three auth/config fingerprints differ. Current compose declares host Codex
mounts, but live scheduler mounts do not match. The validator discovers a local
credential home if `CODEX_HOME` is absent; `/root/.codex` may therefore win over
what the SSH session uses.

Last night's scheduler log contains `workspace routing discovery unauthorized
(401)`. Scheduler credentials changed later that morning. Do not assume the
historical failure still reproduces or claim configuration alignment alone fixes
it. The next approved live probe must establish current behavior.

## Target design

- Host OmniRoute configuration is the authoritative source, with its provider,
  endpoint, model alias and matching API-key auth preserved as a unit. Do not copy
  only the key into a ChatGPT profile or rename the model alias speculatively.
- Use a dedicated named Docker profile directory for pipeline Codex, distinct from
  the preserved ChatGPT home. Set `CODEX_HOME` explicitly for each service and every
  cron invocation that uses Codex. Do not depend on interactive shell startup.
- Mount the host source read-only at a dedicated source location. Do not give
  container root a read-write mount over the user's SSH credential directory:
  Codex may write sessions/state, change ownership or update auth there.
- Prepare separate private writable runtime homes for worker and scheduler from
  the approved source. Copy only the configuration/auth files and verified required
  dependencies, not unrelated session history. Use directories mode 700 and files
  mode 600; never print the file contents or place them in the repository/image.
- Retain the ChatGPT profile in private persistent storage with its own writable
  runtime home if used. Never share writable auth/state between providers or
  concurrently running services. No fallback to `/tmp/codex` stale credentials.
- Source changes require an explicit controlled refresh of the runtime snapshot,
  not silent copying during a running request. Missing or invalid selected profile
  must stop before generation; never fall through to another discovered login.

Exact new directory/mount names must be verified for collisions and recorded
before creation. These are proposed locations/design, not claims about current
server resources.

## Implementation steps after approval

### 1. Preserve state and establish a baseline

1. Record effective user, CLI path/version, `HOME`, `CODEX_HOME`, provider name,
   model, endpoint hostname and relevant environment variable *names/presence* in
   SSH, worker and scheduler. Never dump complete environment/config or secrets.
2. Inspect the host config for referenced `env_key`, credential stores, absolute
   paths, model-provider URLs and project-local overrides. A copied auth file is
   insufficient if the host relies on shell exports or helpers unavailable in cron.
3. Check API-key routing with the configured auth scheme. Distinguish a gateway
   rejection from an upstream workspace entitlement failure; retain sanitized
   error category/status only. Do not change providers merely to suppress a 401.
4. Back up worker and scheduler credentials/config privately outside Git before
   replacing containers. Record mount sources, ownership and rollback references.
5. Preserve the existing YouTube token mount, projects, publication records and
   active queue. Confirm no render/review/publish process is running before any
   approved service replacement; coordinate around the next cron slot.

### 2. Make runtime profile selection explicit

Files to review/change narrowly:

- `docker-compose.yml`: dedicated read-only source mounts, isolated writable
  runtime homes, explicit `CODEX_HOME`, and consistent configuration in both
  services. Avoid ambiguous `~` expansion under a different deployment user.
- Container initialization: validate source/profile and initialize the selected
  runtime snapshot without copying secrets into Docker build layers or logs.
  Reuse an existing entrypoint if suitable; do not introduce a competing launcher.
- `deploy/openmontage.cron` / `scripts/run_strict_docker_publish.sh`: propagate
  the chosen `CODEX_HOME` and required noninteractive environment deliberately.
  A variable in Compose is not sufficient evidence that cron children receive it.
  Keep secrets out of the crontab and command-line arguments.
- `scripts/codex_agent_validation.py`: when the pipeline provides `CODEX_HOME`,
  validate it and fail closed if invalid. Keep any intentional interactive legacy
  behavior separate; never silently choose another provider for the pipeline.

Ensure all pipeline Codex call sites use the same selected profile, not only the
reviewer. Inventory subprocess callers before implementing, including any calls
that run under another Unix user.

### 3. Add an early, bounded readiness gate

- Before media generation, verify CLI availability, selected profile readability,
  runtime write permission, required environment and provider configuration.
- Separately authorize one minimal live request using the real selected endpoint,
  model, auth and cron-like environment. No project documents or credentials in
  its prompt. Use a temporary empty working directory and a restrictive execution
  mode verified against installed CLI help; no tools, shell commands or publishing.
- Bound the process duration and capture sanitized results. Account for provider
  request cost/quota. Treat 401/403 as auth blockers, not content failures to retry
  for hours. Do not refresh or revoke unrelated ChatGPT credentials.
- File existence or `codex login status` alone is not sufficient acceptance proof.
  A passing request is also not a substitute for the actual visual-review test.

### 4. Validate and deploy narrowly

1. Unit tests: explicit profile selection, missing/unreadable auth, no provider
   fallback, source immutability, private permissions, missing environment keys,
   and secret-redacted errors. Use fake credentials/providers; no live quota.
2. Validate effective Compose and cron configuration without exposing expanded
   secrets. Confirm the host source is read-only and runtime homes are separate.
3. Approved live probe: run under the scheduler cron user/environment and the
   selected worker profile, not merely an interactive `docker exec` shell.
4. After explicit deployment approval, recreate only the necessary services. A
   Git pull does not update running container mounts or environment. Preserve
   volumes; do not run destructive Compose down/volume-removal commands.
5. Reinspect actual mounts, user, profile and health after recreation. Repeat the
   bounded probe; verify the SSH host auth/config contents and ownership unchanged.
6. Validate one existing representative video only with approval. Do not generate
   replacements, queue uploads or bypass quality/human-approval gates.
7. End-to-end pipeline and publishing recovery are a separate approved operation
   covered by the audit plan; this configuration task must not trigger them.

## Rollback

- If configuration or the probe fails, stop that test and restore the previous
  approved service configuration and private profile snapshots. Keep the new
  profile isolated for diagnosis; never replace the host's authoritative files.
- Recreate only affected services after approval and verify mounts/environment.
- Preserve the original ChatGPT profile. Re-selecting it for pipeline use requires
  explicit approval; do not implement automatic cross-provider fallback.
- Leave queue, media, YouTube credentials and publication records untouched.

## Acceptance criteria

- Selected pipeline provider/model/auth source is documented and explicitly chosen.
- The host SSH session and Docker pipeline resolve the approved OmniRoute settings
  consistently, or the user-approved split profiles are demonstrably isolated.
- Host auth/config is not mutated by container root; worker ChatGPT login remains
  privately recoverable and is not accidentally used by the scheduler.
- A bounded request succeeds in the current scheduler cron context with no 401;
  if it fails, capture a sanitized cause and stop without generating content.
- Runtime configuration survives an approved container recreation and token/key
  rotation has a documented controlled-refresh procedure.
- Tests retain strict quality, hash-bound approval and publication safeguards.
- No secrets committed; no videos published and no projects deleted by this task.
