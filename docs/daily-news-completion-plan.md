# Daily-news completion contract and implementation handoff

## 1. Status, scope and evidence

**2026-10-10; audited baseline: `4ab66ff0d1288a98925ac0c0904a5edeb3618710`.**
This is a detailed implementation plan, not a declaration of completion or authorization to deploy. The goal is publishable, factually supported Vietnamese daily-news full/Reels videos, followed by a monitored, recoverable production schedule. It extends [master plan 61](../plan/pending/collap-group/61_DAILY_NEWS_RELEASE_PLAN.md), not replaces the original multishot requirements.

Investigation combined repository inspection, three read-only Luna reviews (editorial, media, operations), and the authoritative references in section 10. Findings below are source-level observations or identified risks, **not newly reproduced runtime failures**. Recheck symbols at the implementation revision; line numbers can move. This is a targeted audit, not proof that all project defects have been discovered.

Historical validation at the planning baseline (superseded for changed slices by the implementation checkpoint below):

- Broad regression: **1,329 passed, 7 skipped, 19 subtests**. Skipped coverage is not acceptance evidence.
- Separate strict acceptance-controller suite: **240 passed, zero failures/errors/skips**.
- Controller status: `blocked_missing_rehearsal_inputs`, `plan_complete: false`; resume retained attempt count 1. Recorded state: `/home/ubuntu/OpenMontage-daily-news-acceptance/loop-20261010-02`.
- Historical full/Reels renders passed technical checks but contain unsupported archived content: **not publishable**. Synthetic caption renders and component replay prove narrower behavior only.
- Evidence v2, quarantine, caption installation, frozen daily-shell entrypoint and bounded verification controller exist. The controller consumes rehearsal reports; it does not run coding agents or execute complete rehearsals itself. No background completion loop is established by these results.
- Installed cron, running image, current server health and actual publication outcomes have not been freshly inspected for this plan.

### Implementation checkpoint — 2026-10-10, source `b0a8e52`

The user authorized implementation after the planning baseline. Local Luna agents implemented bounded slices; the supervisor reviewed, corrected failures and validated remotely. These are **partial package closures**, not whole-plan completion:

| Slice | Verified behavior | Still open |
|---|---|---|
| W1 / F01 | Feed no longer invents publication time; retrieval time stays in provenance. Missing/null/blank dates and future dates produce explicit rejection diagnostics. Malformed batch entries do not abort valid neighbors. | Underlying article capture, source-date recovery, review packaging, live source qualification; timezone-naive source policy needs explicit qualification |
| W2 / F03 | Existing evidence requires a matching canonical script hash; validator checks raw script without rewriting it. Malformed/wrong-version evidence, invalid schema or missing canonical script block fallback and preserve bytes. Unbound drafts still normalize. | Authenticated editorial review, compose-only/retry handoff, mutation prevention outside this validator and full dependency invalidation |
| W5 / F10 | Monitoring append is a locked read-modify-write; unique temporary file, file flush/fsync, atomic replace and directory fsync. Corrupt/invalid history raises instead of silently clearing it. Concurrent-process and pre-replace failure tests pass. | Whole-run generation locks, stage-state format/recovery, cleanup ownership, operational alert verification and crash/power-loss qualification |

**Behavior changes:** undated feeds may now yield no eligible candidates; this is an intentional hold, not permission to restore invented dates. Capture actual source dates next. Evidence-bound scripts needing normalization must return to draft/review rather than be repaired in place. Corrupt monitoring history now surfaces an error and requires investigated recovery; do not delete it to resume. Monitoring uses POSIX `flock` on the Linux runtime; shared-filesystem semantics still need operational qualification. Its existing 500-event retention remains unchanged, and the text log and JSON report are not one cross-file transaction.

**Commits:** `21b4994` (dates/bound scripts), `1c72b11` (null diagnostic), `b5a0c89` (monitoring), `b0a8e52` (fixture reaches intended full evidence gate). An initial focused test caught null-vs-missing diagnostics; the strict integration run caught a fake fixture hash now rejected earlier. Both were corrected locally without weakening production gates. The fixture retains empty claims/sources and still must fail full evidence validation/quarantine.

**Remote verification:** new isolated snapshot `/home/ubuntu/OpenMontage-daily-news-verify-21b4994`, populated by `git archive 21b4994` plus exact subsequent committed files. The previous remote test checkout had substantial dirty state and was left untouched. Tests ran in a disposable `openmontage:latest` container, image `sha256:899dd409a10ce38b32d769d00a263ab3357bddd08f293ba544d898cdf7b6ed50`, with `--network none`, only this snapshot mounted at `/app`, and no host production state/credentials mounted. All seven implementation/test file hashes checked equal after synchronization; the subsequent rehearsal-fixture correction was copied from its committed local revision.

