# Daily-news pipeline: supervised implementation and release plan

## Outcome and scope
Produce current, factually reliable Vietnamese daily-news videos at a publishable quality level, then activate a monitored schedule with safe recovery. Passing code tests alone is NOT completion.

The existing multishot plan remains an unfinished workstream; it is not the entire daily-news production workflow. Preserve its implementation and evidence. Do not require AI-generated cinematic shots where verified news footage, licensed imagery or data graphics communicate facts more accurately. Synthetic reconstructions must be clearly labeled and must never appear to be evidence of real news events.

Status: Native Luna coding route approved; this supersedes the initial Haiku-route blocker. Implementation and isolated validation are partial, not release-complete. N2 editorial taxonomy/corroboration, N5 transport and three rehearsals/failure recovery, N6 human review/reference, and N7 budget/deployment/cron observation remain open. Deployment, live paid generation, publication, and cron activation are not authorized by this document.

## Verified baseline
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
3. Invoke local Claude with the explicitly approved model; inspect assistant-event model identity, not only CLI flags or usage summary. Stop on conflicting identity. Self-reported model names are not proof.
4. Use 15-30 minute tasks with 20-40 turn caps as ceilings, not estimated completion promises. Start serially. Parallel tasks require disjoint write scopes and healthy service capacity.
5. Inspect early progress. Repeated reads without edits, permission-looping or compaction thrashing trigger a smaller task, not an unbounded rerun. On 429/503, use bounded retries and preserve state; never substitute models.
6. Review actual diff, then synchronize selected local source to isolated server and run narrow tests, followed by broader regressions. Validate negative scenarios and real media; never accept an agent success claim alone.
7. Feed exact failures back to the same scope. Record command, revision/hash, results, skips, remaining gaps and logs. Mark tasks verified only when acceptance evidence exists.
8. Continue eligible tasks without repeated permission requests. Pause only for unavailable service/access or protected decisions: route/model changes, spending, publishing and stable deployment.

## Work packages

### R0 — Verify coding-model route (blocking; 15-minute investigation)
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
1. Coding route: authorize a gateway correction or a session-local direct Anthropic route for verified Haiku; do not change settings silently.
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
