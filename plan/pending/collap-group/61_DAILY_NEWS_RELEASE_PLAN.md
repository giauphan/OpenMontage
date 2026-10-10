# Daily-news pipeline: supervised implementation and release plan

## Outcome and scope
Produce current, factually reliable Vietnamese daily-news videos at a publishable quality level, then activate a monitored schedule with safe recovery. Passing code tests alone is NOT completion.

The existing multishot plan remains an unfinished workstream; it is not the entire daily-news production workflow. Preserve its implementation and evidence. Do not require AI-generated cinematic shots where verified news footage, licensed imagery or data graphics communicate facts more accurately. Synthetic reconstructions must be clearly labeled and must never appear to be evidence of real news events.

Status as reviewed at `edd7826`: plan writing is complete; implementation and production acceptance are NOT complete. Native Luna is the approved coding route. Evidence 2.0 classification/corroboration checks, captions, quarantine, frozen-entrypoint mode, and the bounded acceptance controller are implemented. Source capture/editorial review integration, immutable approved scripts, an independently edited Reels rendition, positive complete rehearsals, human sample approval, and authorized deployment/cron observation remain open. This document does not authorize spending, publication, deployment, or cron activation.

## Detailed implementation handoff

See [daily-news completion contract](../../../docs/daily-news-completion-plan.md) for the 2026-10-10 deep audit at `4ab66ff`, prioritized source/editorial/media/operations findings, W0–W9 work packages, negative-test matrix, local Luna assignment template, migration safeguards and authoritative research references. It expands C1–C5 and N1–N7 below without declaring implementation complete. In particular, source-date integrity, caption/script comparison, template provenance, whole-run locking, durable monitoring, spend enforcement and unknown-upload reconciliation need explicit qualification; missing rehearsal bundles are not the only remaining work.

## Current evidence and closure sequence

Repository investigation, not new runtime validation: the latest recorded broad regression is 1,329 passed, 7 skipped, 19 subtests. The separate strict controller ran 240 tests with zero failures/errors/skips, then correctly stopped at `blocked_missing_rehearsal_inputs`; resume reused the verified result without another attempt. See [acceptance-loop usage and evidence](../../../docs/daily-news-acceptance-loop.md). This establishes tested safeguards, not successful current-news production.

Work in the following order. Reuse the existing pipeline, checkpoint system, validators and rehearsal mode; do not add another generic orchestration layer.

### C1 — Resolve the reviewed-script workflow conflict (implementation first)
- **Observed problem:** `scripts/prompts/director_generate.prompt.md` requests script and compositions together, while `lib/news_evidence.py` binds reviewed evidence to the exact `script_vi.json` bytes. The daily shell validates evidence only after the director returns. A rewritten script invalidates pre-supplied evidence; there is no complete upstream review handoff in this path.
- **Outcome:** separate script drafting/review from composition. Freeze the canonical approved script before downstream work; composition-only and repair paths must not rewrite it or self-approve evidence. Reuse `lib/checkpoint.py` human-gate/history behavior rather than treating a nonempty reviewer field as authenticated approval.
- **Acceptance:** unchanged approved input reaches composition; missing/pending/rejected approval blocks before generation; script mutation or source revision invalidates approval; retry preserves review history. Record measured narration/scene timing separately where possible so timing repairs do not silently rewrite editorially approved content. Reconcile the existing byte-hash contract explicitly if artifact boundaries change.