- Focused date, director-validator and monitoring suites: **43 passed**, zero skips (`verification-focused-final.xml`).
- Existing fixed `lib.daily_news_acceptance_loop.SUITE` plus `tests/test_codex_agent_validation.py`, `tests/test_pipeline_monitoring.py` and the two focused news suites: **316 passed, 10 subtests passed**, zero skips/failures/errors, 21.83s (`verification-strict-final.xml`). Executed through `python3`/`pytest.main`; this was a suite invocation, not a new acceptance-controller completion run.
- Earlier broad `tests/contracts` plus the two news suites at `1c72b11`: **1,248 passed, 7 skipped, 19 subtests**, 235.93s (`verification-contracts.xml`). SSH hit its 240s timeout during teardown, so a clean command exit was not observed. Follow-up parsed saved JUnit: zero failures/errors, seven skips; the test container had exited. This broad result predates monitoring changes and is not a substitute for strict release acceptance.
- Reports are in the remote snapshot root. The strict final test invocation used `-q --tb=short -p no:cacheprovider --junitxml=/app/verification-strict-final.xml`; no quality thresholds were lowered. No paid generation, publication, stable deployment or cron edits occurred.

**Next dependency-critical implementation:** complete W1 capture/review packaging and W2 draft→human-review→compose routing before W3 independent rendition work. Reviewer identity/workflow, permitted source policy and numeric freshness require explicit production decisions; fixture-based engineering may proceed. W4–W9 and the remainder of W5/W6 remain open. No autonomous agent is left running by this checkpoint.

### Completion has four separate gates

| Gate | Required proof |
|---|---|
| Code complete | Applicable requirements mapped to reviewed changes and passing positive/negative tests at one revision; no unexplained critical failures or skips |
| Technical rehearsal complete | Actual entrypoint produces both renditions; three successive isolated runs and fault recovery have hash-bound evidence; live boundaries distinguished from frozen ones |
| Editorially approved | Authorized reviewer approves sources, claims, rights and three representative full/Reels sample pairs against an agreed quality reference |
| Operationally complete | Explicitly authorized revision deployed, generation canary accepted, schedule observed for the agreed real-time window, alerts/recovery verified; publishing separately authorized |

None of these gates implies the others. Mark the overall plan complete only when all applicable original requirements and all four gates have evidence.

## 2. Findings and priorities

The table records findings at the original audit baseline; the implementation checkpoint above supersedes resolved portions of F01/F03/F10. P0 blocks trustworthy production or risks duplicate/unknown external effects. P1 blocks quality, recovery or release qualification. These priorities do not authorize live actions.

