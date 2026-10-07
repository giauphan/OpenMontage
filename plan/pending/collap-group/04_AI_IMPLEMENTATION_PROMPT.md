# AI Implementation Prompt — Complete the Multi-Shot Plan Group

## How to use

Give an implementation agent this instruction:

> Read `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`, and all numbered documents in
> `plan/pending/collap-group/`, then execute `04_AI_IMPLEMENTATION_PROMPT.md`.
> Implement the feature, not another proposal. Complete the milestones in dependency
> order, keep an evidence-backed task ledger, run validation, and report any blocked
> release gates honestly. Do not perform paid generation without explicit approval.

Status: implementation handoff; **not evidence that the feature is implemented**.
This document consolidates the three source plans and resolves their integration
ambiguities. Preserve those source documents; do not silently rewrite their scope.

## Recovery routing — audit of 2026-10-07

The initial implementation did not satisfy the full acceptance contract. Do not
restart from scratch or assume M0–M5 are complete because helper tests pass.

**Read `06_RECOVERY_PLAN.md` next and execute R0–R6 in its dependency order.**
Use this document for original scope and architecture; use document 06 for current
repair priorities and failure handling, and document 05 for current evidence.
Document 06 supersedes optimistic completion claims, not original requirements.

The old status report is retained as explicitly superseded history in document 05.
A task that fails acceptance is `failed` or `reopened`, never `verified` with a
hidden TODO. Missing paid-provider approval blocks live tests, not offline adapter
implementation, local media tests, or pipeline integration.

## 1. Mission and source authority

Implement a production-ready, resumable multi-shot AI video workflow inside
OpenMontage. It must generate and assemble **2..N independently generated clips**,
with explicit character/style identity, continuity, references, per-shot recovery,
ordered FFmpeg assembly, optional audio/captions, and machine-readable evidence.

Read these sources completely:

1. `01_MASTER_PLAN.md`: product scope, stages 0–13, persistence, safety, and DoD.
2. `02_DATA_CONTRACTS_AND_PROMPTS.md`: artifact structures, prompt sections, states,
   invalidation, media contract, provider error vocabulary.
3. `03_IMPLEMENTATION_TASKS_AND_ACCEPTANCE.md`: TASK 001–021, unit matrix,
   IT-01–06, E2E-01, fail-closed checks, performance and release gates.

Repository governance takes precedence over suggested standalone architecture in
these plans. This handoff supplies integration decisions; source acceptance criteria
remain required unless a conflict is explicitly recorded and resolved below.

Do not stop after scaffolding, fake-provider success, documentation, or a happy-path
concatenation. Deliver working tools, agent instructions, contracts, recovery,
tests, and operational documentation. Real-provider release checks remain separate
from offline implementation verification.

## 2. Mandatory integration decisions

### 2.1 Agent-led workflow, not a second Python orchestrator

The source plan suggests `src/orchestration/pipeline.py` and Python planning.
OpenMontage explicitly assigns creative planning, review, approval policy, and
stage advancement to the agent through manifests and director skills.

- Implement narrative/story/shot planning as agent instructions producing validated
  artifacts. Python validates, persists, builds prompts, schedules bounded technical
  jobs, probes media, and performs deterministic transformations.
- A job scheduler may manage submit/poll/download inside the approved assets stage;
  it must not choose creative policy, approve assets, or advance production gates.
- Prefer a dedicated `multi-shot` pipeline manifest and director skills reusing
  existing tools. Inspect the manifest schema first; follow its supported stages
  and canonical outputs rather than inventing a parallel stage system.
- Expose technical operations through registry-discovered `BaseTool` subclasses
  returning `ToolResult`. Reuse selectors and provider implementations.
- The source CLI is conceptual. Provide documented equivalents for create, plan,
  keyframes, generate, validate, normalize, assemble, finalize, status, retry, and
  regenerate. A `run` entry must not bypass agent decisions or human gates; route
  through the agent workflow or explicitly limit it to already-approved technical
  work. Do not create an unrelated `app` package solely to match example commands.

### 2.2 Keep canonical artifacts and Backlot visibility

Use `lib/checkpoint.py` workspace/checkpoint conventions and `project.json`.
Preserve canonical `artifacts/` outputs, `assets/`, `renders/`, checkpoint history,
partial-progress updates, and decision logging.

The source documents require named planning/job/raw/normalized/final files. Keep
those paths inside the project workspace as supporting artifacts, and map them to
canonical pipeline artifacts. Document the mapping and reference the actual files
from the asset manifest and render report. Avoid independently mutable duplicate
copies. If exposing the same final under `renders/`, use a documented publishing
step and verify that both references identify the same validated output.

The new run manifest describes technical shot/job state; it cannot override stage
checkpoints, human approvals, or the existing decision log.

### 2.3 Resolve contract inconsistencies explicitly