### C2 — Produce real source bundles and a review handoff (implementation plus editor input)
- **Observed problem:** NewsNow fetching/selection and a research brief are not frozen underlying article evidence. No complete capture-to-review workflow was found in the inspected news modules; the evidence validator deliberately neither retrieves nor approves sources.
- **Outcome:** attach bounded article capture and provenance packaging to selected candidates: actual URL, publication/update/retrieval times, original/extracted content hashes, relevant excerpts, rights/attribution notes, and a claim-review worksheet. Capture must respect access restrictions; missing dates, inaccessible sources, conflicts or extraction failure remain explicit blockers. Review outcomes come from the authorized editor, never the capture agent.
- **Acceptance:** source outage, redirect/path safety, undated/stale inputs, contradictory claims, duplicate topic/source and correction cases fail visibly; authentic captured content can be reviewed and bound to the frozen script. Use an explicitly chosen freshness policy. The agent can prepare the capture/packaging workflow; the user need not manually manufacture every bundle.

### C3 — Make Reels a separately reviewed editorial rendition (implementation)
- **Observed problem:** the daily materializer uses a 58-second trim/copy of the full narration and overwrites `narration_reels.mp3`; the director prompt asks for an identical shortened structure. This does not meet N6's substantive-edit requirement.
- **Outcome:** give Reels its own approved script/cut, narration, measured timing, caption alignment and evidence coverage. Preserve supplied valid Reels audio instead of replacing it with truncated full narration. Retain existing provider choices; paid regeneration still requires approval.
- **Acceptance:** a deliberately different Reels script and audio survive materialization; each rendition has matching audio-bound captions and source coverage; endings are complete, and changes to either script invalidate its dependent evidence/assets. Verify names, dates and quantities against approved wording, not just ASR timestamps.

### C4 — Close positive rehearsal and recovery evidence (execution after C1–C3)
- **Inputs:** complete, honestly reviewed source/media bundles; known licensed assets; exact runtime revision; explicit freshness policy. Synthetic fixtures remain test-only and cannot establish factual or human acceptance.
- **Outcome:** first prove one positive full downstream rehearsal, then three successive scheduled-equivalent runs with distinct topics and one injected failure/recovery/resume. The existing frozen mode requires exactly three unique projects per invocation; do not count three projects in one invocation as three successive runs.
- **Acceptance:** real full/Reels MP4s, unchanged strict quality gates, captions/audio checks, report and asset hashes, preserved failed evidence, no duplicate submissions/charges or lost state. Confirm cached ASR and browser/GSAP/font/media dependencies work under the intended offline network policy; provision missing dependencies separately rather than silently enabling downloads. Frozen mode skips acquisition/director/TTS; separately verify those boundaries before calling the result source-to-video E2E.
- **Loop:** consume `next-action.json`; repair locally with Luna, synchronize exact files, rerun remotely within bounded attempts/time. Do not lower tests/thresholds or repeat unchanged deterministic failures. Exhausted budgets start a separately supervised cycle with old evidence retained.

### C5 — Editorial acceptance and stable activation (explicit approval)
- Present three representative Vietnamese samples and compare against an agreed reference. Obtain factual, rights, narration, caption and visual approval; do not derive it from fixture replies.
- Present exact revision/image, generation-only canary, timezone/schedule, volume, cost cap, alert recipient and rollback before stable deployment. Publication is a separate permission. Observe a real authorized cron window and record its actual outcomes; tests cannot simulate operational stability.

**Decisions still needed before the affected actions:** topic/sensitivity policy, source-age limit, approved assets/providers and spending cap, quality reference/sample review, and deployment/publication/observation authorization. These decisions do not block implementing C1–C3 safely with test fixtures; they do block claiming live release completion.