| ID | Priority / evidence location | Observed gap and consequence | Package |
|---|---|---|---|
| F01 | P0; `tools/news/newsnow_feed.py`, `_published_at()` | Missing publication date falls back to current UTC time; retrieval can masquerade as fresh publication | W1 |
| F02 | P0; `newsnow_feed.py:32–73`, `newsnow_adapter.py:130–185`, `lib/news_research_bridge.py:83–108`, `tools/news/news_pipeline_cli.py` | Feed summaries and distinct URLs are not underlying article capture; no complete capture-to-editor workflow found in this path | W1 |
| F03 | P0; `scripts/prompts/director_generate.prompt.md`, `scripts/validate_newsnow_director_artifacts.py:197–201,554–559`, `lib/news_evidence.py:100–126` | Drafting/normalization/retry can rewrite the exact script bytes bound to review; evidence gate follows directors | W2 |
| F04 | P1; `scripts/run_daily_news_pipeline.sh:643–650,337–344,475–483` | Full narration is trimmed/copied over Reels audio; missing HTML can be copied between renditions | W3 |
| F05 | P1; `scripts/generate_news_captions.py:63–70` | `--no-script-comparison` means timed ASR does not prove approved names, dates, numbers or wording were spoken | W3 |
| F06 | P0; daily shell `:599–637`; `scripts/repair_hyperframes_quality.py:92–153` | TTS/music fallback, same-basename lookup and generic placeholders can silently substitute approved assets | W4 |
| F07 | P1; repair script `:371–379`; daily shell font setup; `agents.md` | Offline dependency qualification conflicts with prescribed GSAP CDN/no-vendoring rule; font fallback can change Vietnamese rendering | W4 |
| F08 | P1; `scripts/materialize_news_template.py:663–665`, `scripts/install_news_captions.py:219–220`, daily shell `:667–679` | Caption installation can reject existing markup or mutate composition after template hash recording | W4 |
| F09 | P0; `deploy/openmontage.cron:25–36`, `scripts/run_strict_docker_publish.sh` | No orchestration-wide generation single-flight guard found; schedule locks alone do not serialize whole runs | W5 |
| F10 | P1; strict shell `write_state`; `scripts/pipeline_monitoring.py:31–50,81–96` | State appends multiple JSON documents; concurrent read/append/replace can lose events; malformed monitoring data becomes empty history | W5 |
| F11 | P0; `scripts/schedule_today_native.py:159–185`, `tools/publish_store.py:311–330`, `tools/publishers/youtube_publisher.py:240–257,299–311` | Native scheduling marks unsuccessful calls failed without fully reconciling unknown outcomes; resumable upload session exists only in memory | W6 |
| F12 | P0; daily shell `DIRECTORS_MAX_BUDGET_USD`; `tools/cost_tracker.py` | Budget environment variable is not visible enforcement in inspected Codex invocation; existing WARN/project-local accounting does not prove a shared daily cap | W6 |
| F13 | P1; strict shell cleanup/disk handling; `agents.md`, `CLAUDE.md` | Age-only cleanup can target active long jobs; invalid disk readings need qualification; blanket HTTP400=expired token rule is technically unsound | W5/W6 |
| F14 | P1; rehearsal mode/controller; original plans 01/03/59 | Frozen tests skip upstream boundaries; three projects are not three runs; daily-news tests do not close TASK001–021 | W7/W8 |

Existing protections must be preserved: `publish_active_projects.py` has schedule locks, bounded publisher timeout and retained claims; multishot has cost reservations; checkpoint code has human gates/history; rehearsal music fails closed. The findings do **not** mean these protections are absent everywhere.

## 3. Intended artifact and approval lifecycle

Candidate observation → authentic source capture → normalized draft → authorized editorial review → immutable approved script per rendition → approved narration/assets and measured timing → composition/captions → final provenance and render QA → human sample acceptance → release gate → durable queue/claim/reconciliation → monitored operation.

- Publication time, update time and retrieval time are different facts. Unknown publication time stays unknown.
- Capture and hashes establish provenance, not truth, source authority or authenticated human approval.
- Draft normalization happens before approval. Composition/repair does not silently modify approved editorial content.
- Measured scene/audio timing should be separate from immutable wording where practical. Any schema/byte-hash contract change needs compatibility and invalidation tests.
- Script/source revision invalidates affected approvals and downstream assets. Preserve history and failed outputs; do not overwrite history to make a gate pass.
- Full and Reels have their own reviewed wording, audio, timing, caption coverage and dependencies.
- Final composition hashes must describe the bytes actually rendered, after permitted transforms. Never update a trusted hash just to conceal mutation.
- Agents prepare review materials; an authorized editor supplies approval. A reviewer-name string or `human_approved: true` is not authentication.

## 4. Ordered work packages

Each package is a problem-solving contract. Proposed approaches are candidates; implementing agents must independently inspect and isolate the failure before choosing minimal changes. Use existing pipeline/tools/checkpoints, not a new autonomous daemon or Python creative-orchestration rewrite.

### W0 — Refresh requirement and runtime baseline

**Inputs:** plan 61; original plans 01/03/59; current task branch; existing QA evidence; repository cron and strict entrypoint.

**Outputs:** a requirement ledger with requirement ID, implementation, test/evidence path, revision/hash, status (`unverified`, `in_progress`, `verified`, `blocked`) and blocker owner. Distinguish historical test results from newly executed ones. Read-only remote inventory records actual checkout/image, cron implementation/user/timezone, enabled schedules, isolated state paths, storage/mount layout, alert destination and last run outcomes. Redact secrets.

**Acceptance:** no activation claim based solely on a checked-in cron file; no original requirement disappears; runtime unknowns remain explicit. Verify tests cannot reach live queues/credentials/media. Local unrelated `lib/news_research_bridge.py` changes outside this task worktree remain untouched.

**Dependencies/approval:** none for local inspection; announce target and read-only purpose before authorized SSH inspection. Configuration changes are outside this package.

### W1 — Honest dates and capture-to-review integration