- Canonical request: document 02's structured `resolution` and `shot_policy`.
  Support document 01's flat example only through a tested boundary conversion,
  or return an actionable validation error; do not accept contradictory aliases.
- Default media target: 1080x1920, 30 fps, MP4/H.264/yuv420p; retained audio AAC,
  preferably 48 kHz. Honor other validated request profiles consistently rather
  than accepting a profile and silently rendering the default.
- Version all new schemas. Examples are illustrative, not complete fixtures:
  document 02's one-shot sample is invalid under the two-shot minimum.
- Story must cover beginning/hook, escalation, climax, and resolution/punchline.
  Require complete narrative coverage even though the example lists only three beats.
- Complete the shot schema with the master plan's fields omitted from its example,
  including continuity, time of day, references, and dialogue/narration (explicit
  empty values allowed where appropriate). Use stable character IDs throughout.
- Validate foreign keys, unique stable shot IDs, contiguous unique ordering, finite
  positive durations/FPS, valid dimensions/aspect ratio, and duration feasibility.
  Reject unsupported provider duration/reference combinations before spending.
- Model `STALE`, acceptance, and submission uncertainty explicitly; the example
  shot status list alone cannot express all required recovery behavior.
- Define whether `max_retries` excludes the initial attempt. Internally store an
  unambiguous attempt limit and persist every attempt, not only the latest error.
- Human review before paid work is **V1**, not the optional V2 feature listed in
  document 03. Existing approval and provider/runtime-selection rules still apply.
- Use FFmpeg for this workflow's normalization/assembly/mastering. Do not silently
  change an approved runtime or remove the repository's runtime presentation rules.

### 2.4 Continuity and concurrency must agree

Separate immutable **planned continuity snapshots** from **accepted continuity**.
Each job binds to a shot revision, prompt/reference hashes, and a continuity input
version. Never build a queued prompt from whichever global state happens to exist.

Default to serial generation for a continuity-dependent chain. Parallelize only
shots whose required continuity inputs are already accepted or are independent.
If implementing speculative generation against planned states, label it explicitly:
results cannot advance accepted continuity until predecessors are accepted and the
expected state matches. Invalidate incompatible speculative results.

Acceptance is an explicit recorded agent/user review outcome after technical
validation, not a synonym for “downloaded” or “ffprobe passed.” Apply state changes
once, in planned order, with atomic/version-checked persistence. FFprobe cannot
prove that a costume or kitchen mess is visually consistent.

A same-input retry retains the exact continuity input. Regeneration creates a new
revision and preserves earlier attempts. A material accepted end-state change
invalidates dependent later shots transitively; a media-only replacement with an
unchanged state does not gratuitously regenerate them. Stale assets cannot finalize.

### 2.5 Recovery must not cause duplicate paid jobs

Persist intent before submission and the provider job ID immediately when known.
Use provider idempotency/reconciliation capabilities where supported. On restart,
poll a known job rather than submitting another. For a crash after remote acceptance
but before local ID persistence, mark submission as uncertain and reconcile or ask
for authorization; do not promise exactly-once behavior a provider cannot offer.

Retry a failed download against the existing successful job before regenerating.
If a raw file is deleted, re-download when possible. Regenerate only the affected
shot when necessary and approved, then rebuild its dependent media. This satisfies
single-shot recovery without interpreting the source example as mandatory re-spend.

## 3. Start with a repository audit and task ledger

Before edits, inspect the working tree and preserve unrelated work. Read the actual
implementations, schemas, tests, and development commands. Starting points already
present in this repository include:

- `lib/shot_prompt_builder.py`: existing cinematography prompt helpers; preserve
  their public behavior and add a separate explicit continuity-aware entry point.
- `lib/checkpoint.py`, `lib/pipeline_loader.py`, `lib/paths.py`,
  `lib/media_profiles.py`, `lib/providers/`.
- `tools/base_tool.py`, `tools/tool_registry.py`, `tools/cost_tracker.py`.
- `tools/video/video_selector.py`, provider tools in `tools/video/`,
  `tools/video/video_stitch.py`, `tools/video/video_compose.py`.
- `pipeline_defs/cinematic.yaml`, existing director skills, `schemas/artifacts/`,
  `schemas/pipelines/pipeline_manifest.schema.json`, `tests/contracts/`.
- `PROJECT_CONTEXT.md`, `requirements.txt`, `requirements-dev.txt`, `Makefile`.

These are inspection points, not claims that they already satisfy the new feature.
Discover other relevant audio, subtitle, validation, and provider helpers before
adding duplicates. Check for scoped instructions in every edited subtree.

Create `05_IMPLEMENTATION_STATUS.md` beside this prompt with:

| Source requirement | Status | Code/docs paths | Tests/evidence | Remaining blocker |
|---|---|---|---|---|