## Historical baseline (initial observations, not current status)
The bullets below preserve the starting evidence. Later fixes and the current closure sequence supersede their implementation status; do not interpret the old failure counts or deletion behavior as the latest code.
- Local Claude settings route requests to localhost:20128. No settings or credentials were changed or exposed during inspection.
- Requested CLI model and result summaries say claude-haiku-4-5-20251001, but assistant events in recent logs say gpt-5.6-luna or gemini-3.5-flash-lite. Exact Haiku execution is NOT verified. Preserve affected work as provenance-unverified; do not silently delete or relabel it.
- Recovery branch: task/multishot-recovery, last committed revision ee69a13. There is additional uncommitted local implementation and partial documentation.
- Last multishot verification: 346 passed, 2 failed. Both E2E fixtures fail continuity schema validation. Additional invalid fixture fields and missing finalize profile were found in review. Earlier full green tests apply only to an earlier revision.
- scripts/run_daily_news_pipeline.sh targets Vietnamese full/reels videos, described as 120s/60s; default timezone Asia/Ho_Chi_Minh. It fetches NewsNow, generates, renders, validates and writes publishing metadata.
- scripts/run_strict_docker_publish.sh is the server/container entry point, with disk thresholds, heartbeat and staged publishing.
- deploy/openmontage.cron proposes generation at 06:00 Vietnam and Instagram slots 09:15/14:15/21:15. Its YouTube-only comment conflicts with Instagram entries. Actual installed cron/container state has NOT been inspected in this task.
- A quality-failure branch at scripts/run_daily_news_pipeline.sh removes the failed project directory. This must be reconciled with quarantine/recovery requirements before release.

## Non-negotiable execution rules
All application source, tests, scripts, manifests and agent instructions are authored locally in an isolated task worktree. Claude coding agents run locally only. Server actions are controlled source synchronization, setup, execution, tests, renders and read-only runtime inspection. Pipeline directors may produce project artifacts/compositions at runtime, but must not patch repository source or deployment configuration.

Preserve original local and stable server state. Verify exact source revision/hashes in an isolated remote test checkout before validation. Never use live queues, publication records or production media for tests. Never disable hooks or validators, change model/provider silently, publish, or activate cron to make a test pass.

## Supervisor control loop
1. Confirm branch, clean/dirty state, write ownership and model route before each task.
2. Prepare one outcome-focused prompt: problem, evidence, exact write scope, constraints, expected behavior and negative acceptance cases.
3. Use the approved native Luna subagent locally in the authorized task worktree. The original Claude/Haiku route remains historical and is not a prerequisite for this approved route. If a future task explicitly requires that route, verify provider/model identity rather than relying on CLI flags or self-report; never silently substitute models.
4. Use 15-30 minute tasks with 20-40 turn caps as ceilings, not estimated completion promises. Start serially. Parallel tasks require disjoint write scopes and healthy service capacity.
5. Inspect early progress. Repeated reads without edits, permission-looping or compaction thrashing trigger a smaller task, not an unbounded rerun. On 429/503, use bounded retries and preserve state; never substitute models.
6. Review actual diff, then synchronize selected local source to isolated server and run narrow tests, followed by broader regressions. Validate negative scenarios and real media; never accept an agent success claim alone.
7. Feed exact failures back to the same scope. Record command, revision/hash, results, skips, remaining gaps and logs. Mark tasks verified only when acceptance evidence exists.
8. Continue eligible tasks without repeated permission requests. Pause only for unavailable service/access or protected decisions: route/model changes, spending, publishing and stable deployment.

## Work packages

### R0 — Original Haiku route investigation (superseded for current Luna work)
The following original acceptance criteria are retained for provenance only. They do not block the approved native Luna route and do not establish that the old Haiku route was verified.

Inputs: redacted routing inspection, assistant-event model mismatch, local Claude CLI configuration.
Outcome: an approved route whose request and returned assistant-event model identity consistently identify Haiku 4.5, with no automatic cross-model fallback. Confirm gateway mapping through trusted configuration/provider evidence; flags alone are insufficient.
Scope: read-only diagnostics first. Any route/settings/auth change requires approval; no secrets in prompts, artifacts or reports.
Acceptance: a no-edit canary confirms route health and identity; supervisor records sanitized evidence. If identity remains inconsistent, keep coding blocked.