**Inputs:** F01/F02, feed/adapter/research interfaces, evidence v2, explicit freshness policy and permitted source domains/access policy.

**Expected outcome:** distinguish unknown publication date from observation time; securely capture accessible underlying article content with canonical URL, retrieval/publication/update provenance, raw/extracted hashes, excerpts and rights/attribution notes. Produce a claim-review worksheet and unresolved-conflict list. Missing/inaccessible/undated evidence holds production rather than inventing metadata. Do not bypass paywalls/access restrictions.

**Candidate approach:** extend existing research tools with bounded capture and review packaging. Review SSRF controls at every fetch/redirect: schemes, credentials, resolved IPv4/IPv6, internal/link-local/metadata addresses, DNS changes, time/size/type limits; use network defense too. Preserve Host/SNI and certificate validation when controlling destination resolution.

**Scope:** news feed/adapter/CLI, research integration, evidence interfaces and focused contract tests. Coordinate shared evidence edits with W2.

**Acceptance:** fresh dated article can reach review; missing date never becomes now; stale/future/invalid dates, source outage, oversized response, redirect to private address, DNS rebinding, duplicate source/topic, conflicting reports and post-capture mutation all have explicit outcomes. Corrections retain provenance. Capture alone never authorizes publication. Existing consumers migrate without confusing retrieved and published times.

**Done:** authenticated capture can be handed to the editor and then bound to the approved canonical script. An agent may prepare bundles; the user need not manually assemble every artifact. Numeric freshness and real source permissions require a decision before live use.

### W2 — Immutable approval and dependency invalidation

**Inputs:** F03; director generation/retry prompts; normalizer; checkpoint human gates/history; evidence exact-byte contract.

**Expected outcome:** normalized drafts are reviewed before downstream work; composition-only/retry preserves approved scripts. Any editorial/source change invalidates affected approvals and outputs without destroying prior evidence. Review action must originate through the intended authorized human workflow.

**Scope:** prompts, director validator, daily-shell handoff, checkpoint/evidence integration and tests. Avoid a general checkpoint rewrite unless isolated evidence requires it.

**Acceptance:** approved unchanged input progresses; missing/pending/rejected review blocks before consequential generation; retry cannot self-approve; post-approval normalization, source mutation, whitespace/byte changes under the existing contract and stale audio all invalidate correctly; measured timing updates do not silently rewrite wording. Migration of older checkpoints fails visibly when approval provenance is insufficient.

**Dependencies:** W1 for real evidence; synthetic test-only capture fixtures permit implementation in parallel under disjoint ownership. Done requires an actual draft→review→compose integration test, not only hash-helper tests.

### W3 — Independent Reels and faithful captions

**Inputs:** F04/F05; approved scripts from W2; cached ASR; existing caption installer and quality contract in plan 61.

**Expected outcome:** Reels is a substantive editorial cut, not a 58-second audio truncation. Preserve valid supplied Reels assets. Each rendition binds approved script, narration, captions and measured timing. Missing rendition-specific composition blocks rather than copying an incompatible layout.

**Candidate approach:** script/ASR comparison with explicit Vietnamese normalization and sensitive-token checks, plus a reviewable mismatch report. Recognition is evidence to inspect, not authority to rewrite the script. Forced alignment or manual timing review may be needed; ASR timestamps alone do not prove the required timing tolerance.

**Scope:** daily materialization, caption generation/comparison, rendition manifests and relevant tests. Serialize shared daily-shell edits with W2/W4/W5.

**Acceptance:** deliberately different scripts/audio survive; full narration longer than Reels cap does not cause overwrite or a clipped sentence; wrong audio/hash/rendition is rejected; changed names, dates, quantities, negation, omissions and extra speech are held for review; punctuation/diacritic normalization does not hide factual differences. Human listening verifies intelligibility/pronunciation and caption timing against the existing ≤250ms target.

**Done:** both renditions independently pass approved-content, duration, audio and caption checks. Paid regeneration or provider changes require approval.

### W4 — Approved assets, dependency closure and final provenance

**Inputs:** F06–F08; template hashes, caption ownership, asset manifest, existing runtime rules.

**Expected outcome:** final artifacts only reference approved assets; no silent alternate TTS/music, generic editorial placeholder or unrelated same-basename file. One caption authority and a finalization boundary bind exact rendered composition/media bytes after authorized transforms.