Include TASK 001–021, IT-01–06, E2E-01, performance checks, security, and all ten
release gates. Use `not_started`, `in_progress`, `implemented_unverified`,
`verified`, or `blocked`. Record design deviations, exact validation commands,
exit outcomes, skipped tests and reasons. A skipped test is not a pass.

## 4. Dependency-ordered implementation milestones

### M0 — Integration skeleton and schemas (TASK 001–002)

- Add versioned request/story/character/style/shot/continuity/job/run schemas and
  validation consistent with the repository's existing schema/model stack.
- Implement safe project initialization, stable filenames, atomic persistence,
  project-level mutation locking/version checks, and revision/attempt history.
- Reject path traversal, absolute-path injection, unsafe IDs, non-finite numbers,
  duplicate IDs/orders, invalid references, and impossible durations before jobs.
- Add the pipeline manifest, initial director contracts, and documented operations.
- Preserve existing projects and APIs; do not migrate user work silently.

Gate: schema/workspace/manifest tests pass for valid 2-, 25-, and configurable
30-shot plans and invalid boundary cases. No live API calls required.

### M1 — Planning, continuity, prompts, references (TASK 003–008)

- Implement director instructions for story, immutable identity versus mutable
  state, style/environment locks, single-dominant-action shots, and ending states.
- Provide validated example fixtures including a six-shot Mochi plan.
- Implement immutable continuity inputs, acceptance records/versioning, and stale
  propagation. Persist expected and reviewed outcomes without conflating them.
- Build full self-contained prompts with every document 02 section, explicit
  initial state for shot one, every participating character lock, shot ID/duration,
  environment, props, ending state, and no unresolved placeholders.
- Track reference provenance/content hashes and shot ownership. One-reference
  providers receive a shot keyframe derived from the character master; multiple-
  reference providers receive supported identity/keyframe/environment inputs.
- Block unreadable/missing/mismatched required references or rejected identity.
  Use explicit review evidence when automated identity checking is unavailable.

Gate: first/middle/last prompt snapshots; missing-lock/reference rejection;
repeat-acceptance idempotence; failed-shot non-mutation; stale-chain tests pass.

### M2 — Provider jobs and crash-safe recovery (TASK 009–011, 019–021)

- Implement a provider-neutral submit/status/download boundary and deterministic
  fake provider. Integrate at least one real existing registry provider, chosen
  after checking its supported references, durations, job lifecycle, and skills.
- If its existing execute call hides polling, introduce a backward-compatible
  durable lifecycle adapter rather than falsely claiming recovery across crashes.
- Bound remote jobs and downloads separately; configurable default concurrency
  2–3, with continuity eligibility independently limiting dispatch.
- Map every document 02 error class. Retry only retryable failures with capped
  exponential backoff/jitter, provider retry-after support, deadlines and attempt
  history. Do not loop on auth, invalid input, safety refusal or permanent quota.
- Use bounded, atomic downloads; never mark partial/empty files as complete.
  Validate provider URLs, avoid credential leakage, and keep request logs redacted.
- Hash canonical inputs including provider/model/settings and referenced file
  contents. Persist invalidation metadata before parallel work begins.
- Add status, retry-one, regenerate-one and resume operations. Preserve valid work,
  reserve/reconcile costs, and serialize manifest/state writes safely.

Gate: fake-provider 429/500/auth/safety/download/timeout tests; concurrency <=3 for
20 independent jobs; out-of-order completion; crash/uncertain-submit recovery;
unchanged completed shots reused; single-shot revision tests pass.

### M3 — Media validation and ordered assembly (TASK 012–015)

- Reuse or extend ffprobe/FFmpeg helpers with timeouts and structured errors.
  Parse rational FPS safely; probe metadata and perform a decode validation where
  necessary. Metadata readability alone is not proof of an uncorrupted stream.
- Enforce configured file-size and per-shot duration tolerances. Reports include
  the input hash/revision so old success reports cannot validate changed files.
- Normalize resolution, explicit fit/pad/crop policy, FPS, codec, pixel format,
  time base and audio layout. Do not distort framing silently.
- Choose and document source-audio policy: strip it consistently for silent base
  clips, or normalize all tracks and supply silence where needed. Mixed layouts
  must not break concatenation. Keep planned and actual duration accounting.
- Build concat input only from accepted, current, validated shots in plan order;
  reject missing/extra/duplicate/stale entries. Hard cuts are the default.
- Re-probe normalized and assembled output; compare base duration to normalized
  clip sum and target duration. No implicit time stretching or freezing to hide
  an infeasible plan; report the discrepancy and require approved correction.

Gate: IT-01/IT-03 and missing-middle-shot rejection pass with locally generated
fixtures of differing codecs/resolutions/FPS, including silent/audio mixtures.
Use visibly distinct fixture clips and inspect boundary frames to prove order;
matching total duration is not sufficient evidence.