### R1 — Reconcile provenance and finish multishot recovery (several bounded tasks)
Inputs: original TASK 001-021 plans, recovery worktree, 60_MODEL_IDENTITY_BLOCKER.md and current failures.
Outcomes: independently review affected uncommitted code with verified approved agent; repair E2E fixture schemas and real output paths; finish cost-ledger consistency, reference/revision invalidation, public generation/finalization and documentation.
Acceptance: registry-driven 2-shot/10s and 6-shot/30s offline runs traverse actual human-gated checkpoints; real FFmpeg output validates; resume causes no duplicate submit or charge; corrupted/stale inputs fail closed. Full task ledger distinguishes implemented, verified, unverified and live-blocked requirements. Run full contracts after focused tests.

### N1 — Daily production and deployment audit (15-30 minutes, read-only)
Inputs: daily script, strict orchestrator, cron file, news tools, validators, publishing guards and relevant tests.
Outcomes: map actual source-to-render-to-publish path and runtime director permissions; inspect installed schedule/container revision only with read-only server commands; inventory configured providers by availability, never credentials.
Acceptance: report exact deploy revision, timezone, enabled platforms, budgets, source freshness, run history/heartbeats and recovery paths. Identify discrepancies between repository config and active runtime. Do not infer activation from a cron file.

### N2 — Factual-news and topic-selection gates (one or more 15-30 minute tasks)
Outcome: every script carries claim-to-source provenance, publication/update timestamps and freshness policy; reject duplicated topics and stale or unverifiable claims. Separate reported facts, attribution, inference and opinion. Require authoritative corroboration for consequential claims; do not invent quotes, numbers or citations.
Acceptance: fixtures cover fresh/stale feeds, conflicting reports, source outage, repeated topics, unsupported claims and correction handling. A failed factual gate prevents publication even if rendering succeeds. Numerical stale-age limits must be explicit production decisions, not hidden defaults.

### N3 — Recoverable execution and scheduling (several bounded tasks)
Outcome: bounded retries/timeouts, cross-process locks, durable idempotency, atomic state, conservative cost reservations, heartbeat/alerts and restart-safe work queues. Quarantine failed projects rather than deleting review evidence. Fail-closed reviewer behavior; no stale artifacts accepted after timeout.
Acceptance: tests exercise restart, overlap, 429/503, unknown paid submission, low disk, expired platform credentials and interrupted upload. No duplicate upload/publish, no accidental budget reset, no loss of failed evidence. Tests operate only on isolated temporary state.

### N4 — Video quality and editorial treatment (several bounded tasks)
Outcome: enforce the quality contract below and align visual treatment with each story. Select providers and composition runtime explicitly. If both Remotion and HyperFrames are available, present both before locking runtime. Existing HyperFrames use is evidence, not automatic new approval. Discuss templated versus bespoke treatment as a separate choice.
Acceptance: genuine media checks plus visual/audio review, with current-source topic examples. Avoid validator-only optimization such as artificial motion to satisfy frame-change thresholds. Failed criteria create actionable repair work and preserve evidence.

### N5 — Isolated complete rehearsals (bounded runs)
Outcome: exercise the actual daily entry point, not only helper tests, with isolated queues and publication disabled. Use frozen licensed assets/offline transports first; separately approved live canary later.
Acceptance: at least three successive scheduled-equivalent dry runs with distinct topics, plus one injected failure/recovery; verify freshness, output duration, audio/subtitles, cost accounting, no duplicates and useful alerts. Record exact revisions, artifacts and results. Do not simulate elapsed cron reliability and call it a real multi-day soak.

### N6 — Human quality acceptance (approval gate)
Deliver three representative Vietnamese news samples: a breaking update, a fact/data-heavy story and an explanatory story. Full/reels versions must be substantively edited, not simply truncated.
Acceptance: factual review and rubric below pass; user approves the real rendered samples. Compare against a user-provided reference or an agreed previous output. No claim of improved quality without that comparison. Live media spending requires an agreed cap first.