**Decision required:** `agents.md` prescribes GSAP 3.14.2 CDN and prohibits vendoring. Investigate compiler/browser caching or an approved offline resolution mechanism preserving that contract. Local vendoring requires an explicit rule exception first. A browser cache alone is not proof of reproducible resolution: verify the mandated version and behavior with missing/stale cache. If no compliant resolution works, keep offline-render acceptance blocked and request the exception instead of implying the current contract is sufficient. Do not claim the earlier synthetic render was network-free; it fetched Google fonts.

**Scope:** asset repair/finalization, template materializer, caption installer, font/dependency checks and daily-shell integration.

**Acceptance:** deleted/changed assets, identical basenames with different hashes, absent font/Vietnamese glyph coverage, unreachable CDN, empty cache, duplicate caption markup and template hash mismatch fail visibly. Repeated permitted finalization is deterministic or explicitly rejected without partial corruption. Demonstrate the intended browser/render path with network disabled after separately authorized provisioning; record dependency versions and content hashes.

**Dependencies:** W2/W3 contracts. Done means an unapproved fallback cannot enter a release artifact, while existing legitimate fixtures remain explicitly test-only.

### W5 — Single-flight operation, durable state and safe cleanup

**Inputs:** F09/F10/F13; actual filesystem/container sharing from W0; existing queue/publisher locks and controller state patterns.

**Expected outcome:** generation overlap is safely refused/deferred; appropriate project/platform claims remain independent. Run state records stage, owner, revision, attempts and `running/succeeded/failed/unknown` with recoverable history and actionable alerts. Cleanup cannot delete active or uncertain work merely because it is old; invalid disk metrics fail closed.

**Candidate approaches:** a process lock/lease compatible with actual shared storage and explicit ordering; transactional or locked crash-safe state/events. SQLite is an option, not a mandate; assess migration, filesystem guarantees and existing interfaces first. Avoid nested-lock deadlocks; existing unlock-before-cleanup behavior may be intentional.

**Scope:** strict entrypoint, monitoring, cleanup and scheduling boundaries with reliability tests. Do not remove existing publication locks.

**Acceptance:** concurrent generation, concurrent slot/queue writes, crashed owner, SIGTERM, SIGKILL, partial ledger writes, malformed history, low disk, unavailable disk reading and a live job older than cleanup threshold preserve evidence and avoid duplicate effects. Test process-group cleanup and lock release. Monitoring must not turn corruption into empty success/history. Alerts identify run/stage/recovery action without exposing secrets.

**Done:** restart can identify completed/failed/unknown stages and safely choose eligible work. Signal handling alone is insufficient for SIGKILL; durable evidence/reconciliation must cover it.

### W6 — Budget enforcement and uncertain provider outcomes

**Inputs:** F11/F12/F13; cost tracker and multishot reservation patterns; all paid boundaries; native scheduler/publish store/YouTube adapter.

**Expected outcome:** explicit approved per-video/daily limits apply before every paid request across overlapping runs. Estimates, reservations and reconciled actual costs remain distinct; unknown cost retains a conservative reservation. Unknown uploads/submissions are not blindly retried or marked safely absent.

**Candidate approach:** inventory each actual CLI/provider path and prove enforcement, rather than relying on an environment-variable name. Persist resumable upload identity/state securely before relying on it; reconcile authoritative session/provider status after response loss. An expired session or missing video ID may leave a genuine unresolved outcome. Do not promise exactly-once delivery where the provider has no such guarantee.

**Scope:** daily paid-call wiring, cost persistence, native scheduling/upload lifecycle, error classification and reviewed instruction corrections in both `agents.md` and `CLAUDE.md` as necessary.

**Acceptance:** cap reached, concurrent reservations, timeout after charge, restart before response persistence, 429/503/Retry-After, interrupted upload, completed upload with lost response, expired session and permanent rejection are classified without duplicate charges/uploads. Provider-specific HTTP400 reasons distinguish credentials from payload/permission errors; no blind credential rotation. Test doubles prove behavior without spending/publishing; real canary needs separate approval.

**Dependencies:** W0 storage inventory and W5 state contract. Done requires direct evidence that daily director calls are governed, not only standalone cost-tracker tests. Unknown outcomes remain visible holds until reconciled.

### W7 — Complete rehearsals and fault qualification

**Inputs:** W1–W6; honestly reviewed frozen assets/evidence; exact isolated runtime revision; explicit freshness policy; existing rehearsal/controller interfaces.

**Sequence and outputs:**