### M4 — Optional audio, final master and completion (TASK 016–018)

- Support all-audio-disabled operation, supplied/generated narration, music, SFX,
  optional subtitle files, and configured burn/mux modes through existing tools.
- Define loudness target, narration priority, ducking, fades, source-audio policy,
  silence handling and language/font requirements. Never assume shot audio usable.
- Bound audio loops, padding, encoding runtime and final output duration explicitly
  so a short base video cannot trigger unbounded audio muxing.
- Audio/subtitle changes invalidate final master/report only, not generated shots.
- Write the master atomically, validate decode/duration/resolution/FPS/audio,
  provenance and complete shot coverage, then publish the final report/artifacts.
- A current mandatory failure prevents COMPLETED even if an older final exists.
  Preserve the old render as history, not as proof of current success.

Gate: silent, narration, music ducking, SFX, subtitle and duration-bound tests pass;
missing mandatory assets, failed/stale shots, invalid reports and corrupt outputs
cannot transition to COMPLETED.

### M5 — Full workflow, regression tests and documentation

- Finish all director skills, registry contracts, manifest integration, canonical
  artifact mappings, approval checkpoints, reviewer criteria and progress updates.
- Complete TASK 019–021 across the actual tool workflow, not only helper functions.
- Execute IT-01–06, six-shot/30-second fake-provider integration, crash/resume,
  regeneration with unchanged and changed continuity, and concurrency testing.
- Test all invalidation rules: story change recomputes affected prompts; character
  changes invalidate dependent keyframes/prompts/video; style invalidates applicable
  references/prompts/video; one prompt or clip invalidates only dependent media;
  material end-state changes additionally invalidate later continuity consumers;
  narration/music/subtitles preserve all valid video work.
- Add operator docs with verified command examples, prerequisites, artifact paths,
  expected outputs, error recovery, provider limitations and cost/approval policy.
- Record timing/attempt/provider/error metrics requested by document 03 without
  secrets, signed URLs or sensitive raw payloads.

Gate: focused tests and relevant existing regression suites pass. Report unrelated
baseline failures separately rather than changing unrelated functionality.

### M6 — Real-provider release verification

Only after explicit provider/model/reference/runtime/budget approval:

1. Run a real two-shot project end-to-end.
2. Run the six-shot, 30-second, 9:16, 1080x1920, 30 fps Mochi acceptance project.
3. Inspect identity/clothing/environment/mess persistence, action, cut order and
   story readability. Store review outcomes; technical metadata cannot replace this.
4. Demonstrate resume and one-shot regeneration with hashes/job IDs showing reuse.
5. Attach final ffprobe/decode evidence, cost accounting and all required reports.

If credentials, quota, approval or runtime dependencies are unavailable, complete
all possible offline work and mark these gates BLOCKED. Do not generate paid
content as a surprise, substitute a vendor/runtime, or call V1 production-ready.

## 5. Execution discipline and parallel work

Proceed milestone by milestone; do not repeatedly ask whether to continue ordinary
implementation. Stop for genuine architectural ambiguity, destructive migration,
paid actions, approval gates or a provider limitation that changes the deliverable.

If delegating, agree on schemas and lifecycle interfaces first. Assign disjoint
write sets: contracts/persistence, prompt/reference helpers, provider jobs, media,
and integration/docs. Keep one owner for shared registry/schema/manifest edits.
Integrate each slice and run its tests before declaring the milestone verified.

No new distributed queue, database service, timeline UI, auto-provider fallback,
visual similarity ML system or additional rendering framework in V1. Reuse existing
dependencies unless a concrete requirement justifies an addition. Do not commit,
change branches, move source plans to archive, or erase old assets without permission.

## 6. Evidence and completion report

Discover exact test/lint commands from current repository configuration; do not
invent commands or report tests that were not run. Keep CI offline by default;
explicitly mark network/paid and FFmpeg-dependent tests. Missing FFmpeg may justify
a local skip, but media release gates still require execution somewhere supported.

Before finishing, reconcile every TASK 001–021 and source release criterion against
`05_IMPLEMENTATION_STATUS.md`. Include:

- Implemented capabilities and changed paths.
- Requirement-to-test coverage and exact command outcomes.
- Demonstrated retry, resume, concurrency, continuity and invalidation behavior.
- Real-provider adapter supported capabilities and known lifecycle limits.
- Evidence paths for reports and final media, if actually produced.
- Remaining blockers, skipped tests, and the precise action needed to unblock each.
- Separate conclusions: **implementation verified offline** and **V1 release-ready**.

Do not claim completion from the existence of files, schemas or a final MP4 alone.
A production-ready claim requires every source release gate, including both real
provider scenarios and human visual acceptance, to have recorded passing evidence.