### N7 — Controlled activation and observation (approval gate)
Before action: present exact commit/image, target checkout/container, cron diff/timezone, topic policy, daily volume, platforms, spend limits, alert destination and rollback commands. Preserve stable baseline and queues.
Activation: generation-only canary first; publication requires separate explicit authorization. Confirm next scheduled execution, heartbeat, output and alert behavior. A real observation window is recorded separately from offline tests; suggested 24-72 hours, subject to approval.
Acceptance: no duplicate production, budget breach or bypassed quality gate; rollback demonstrated safely. Only then mark operational activation complete.

## Proposed publishable-quality contract
These are acceptance targets, not claims about current videos. Confirm numerical thresholds during the quality-spec task.
- Factual: all substantive factual claims traceable to accessible dated sources; zero fabricated quotes, entities or numbers; uncertainty and synthetic imagery labeled; corrections supported.
- Editorial: clear opening, explain what happened and why it matters, useful context and limitations; no misleading sensationalism or unsupported prediction.
- Vietnamese: natural script and intelligible narration; verify names, acronyms, dates and quantities against the approved text.
- Visual: evidence-relevant, licensed/attributed media; no placeholder frames, unreadable text, unintended freezing or stretched imagery. Sources readable at phone size; safe margins and restrained transitions.
- Audio: intelligible voice, no clipping/dropouts or abrupt endings; music does not mask speech. Proposed web target around -16 LUFS integrated and true peak <= -1 dBTP, adjusted to confirmed platform requirements and measured on actual output.
- Captions: valid Vietnamese glyphs, accurate wording/numbers, synchronized phrases, no clipping or overlaps. Proposed timing error <= 250ms on sampled speech; human readability matters beyond timing.
- Delivery: approved resolution/aspect/fps, duration tolerance, decode integrity, expected audio stream and correct opening/ending. Preserve render profile/provenance and final content hashes.
- Human rubric: accuracy, editorial value, narration/audio, visual relevance/design and caption readability each >=4/5, with zero critical factual, rights or safety issue. Automated checks cannot substitute for this review.

## Decisions required before live production
1. Coding route: native Luna is already approved. No further route decision is needed for current implementation; any future provider/gateway change still requires authorization.
2. Confirm target: Vietnamese daily news; topic categories and excluded/sensitive subjects; intended audience.
3. Confirm format/volume: existing 120s full + 60s reels and proposed three topics/day are candidates, not approved requirements.
4. Confirm daily/per-video spend cap, providers, source/asset rights and render runtime.
5. Confirm generation-only versus auto-publication, channels, schedule/timezone and alert recipient.
6. Supply a quality reference or nominate an existing output for comparison.

## Definition of done
All applicable implementation acceptance cases verified; provenance/model constraint satisfied; daily dry runs and failure recovery evidenced; real sample videos approved; separately authorized schedule activated and observed; operator runbook and rollback available. Until then report partial progress and concrete blockers, never simply DONE.

## 2026-10-09 evidence and caption checkpoint
The initial Haiku route blocker is superseded by approval to use native Luna; this records route approval, not a claim that prior model-identity evidence was verified. Evidence and caption implementation/validation details and limitations are recorded in [`docs/daily-news-evidence-caption-checkpoint.md`](../../../docs/daily-news-evidence-caption-checkpoint.md). Summary: explicit source-age policy remains mandatory with no default; structural provenance checks do not prove semantic truth, source authenticity, or reviewer-attestation authenticity. Cached-only small ASR captions are an independent transcript path for full and reels, with no script comparison or human verification. The adapter rejects legacy captions and requires the main-root start-0 paused timeline; it inserts timed clips and replaces only its own block idempotently.