1. Run focused tests, then the fixed strict suite and relevant broad regression; investigate skipped acceptance cases rather than lowering the suite.
2. Produce one positive actual daily-shell rehearsal, including real full/Reels MP4s and final provenance/QA reports.
3. Complete three successive scheduled-equivalent frozen runs with distinct topic sets. The current shell requires three projects per invocation and the controller requires pairwise-distinct IDs across three roots: **nine project executions**, not three projects relabeled as three runs. The initial positive run may count if it meets the same requirements.
4. Inject a failure and resume through the real entrypoint; verify unchanged completed artifacts, preserved quarantine, no duplicate submit/charge, useful alerts and strict gates.
5. Separately test acquisition/director/TTS boundary contracts, which frozen mode bypasses. An approved source-to-video generation canary is still required for a live E2E claim.

**Acceptance evidence:** revision/image, environment/dependency hashes, command and exit code, elapsed time, test counts/skips, source/script/audio/HTML/MP4/report hashes, fault description, before/after queue and reservation state, redacted logs and reviewer outcomes. Synthetic/historical evidence must remain labeled test-only. Bind controller input to validated reports, not hand-authored success flags.

**Done:** all required fault cases below pass at the release candidate or have a justified retest mapping; no claim of multi-day reliability from accelerated runs.

### W8 — Reconcile original multishot group

**Inputs:** `01_MASTER_PLAN.md`, `03_IMPLEMENTATION_TASKS_AND_ACCEPTANCE.md`, `59_REQUIREMENTS_EVIDENCE.md`; TASK001–021 implementations/contracts.

**Expected outcome:** update every requirement against current code and evidence, not historical failure counts. Preserve original integration coverage: IT-01 2-shot, IT-02 6-shot/30s, IT-03 mixed media, IT-04 retry, IT-05 permanent failure, IT-06 crash resume, E2E-01 Mochi/30s, plus master-plan registry/human-gate requirements.

**Acceptance:** actual outputs and checkpoints where required, cost/resume/invalidation qualification, explicit live-provider and human-review blockers. `actual_cost_source=estimate` is not billing reconciliation. Daily-news tests cannot stand in for these requirements. Synthetic cinematic footage is optional editorial treatment, never factual news evidence.

**Dependencies:** W0 ledger; independent investigation can proceed in parallel, but shared cost/checkpoint code must have one owner. Done requires a complete requirement ledger, not an aggregate pass count.

### W9 — Human acceptance, approved deployment and observation

**Inputs:** W7/W8 evidence, three representative sample pairs (breaking update, data-heavy story, explanatory story), agreed reference and plan 61 quality rubric.

**Expected outcome:** editor checks facts/attribution/rights, independent Reels narrative, Vietnamese pronunciation, audible balance, readable captions/safe areas, appropriate visuals and pacing. Show reference comparison; do not claim improved quality from edge density or motion alone.

**Release proposal:** exact commit/image and rollback revision, target checkout/container, database/state migration and backup strategy, generation schedule/timezone, volume, source policy, providers, daily cap, alert recipient and observation window. Present both composition runtimes if both available before a new runtime decision; authoring mode is a separate choice.

**Acceptance:** explicit approvals recorded; generation-only canary first; publication authorization separately scoped to channels/platforms. Inspect the actual installed scheduler and observe at least one real scheduled run, then the agreed stability window. Verify freshness, deadlines, budgets, alerts, duplicate prevention and recovery from real logs. A platform failure must be reported as degraded even if an existing partial-success policy permits overall progress.

**Rollback:** disable only the authorized new schedule, retain queues/unknown claims and artifacts, restore the approved prior code/image, reconcile pending external actions before retry. Never blindly restore an old queue snapshot that could re-publish completed work. Stable checkout remains untouched until deployment approval.

## 5. Cross-package fault matrix

| Area | Required positive/negative cases | Evidence/owner |
|---|---|---|
| Sources | Authentic dated capture; unknown/stale/future dates; redirect/DNS/private target; conflict/correction; changed content | Capture and evidence contracts, W1 |
| Approval | Normalized approved script; missing/rejected review; compose retry; post-approval rewrite; source revision | Checkpoint/history + dependent artifact assertions, W2 |
| Renditions | Different full/Reels wording/audio; wrong audio; missing layout; clipped ending; Vietnamese names/numbers/negation mismatch | Caption/rendition integration + listening review, W3 |
| Assets/render | Approved manifests; missing/changed asset; basename collision; no network/cache/font; template/caption hash conflict | Actual renderer + provenance reports, W4 |
| Concurrency/state | Single and overlapping runs; slots during queue updates; killed owner; corrupt/truncated ledger; disk/cleanup hazards | Multiprocess/fault-injected isolated tests, W5 |
| External effects | Budget limit; concurrent reserve; response loss; unknown/expired session; 429/503; permanent 400 reason | Adapter tests, durable claims, approved canary only, W6 |
| Acceptance | Strict suite with zero skips; missing/stale/forged reports; repeated IDs; source mutation; fault recovery | Actual shell reports/controller state, W7 |
| Original group | All TASK001–021, IT-01–06, E2E-01 and cost/provider qualifications | Refreshed requirement ledger, W8 |
| Operations | Actual cron user/env/timezone, generation deadline, alert delivery, partial failure, approved rollback | Observed runtime evidence, W9 |

Start with existing tests rather than duplicate suites: `tests/contracts/test_news_research_evidence.py`, `test_news_evidence_gate.py`, `test_daily_news_evidence_integration.py`; `tests/tools/test_newsnow_pipeline.py`; director-artifact, caption and rehearsal tests; `tests/test_strict_cron_retry.py`, `test_daily_cron_reliability_hardening.py`, `test_pipeline_monitoring.py`, `test_publish_active_projects.py`, `test_schedule_today_native.py`, `test_publish_manual_video.py`; and publish/multishot contracts. Resolve actual paths before execution. Test names/comments are not proof that failure cases are covered.

## 6. Delivery, migration and supervision

Recommended dependency order: **W0 → W1/W2 → W3 → W4 → W7 → W9**. W5/W6 and W8 can progress in parallel after baseline inspection with separate write ownership; W7 waits for all relevant release blockers. Documentation-only work does not authorize implementation or live execution.

- Local task worktree: `/home/ubuntu/OpenMontage/.claude/worktrees/daily-news-render-repair`, branch `task/daily-news-render-repair`.
- Isolated remote execution checkout: `/home/ubuntu/OpenMontage-daily-news-render-repair`. Stable `/home/ubuntu/OpenMontage` on the server is protected.
- Code and coding agents stay local. Project setup/tests/builds/renders run only remotely after safe synchronization and revision/hash verification. Announce SSH purpose and target first. Isolation includes queues, credentials, publication records, costs and media, not just Git.
- Slice packages into bounded 15–30-minute investigation/implementation attempts, not promised completion times. The supervisor checkpoints after each attempt. Native agent tooling may not expose a timeout/turn cap: do not invent flags; use the available controls and report limitations.
- One owner per shared daily shell/checkpoint/evidence file. Delegate disjoint tests/docs only when interfaces are agreed; otherwise proceed serially.
- Each cycle: inspect → isolate/reproduce → local minimal patch/tests → independent diff review → synchronize → remote narrow tests → broader relevant tests → ledger update. Continue eligible tasks; do not rerun unchanged deterministic failures.
- Retry transient service failures with bounded attempts/backoff. After two unsuccessful focused fixes of the same diagnostic, preserve work and report the concrete blocker or rescope investigation. Never lower thresholds, disable validators or silently switch models/providers.
- Schema/state migrations need old/new fixture tests, backups and explicit compatibility behavior. Preserve approval history, failed evidence and unknown reservations. Avoid replacing existing orchestration before fixing its interfaces.
- Commit only reviewed task changes under existing authorization. Do not automatically merge main, deploy, activate cron, publish or spend.

## 7. Copyable local agent assignment

The approved route is native **`openai-subscribed/gpt-6-luna`**. Use the available native agent dispatcher with that exact model ID after confirming availability. This is a dispatch specification, not a shell command or a claim that an agent is running. Do not retry the historical unverified Claude/Haiku gateway or substitute another model silently.

```text
Work only in /home/ubuntu/OpenMontage/.claude/worktrees/daily-news-render-repair
on task/daily-news-render-repair. Read AGENT_GUIDE.md, AGENTS.md,
agents.md and CLAUDE.md before acting. Inspect branch/status and preserve
all unrelated work. Never edit the main checkout or any remote source.

Read docs/daily-news-completion-plan.md and master plan 61.
Assigned package: [supervisor supplies one W ID and a bounded sub-outcome].
Write ownership: [supervisor supplies explicit files after path discovery].
Acceptance cases: [copy the relevant positive/negative cases].

Independently inspect current code and provider documentation; validate the
plan's assumptions. Isolate the defect before patching. Implement the smallest
compatible solution, preserve history/unknown outcomes, and add regression
coverage. Do not treat source hashes as fact-checking or fabricate approval.

Do not run project setup/tests/builds/renders locally. Return the proposed
remote validation commands to the supervisor; they will synchronize the exact
revision and validate in /home/ubuntu/OpenMontage-daily-news-render-repair.
No coding over SSH, paid calls, publishing, stable deployment, cron changes,
model/provider changes, secret exposure, or deletion of evidence.

Return: verified observations versus assumptions; files/diff summary;
acceptance-test mapping; migrations; unverified cases and concrete blockers.
Do not claim success from unexecuted tests. Do not commit unless assigned.
If blocked, preserve partial work and propose the next investigation rather
than weakening gates. This assignment does not mark the whole plan complete.
```