Remote isolated QA project `projects/qa-caption-installation.Y3Ow5X` recorded 0 lint errors/warnings, browser validation with no console errors and 12 WCAG text elements, and inspect with 0 issues at 0.7, 1.7, 3.4, and 9.5 seconds. A 10-second silent synthetic caption fixture rendered an MP4 of 66.8 KB. Supervisor contact-sheet inspection found the first cue at 0.7 and 1.7 seconds, the second at 3.4 seconds, and no captions at 9.5 or 9.7 seconds. This is a limited visual fixture check, not speech-accuracy or human editorial acceptance. The completed final remote broad regression reported 1249 passed, 7 skipped, 19 subtests in 142.01 seconds; JUnit results: `projects/render-freeze-rehearsal/qa/evidence-caption-final-results.xml`. An initial shell syntax regression and fixture-root missing start were caught and fixed.

No stable checkout was changed; no spending, publishing, deployment, or cron activation occurred. Deployment is not authorized by this document. Remaining actual release gates are N2 editorial taxonomy and corroboration, N5 transport plus three rehearsals and failure recovery, N6 human review and reference comparison, and N7 budget/deploy/cron observation. New configuration without explicit policy and evidence blocks production; templates may be rejected until legacy captions are migrated. Reels still truncates existing audio rather than performing a substantive editorial edit.

## 2026-10-09 replay follow-up — partial, not done

Evidence 2.0 declares corroboration classifications and guards distinct source IDs, publishers, normalized URLs, and content hashes. `authority_attested` is a classification declaration, not authentication or proof of truth. The public selector/reviewer is injected; the test-only marker is rejected for release. The replay exercised an executable component, not the full shell entrypoint, and performed no generation or rendering. QA copied a historical MP4 and ran actual technical checks and frame extraction on the copy. QA metadata is now always synthetic; source metadata is not copied.

Remote broad regression was 1,284 passed, 7 skipped, 19 subtests in 140.15s, **before** the final helper metadata fix. After the fix, targeted tests were 25 passed in 0.74s. Provenance: one agent initially ran evidence tests locally (51 passed); the supervisor reran revised code remotely. These are distinct runs and the local initial result is not the remote revised-code result. A real Docker replay used `--network none`, read-only `/app`, and external output `/home/ubuntu/OpenMontage-daily-news-replay-qa/probe-20261009-02`. The valid component passed; malformed missing `audio_sync` failed and preserved the first report (SHA-256 `2a8be06bb383545db1d66f638f21fbe5f5336ce1d5743c99dade1f4391da4975`).

N5 remains incomplete: the full daily entrypoint still needs deterministic selection, director, TTS, ASR, render, and reviewer exercised across three distinct complete runs, plus recovery. N6 representative human-reviewed examples remain incomplete. N7 approval, budget, and observation of current sources/runtime remain incomplete. This is a task-branch-only documentation update; it does not establish stable-checkout readiness or release completion.

## 2026-10-09 rehearsal-bundle follow-up — partial, not done

The actual `scripts/run_daily_news_pipeline.sh --rehearsal-bundle` mode consumes exactly three frozen, unique evidence bundles in a marked stage isolating environment and live state; an explicit source-age policy is mandatory. Live fetch, production, director, and TTS are disabled. Existing downstream validators and caption/render stages are shared, but a positive complete render was not run. Atomic marked copies preserve interruption state. Strict fixture review requires both markers; publication gates reject fixtures carrying either marker.

A real shell subprocess test supplied three invalid evidence bundles. Real validators rejected and quarantined all three; no external providers were invoked. Report successful, failed, and quarantined counts plus exit status. Rehearsal success requires all three bundles to succeed. Remote final regression: 1298 passed, 7 skipped, 19 subtests in 144.48s; JUnit: `projects/render-freeze-rehearsal/qa/daily-entrypoint-regression-results.xml`.

Selection acquisition was skipped; this is not an all-source-to-video E2E run. N5 remains open pending three complete successful runs and real recovery/resume using complete frozen input bundles. N6 human content/sample approval and N7 policy, budget, deployment, and real observation remain open. No runtime source change, stable deployment change, spending, or publication is part of this progress update.