The supervisor must fill in package, scope and tests before dispatch. Suggested first implementation slice: W1's missing-publication-date integrity fix and consumer regression tests; then W2's immutable approval boundary. An independent read-only reviewer should verify each completed slice before remote validation.

## 8. Decisions needed, at the affected gate

| Decision | Needed before |
|---|---|
| Topic scope, sensitive exclusions, authoritative-source/corroboration policy, freshness limit | Real editorial intake and approval |
| Permitted sources, capture/access and media rights/attribution | Live capture and assets |
| Approved providers/voices, per-video/daily cap, paid canary scope | Any paid request |
| Runtime and templated/bespoke mode where a new choice is needed | Production composition |
| GSAP offline resolution versus explicit no-vendoring exception | Offline runtime architecture change |
| Quality reference, authorized reviewer and approval mechanism | Sample acceptance |
| Platforms, schedule/timezone/volume, alert destination, observation window, rollback owner | Stable activation |
| Explicit publishing permission | External publication |

These decisions need not block safe fixture-based engineering. When unavailable, complete eligible work and record the specific blocked gate instead of repeatedly asking whether the entire plan is done.

## 9. Evidence and closure checklist

For every requirement, retain exact revision, executable test/report location, result and scope limitations. Link existing evidence rather than duplicating inconsistent status files.

- [ ] W0 current requirement ledger and isolated runtime inventory
- [ ] W1 authentic source capture and honest timestamp handling
- [ ] W2 immutable human approval and downstream invalidation
- [ ] W3 independently reviewed Reels and script-faithful captions
- [ ] W4 approved assets, final provenance and dependency qualification
- [ ] W5 tested single-flight, durable state, alerts and safe cleanup
- [ ] W6 enforced spend limits and uncertain-effect reconciliation
- [ ] W7 three actual successive rehearsals plus recovery and upstream qualification
- [ ] W8 original group requirement-by-requirement closure
- [ ] W9 approved samples, authorized deployment and observed schedule

At this document's baseline these boxes are intentionally open. Implemented subfeatures and prior passing tests are credited in section 1; they do not close whole packages.

## 10. Research references and limits

Authoritative documentation consulted during the planning investigation:

1. [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html): informs source/asset capture, redirect and DNS validation plus network controls. A design risk, not a claim that a current exploit was reproduced.
2. [Cronie crontab(5)](https://man7.org/linux/man-pages/man5/crontab.5.html): timezone/environment, user versus system syntax and missing/repeated DST times. Identify the installed cron first; do not assume Cronie or `crontab -T` exists. Vietnam's schedule still needs correct timezone configuration.
3. [util-linux flock(1)](https://man7.org/linux/man-pages/man1/flock.1.html): bounded/nonblocking acquisition, descriptor lifetime, lock ordering and filesystem caveats. It does not detect deadlocks or guarantee locking on every network filesystem.
4. [SQLite Atomic Commit](https://www.sqlite.org/atomiccommit.html): possible durable local ledger solution with filesystem/fsync assumptions and crash testing. It cannot transact an external paid API or solve unknown uploads by itself.
5. [YouTube resumable upload protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol): persist session Location securely; status probe, 308/Range resume, completed response and bounded backoff/Retry-After. Expired session identity cannot prove absence of a prior upload. Never put session URLs, auth headers or credential-bearing debug logs in public evidence.

6. [Python `os.fsync` and `os.replace`](https://docs.python.org/3/library/os.html#os.fsync): consulted during the monitoring implementation for flush-before-fsync and same-filesystem atomic replacement. These mechanisms are not proof of power-loss recovery on the actual deployment filesystem.

These references guide investigation; they do not establish that a particular patch works. Only implementation review, isolated verification, authentic editorial approval and authorized observed operation can close the plan.
