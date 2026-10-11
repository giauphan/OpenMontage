# Daily-news release execution runbook

**Status snapshot:** task worktree `task/daily-news-review-handoff`, revision
`cf0ef91` (2026-10-11). This is an execution plan, not a release declaration.
The completion contract, evidence contract, strict acceptance controller, and
original release plan remain authoritative; this document operationalizes
W0–W9, R0–R1, N1–N7, and the original TASK001–021, IT-01–06 and E2E-01
requirements into ordered, observable handoffs.

- [Completion contract / W0–W9](daily-news-completion-plan.md)
- [Evidence and capture/review boundaries](news-evidence.md)
- [Strict acceptance-controller contract](daily-news-acceptance-loop.md)
- [Original master release plan 61 / N1–N7 and multishot requirements](../plan/pending/collap-group/61_DAILY_NEWS_RELEASE_PLAN.md)

## Release authority and truth labels

The user authorized implementation of the release work and conditionally
requested the eventual merge of the task and main histories, synchronization
to the production main/server target, and a production generation run once the
release gates below pass. That scoped deployment/run is authorized on passing
gates; do not ask for redundant deployment permission. Before execution, record
the exact tested revision, production target, snapshot/recovery evidence and
run interface, and stop if any differs from the approved candidate or has
unresolved state. This authorization does not approve unlimited generation,
spending beyond a separately agreed cap, editorial self-approval, external
publication, or new/modified cron activation. Provider calls still require a
bounded approved spend policy. The first production run must be generation-only
and must not publish or create/activate publication work. The inspected strict
orchestrator includes a publish stage; no verified safe generation-only
production command/interface was found. Do not invoke it for that run: establish
and validate a safe generation-only route in the implementation, and record
its exact interface and side-effect proof before production execution. If the
existing environment cannot support generation-only execution without queue or
publication effects, stop at that concrete blocker.

Use these status labels in the evidence ledger:

- **VERIFIED AT SNAPSHOT** — recorded evidence at `cf0ef91`, not a new run in
  this task and not proof of live qualification.
- **PENDING** — no acceptable evidence yet; identify the owner, decision or
  artifact needed next.
- **PASS AT RELEASE CANDIDATE** — exact revision, environment, command, exit
  status, artifacts, hashes, test counts and reviewer evidence retained.
- **BLOCKED** — a negative gate did what it should; retain its evidence and
  resolve the named cause. Never relabel a block as pass by bypassing it.

## Verified baseline and remaining boundary

At `cf0ef91`, the completion-plan checkpoint records **307 strict tests passed,
10 subtests, zero failures/skips**, and **1,279 broad tests passed, 7 skipped,
19 subtests**. These were remote isolated tests at the documented earlier
implementation snapshot; they are not tests of this documentation change or of
a merge candidate. Skips in broad coverage are not strict acceptance. Historical
technical renders also passed some checks, but their archived content was
unsupported and **not editorially verified or publishable**. The strict
acceptance controller previously passed its own 240-test suite yet correctly
returned `blocked_missing_rehearsal_inputs`; it is an evidence verifier, not a
pipeline runner. No positive set of three complete successful full-shell runs,
source-to-video qualification, human-approved sample set, current server/cron
inventory, or observed scheduled run is established by those results.

**W1 is partial, not complete:** bounded explicit source capture and
`prepare-review` produce pending, hash-bound full-script worksheet scaffolds.
They do not authenticate the reviewer, assess claim support, approve rights or
sources, make evidence v2, create a Reels worksheet, or connect approval to the
live pipeline. W2–W9 remain open as described in the completion contract.

## Owner decisions required (do not infer defaults)

Record the decision, authorized owner, timestamp and resulting configuration
before crossing its gate. Fixture work can proceed while these are unresolved.

| Decision ID | Owner decision required | Blocks |
|---|---|---|
| D-01 | Approved source/domain allowlist, authority/corroboration and correction policy; capture/access constraints and rights/attribution; explicit maximum source age in `(0, 720]` hours | Real intake, editorial evidence and live source qualification |
| D-02 | Authenticated reviewer identity and workflow, reviewer authorization, audit/history and approval revocation semantics | Any claim that a draft/evidence/script is editorially approved |
| D-03 | Allowed providers/models/voices/assets and per-video plus daily spend caps; treatment of unknown charges | Every paid provider call and canary |
| D-04 | Human-defined sample quality reference/rubric and acceptance (three full/Reels pairs: breaking update, data-heavy, explanatory); observation/sign-off owner | Editorial release gate |
| D-05 | Queue/state isolation and snapshot strategy; schedule/timezone/volume; alert recipient; rollback owner and observation window. Record the exact authorized production target and tested revision as release evidence, not as a new permission request. | Safe generation-only run and any separately approved schedule operation |
| D-06 | Composition runtime and separate templated/bespoke choice where a new decision is needed; offline dependency policy | Release render path |
| D-07 | Explicit platform/channel publication scope and permission | Any external publication, independent of generation approval |

A named reviewer string, `human_approved` boolean, source hash or agent
assertion is not authentication or proof of semantic support. No user decision
is presumed by this runbook.

## Ordered execution phases and acceptance gates

### Phase 0 — Reconcile requirements and establish safe baselines (W0, N1, W8)

**Scope:** freeze the evidence inventory, reconcile master-plan requirements,
and perform the isolated runtime/operational inventory (read-only).

**Dependencies:** none for local inventory. Remote inspection requires an
announced target and explicit read-only purpose. Do not inspect or expose
secrets.

**Actions and outputs:** create a requirement ledger mapping every W0–W9 and
W0–W9/R0–R1/N1–N7 item plus original multishot TASK001–021, IT-01–06 and E2E-01 to
owner, code/interface, positive and negative tests, report/hash/revision, status,
blocker and next action. Credit the baseline above only at its stated scope.
Inventory server checkout/image, installed schedule/user/timezone, run history,
queue and publication-state locations, storage/mount sharing, alert path and
actual current health only through authorized isolated/read-only inspection.
Record unknowns as unknown, not as “disabled” or “healthy”. Keep multishot
requirements distinct; daily-news tests do not close them.

**Gate G0 passes only when:** every original requirement is represented; each
runtime fact is tied to dated evidence and target identity; test isolation from
live queues, credentials, publication records and media is demonstrated; no
secret is copied into the ledger. A checked-in cron file alone is not proof of
an installed schedule. If the server target or isolation boundary is unclear,
stop before remote execution.

### Phase 1 — Finish honest source intake and claim review (W1, N2)

**Scope:** settle D-01; finish the source-to-claim worksheet and Reels
coverage; connect authorized review outcomes to evidence v2.

**Dependencies:** G0 for live interfaces; D-01 and D-02 for real-source and
approval qualification. Test fixtures may be used before those decisions but
must remain marked test-only.

**Known interface:** `python3 -m tools.news.news_pipeline_cli capture-source
--project-dir PROJECT_DIR --url ARTICLE_URL --allowed-host APPROVED_HOST`
requires real project/host values and repeats `--allowed-host` for explicit
redirect hosts. It captures pending material; it does not approve. For an
existing canonical full script and selected capture revisions,
`python3 -m tools.news.news_pipeline_cli prepare-review --project-dir
PROJECT_DIR --capture artifacts/news_source_capture/CAPTURE_ID.provenance.json=PROVENANCE_SHA256`
(repeat `--capture`) creates a pending worksheet only. These examples are
interfaces, not an instruction to run them with placeholders. Never use a
secret-bearing URL. See `news-evidence.md` for exact artifact and security
contracts. There is no verified authenticated production approval command.

**Positive acceptance:** an explicitly permitted, accessible, dated source is
captured into a unique revision; exact raw/extracted/provenance hashes verify;
a human-authorized reviewer can assess claim wording, excerpt support, source
authority, distinct corroboration for consequential claims, rights, dates and
corrections, then bind approval to exact script bytes and rendition. Full and
Reels claims each have coverage. Evidence v2 validates with the explicit
freshness policy and all downstream approval provenance.

**Negative acceptance:** unknown/missing, stale, future, timezone-naive or
invalid publication/update dates never become retrieval time/current time;
unauthorized host or redirect, private/mixed DNS, rebinding, paywall, outage,
oversized/unsupported/lossy content, changed capture bytes, duplicate topic,
unsupported claim, unresolved conflict/correction, absent rights, pending,
rejected or unauthenticated review, wrong script hash, missing Reels evidence
and unsupported consequential claim all hold before consequential work. A
captured worksheet never passes the release gate by itself.

**Gate G1:** policy decisions D-01/D-02 recorded; source and rights status
resolved; exact full and Reels scripts have authenticated authorized human
approval; evidence-v2 hashes and explicit freshness validation pass; all listed
negative cases fail closed. Otherwise remain in pending review; no generation.

### Phase 2 — Immutable approvals and independent renditions (W2–W3, N2/N4)

**Scope:** establish draft/review/compose ordering, approval immutability and
invalidation, a substantive Reels cut, and script-faithful caption/audio checks.

**Dependencies:** W1 contracts; synthetic fixtures permit isolated engineering
before D-02. Paid regeneration waits for D-03 and explicit per-call approval.

**Positive acceptance:** unchanged approved bytes can proceed to composition;
composition-only retries preserve approvals and history; full and Reels each
have intentionally distinct or explicitly approved scripts, narration, measured
timing, source coverage and captions; valid supplied Reels assets survive
materialization; captions match the audio and approved wording; Vietnamese
names, numerals, dates, negation and acronyms are checked by human listening.

**Negative acceptance:** missing/pending/rejected approval blocks before
consequential generation; director retry cannot self-approve; any source/script
revision or post-approval byte mutation invalidates dependent evidence/assets;
full audio cannot be trimmed/copied as a substitute for reviewed Reels; wrong
rendition/audio/hash, missing layout, incomplete sentence, added/omitted speech,
factual token mismatch, stale captions and timing outside the agreed existing
250 ms sampled target are held. Normalization must not conceal a factual
mismatch or rewrite the approved bytes.

**Gate G2:** integration evidence proves actual draft → authenticated review →
compose-only flow and both complete renditions at the same candidate revision;
no unreviewed generation occurs. Hashes connect the exact approved wording,
source evidence, narration, captions, compositions and eventual outputs.

### Phase 3 — Approved assets, deterministic render and release provenance (W4)

**Scope:** close approved-asset dependencies; establish final composition and
caption ownership/hash boundaries; qualify fonts, browser/GSAP and offline
reproducibility; retain final-output provenance and technical QA.

**Dependencies:** G2 and D-06. Do not silently choose runtime or authoring mode;
when both Remotion and HyperFrames are available present both as required by
`AGENT_GUIDE.md`, then record the user's choice separately from authoring mode.

**Positive acceptance:** only manifest-approved assets enter the final render;
rendered bytes are hashed after permitted finalization; final report captures
script/evidence/audio/caption/composition/asset/MP4 hashes, exact renderer and
font/dependency versions, duration, streams, decode and QA results. Repeated
permitted finalization is deterministic or explicitly rejected without partial
corruption. Validate Vietnamese glyphs, readable safe margins, complete opening
and ending, speech intelligibility, no clipping/dropouts, appropriate licensed
visuals and captions.

**Negative acceptance:** missing or changed assets, basename collision, silent
TTS/music/provider fallback, generic placeholder, missing Vietnamese glyph,
uncached/unavailable dependency, network-disabled failure, duplicate/conflicting
caption markup, altered composition after recorded hash, invalid duration,
decode/stream failure or QA threshold miss must block and preserve evidence.
`agents.md` requires a GSAP CDN version and prohibits vendoring; no offline
substitute or exception is approved here. Resolve that conflict explicitly.

**Gate G3:** actual selected render path passes technical and human spot checks
on exact bytes with dependency closure and complete provenance. Synthetic or
historical content is not evidence of editorial acceptance.

### Phase 4 — Reliability, state, spend and external-effect controls (W5–W6)

**Scope:** run-wide single-flight and safe project/platform claims; durable
stage/event state, recovery, cleanup and alert delivery; enforceable shared
spend reservations at every paid boundary; reconciliation of unknown provider,
upload and schedule outcomes.

**Dependencies:** G0 storage/locking inventory; D-03 for live paid calls; W5
state contract before W6 final integration. Use isolated state and test doubles.

**Positive acceptance:** overlapping generation is refused/deferred; restart
identifies completed/failed/unknown stages and resumes only eligible work;
completed artifacts and quarantine survive; reservations reconcile estimate,
actual and unknown cost conservatively; actionable redacted alerts arrive;
external submissions are reconciled before retry. Prove enforcement in the
actual director/provider invocation, not by presence of a budget variable or a
standalone cost-tracker test.

**Negative acceptance:** lock overlap, killed owner, SIGTERM/SIGKILL, partial or
corrupt ledger, invalid disk reading, low space, active old job during cleanup,
concurrent queue/slot updates, timeout after charge, response loss, 429/503,
interrupted/expired upload session, completed upload with lost response and
permanent credential/payload/permission rejection never erase history, release
an unknown reservation, duplicate charge/upload, or classify unknown as absent.
No guarantee of exactly-once external effects where provider semantics cannot
establish it.

**Gate G4:** isolated multiprocess/fault-injection evidence at candidate
revision proves safe overlap/recovery, durable state, cleanup boundaries,
alerting and hard budget enforcement. Unknown outcomes remain visible holds.

### Phase 5 — Full entrypoint rehearsals and fault recovery (W7, N5)

**Scope:** qualify the exact candidate/environment; complete one positive
daily-shell run, three successive scheduled-equivalent runs, and one injected
fault/recovery; separately qualify upstream acquisition/director/TTS boundaries
not exercised by frozen bundles.

**Dependencies:** G1–G4, chosen explicit freshness policy, licensed/approved
frozen content, D-03 if any paid provider boundary is exercised, and a disposable
isolated server root with no live secrets/queues/publication state. Rehearsal
stage isolation is external; the shell report explicitly does not assert egress
isolation.

**Known interfaces:** full live shell accepts no arguments;
`scripts/run_daily_news_pipeline.sh --rehearsal-bundle MANIFEST` accepts exactly
one nonempty manifest and is test-only with a marked root and explicit
`NEWS_MAX_SOURCE_AGE_HOURS`. Rehearsal disables acquisition, director and TTS;
it does not qualify them. The strict acceptance controller takes `--state-dir`,
exactly three repeated `--rehearsal-manifest` arguments, and bounded
`--max-attempts` (1 or 2), `--wall-seconds`, `--suite-timeout`; see
`daily-news-acceptance-loop.md` for exact contracts. It runs its fixed tests and
verifies three reports, but does not run rehearsals, render, deploy, publish or
observe cron. Do not invent a production environment or invoke the strict
publish orchestrator as generation-only.

Each controller report must represent a complete successful actual shell run,
not replay/component output: three unique projects per run, all three successful
and no failed/quarantined projects, `test_only: true`,
`shell_executed: true`, `publication_enabled: false`, `n5_complete: false`,
terminal stage `completed`, exit 0, stage evidence paths and distinct
failure/recovery observation files within a valid marked root. Three manifests
must use distinct roots and pairwise-distinct project-ID sets: **nine distinct
project executions across three runs**. A positive initial run may count only
if it meets the same contract. Preserve controller state/reports and failures.

**Positive acceptance:** at least one full/reels render per run from approved
frozen source/script/evidence; all hashes and technical QA retained; three
successive distinct topic sets at the exact candidate image/revision; injected
failure and actual entrypoint recovery preserve successful artifacts, quarantine
and state without duplicate effects; upstream acquisition/director/TTS
boundaries independently exercised under their approved isolation and provider
controls. Record exact command, environment/dependency hashes, output hashes,
exit status, elapsed time, test counts/skips, log/report paths and reviewer.

**Negative acceptance:** stale/missing/forged/changed report or manifest,
repeated run roots/IDs, absent failure/recovery observations, nonzero shell,
missing rendition/stage artifact, failed or quarantined requested project,
network isolation not demonstrated, invalid freshness policy, changed source
fingerprint, any skip in the controller's fixed strict suite, or acceptance
controller `blocked_*` result prevents G5. Do not fabricate manifests or
hand-author pass reports. Test-only renders cannot satisfy editorial approval.

**Gate G5:** strict controller returns accepted evidence at the candidate
revision with valid reports and zero strict-suite failures/errors/skips; all
nine project executions and the failure/recovery run are verified; upstream
boundaries have separately qualified evidence; no live side effect occurred.
A controller suite pass with missing rehearsal inputs is a block, not a partial
release pass.

### Phase 6 — Human sample acceptance (W9, N6)

**Scope:** present three representative full/Reels pairs with an agreed
reference and collect authorized independent review and disposition.

**Dependencies:** G5 and D-04; D-01/D-02/D-03 resolved for the actual sources,
reviewers and assets in the samples.

**Positive acceptance:** an authorized reviewer assesses each actual rendered
breaking-update, data-heavy and explanatory pair for factual support and
attribution, rights, Vietnamese pronunciation, narration/audio, caption wording
and readability, safe areas, visual relevance/design, pacing and completeness.
Record reference comparison and rubric scores (the plan's proposed rubric is
at least 4/5 each for accuracy, editorial value, narration/audio, visuals and
captions, zero critical fact/rights/safety issue, subject to explicit owner
acceptance); bind review to exact artifact hashes and reviewer identity.

**Negative acceptance:** unsupported/archive claims, missing rights, synthetic
visual presented as real evidence, unreviewed Reels, unclear names/numbers,
caption/audio mismatch, critical factual/safety issue, missing reference or
unauthenticated/agent-only signoff rejects the sample. Do not improve a score,
change samples or lower a threshold to force a pass.

**Gate G6:** all three pairs are human-approved by the authorized reviewer with
recorded decisions on exact hashes and agreed rubric. A successful render,
validator score or user authorization to proceed conditionally is not sample
approval.

### Phase 7 — Merge, validate, production synchronization and generation-only run (W9, N7)

**Scope:** integrate task and main without loss; review and test the merge
commit; synchronize and hash-verify the isolated server candidate; synchronize
the exact approved revision to production main/server; run generation-only and
verify recovery.

**Dependencies:** G0–G6; D-01–D-04 and D-06 resolved where applicable; D-05
operational facts recorded; no unresolved unknown external effects. The user
has already authorized this conditional merge, production synchronization and
generation-only run once the gates pass, so do not seek redundant deployment
approval. D-07 is not needed for a genuinely generation-only run that cannot
publish or create/activate publication work; it remains mandatory for any
external publication.

**Pre-merge safety protocol:** on the exact local worktree, verify `pwd`,
`git rev-parse --show-toplevel`, branch, HEAD, `git status` and upstreams. Before
any merge, record immutable snapshots of main/task HEADs, their merge base,
worktree status, and a backup/ref or bundle sufficient to preserve both
histories; retain uncommitted/ignored user state separately and never reset,
stash, overwrite, or clean it. If either side is dirty or changed concurrently,
stop and preserve it. Inspect both histories and all changed files, explicitly
resolve divergence, and integrate both main and task commits. Do not assume a
fast-forward is possible or that a rebase is safe. Resolve conflicts without
reverting unrelated content. Review the exact resulting merge diff and
requirement coverage. Run the focused then relevant broad/strict validation on
the exact merge commit in the isolated runtime. Only after it passes may that
exact tested merge commit be pushed to GitHub; never push an untested merge or
force-update a shared branch. Passing these conditions fulfills the user's
conditional authorization to deploy/synchronize and run the exact candidate;
record the exact target and revision rather than requesting that authorization
again. It does not authorize new/modified cron or publication.

**Isolated validation synchronization:** before SSH, announce whether the action
is synchronization, setup, execution, validation or read-only inspection and
name the exact isolated target. Snapshot its branch/HEAD/status and queue/state
metadata. Do not blindly overwrite dirty state or use live production queues.
Synchronize only the reviewed tested commit; verify the full expected hash and
changed-file hashes before setup/tests/renders. If remote history is not a
fast-forward of the intended base, stop for reconciliation, never reset. Keep
unknown queue/claim/publication states and backups; never restore stale queues.

**Production synchronization and run:** after the isolated candidate passes,
use the already authorized production target identified by the release evidence.
Before sync, snapshot production checkout/image/revision, worktree/runtime
status, queues, reservations, claims and publication records; preserve unknown
states and ensure recovery evidence is usable. If production is dirty,
concurrently changed, non-fast-forward, or its state cannot be safely preserved,
stop without overwriting it and report the blocker. Synchronize the exact tested
merge commit to production main/server, verify full commit and relevant file
hashes, and capture the resulting deployment evidence. Then execute only the
validated generation-only route at that exact revision, within the separately
approved spend cap. Verify artifacts and before/after queue, claim, reservation
and publication state; prove no publication or unintended queue activation.
This is the authorized conditional production run, not a request for another
deployment approval.

**Generation-only acceptance:** the exact route is validated to generate
artifacts without publishing or creating/activating publication work; approved
spend is bounded and reconciled; source/evidence and render gates pass; generated
outputs receive required human review; no unexplained side effect or unknown
external outcome remains. `scripts/run_strict_docker_publish.sh` is not a safe
substitute because it includes publish stages, and `--rehearsal-bundle` is
test-only. Implement and test the safe route locally, then synchronize the
reviewed code; do not infer or invent production flags.

**Gate G7:** both histories integrated; exact merge commit reviewed, tested in
isolation and pushed; production baseline snapshots/recovery record retained;
production main/server contains the exact approved hash; the generation-only
run completed at that hash within approved spend, with reviewed artifacts and
verified absence of queue/publication side effects. Any dirty state, hash
mismatch, non-FF ambiguity, unbounded spend or unknown outcome halts execution
pending safe reconciliation.

### Phase 8 — Schedule activation and real observation (W9, N7)

**Scope:** record the actual scheduler and existing approved schedule; obtain
a separate owner decision before any new/modified cron or schedule activation;
observe an already authorized scheduled execution and recovery; separately
request publication authorization if desired.

**Dependencies:** G7 and D-05 operational evidence; D-07 before any publishing.
The conditional production sync and generation-only run at G7 are already
requested/authorized once gates pass. That does not authorize new or modified
cron, schedule activation, or publication; obtain those distinct decisions.

**Proposal must state:** exact commit/image and target, actual scheduler/user/
timezone and proposed diff, volume/deadlines, source policy/freshness, approved
providers and caps, alert destination, state/queue snapshot and isolation,
rollback revision/owner, unknown-outcome reconciliation and human-approved
observation window. Do not infer actual installed cron from repository config.

**Positive acceptance:** do not activate a new or modified schedule without its
separate owner decision. For an already-authorized schedule, observe at least
one real scheduled run and the owner-agreed real-time observation window (the
older plan suggests 24–72 hours as a proposal, not an approved value). Capture
timestamps, run IDs, source freshness, output/review evidence, deadline, spend,
heartbeat, alerts, queue state, partial failures and recovery from actual logs.
A platform failure is reported degraded even if unrelated platform success
exists.

**Negative acceptance:** missed/duplicate run, overlapping generation, stale
source, unsupported content, budget breach, unreviewed sample, absent heartbeat,
missing/late alert, unknown submission/upload, queue drift, unsafe cleanup or
failed rollback rehearsal blocks stable-completion claim. Do not simulate time
or use accelerated rehearsals as a real observation window.

**Rollback:** disable only the newly authorized schedule; retain queues,
unknown claims, reservations, reports and generated artifacts; restore only the
approved prior code/image after reconciling external actions. Never restore a
stale queue snapshot that could repeat a completed publication. Keep stable
checkout untouched unless exact deployment authorization covers it.

**Gate G8 / definition of operational completion:** G0–G7 evidence is complete;
the conditional production sync and generation-only run are evidenced at the
exact target/revision with snapshots, recovery path and reconciled outcomes;
any new/modified schedule is separately authorized and its real observation
window evidenced; alerts/recovery and rollback are demonstrated. Publication
remains separately blocked unless D-07 explicitly authorizes its exact scope.
No “complete” claim until actual sample content is human-reviewed and an
authorized real schedule has been observed for the agreed window.

## Evidence record required at every gate

For every task and gate retain: task ID and outcome; status label; owner and
blocker; exact repository revision/image/check-out; exact invoked interface and
redacted environment/policy values; start/end time and exit status; test counts
including skips; positive and negative case mapping; artifact/log/report paths
and SHA-256 hashes; reviewer decision bound to artifact hashes; queue/claim/
reservation before-and-after snapshots where applicable; known limitations and
next action. Preserve failure evidence and acceptance-controller state for
resume/audit. Never claim a process is running in the background unless directly
observed; this plan creates no background work.

## Pending checkpoint — 2026-10-11, base `cf0ef91`

This is a pending slice record, not a release declaration or replacement for the original requirements and gates above. The 2026-10-11 implementation slice covers: run-wide inherited `flock` singleflight before state/provider work; fail-closed local image/CSS asset checks, removing basename lookup and placeholder replacement; music accepted only when supplied music is nonempty, has a finite measured duration greater than five seconds, and is byte-distinct from narration, with no test-music fallback; and accurately distinguishing source-only font fixtures from real fonts. Luna also fixed a Codex fixture mismatch and nonportable `awk` acceptance of `1e999`.

Authoritative isolated remote validation ran at `/home/ubuntu/OpenMontage-daily-news-release-verify-cf0ef91` with image `sha256:899dd409a10ce38b32d769d00a263ab3357bddd08f293ba544d898cdf7b6ed50`, network disabled, UID 1001. Seven implementation/test SHA256 values were checked equal. `release-focused-luna.xml`: 96 passed, 0 failures. The final combined fixed `SUITE` + `tests/test_strict_generation_singleflight.py` + `tests/contracts` run, `release-regression-final.xml`, completed with 1,376 passed, 7 skipped, 19 subtests in 244.91s, exit 0. Separately, fixed `SUITE` + `tests/test_strict_generation_singleflight.py` + `tests/contracts/test_news_asset_integrity.py` completed in the same isolated snapshot/container with 256 passed, 10 subtests, 0 skips/failures in 25.64s, exit 0 (`release-strict-final.xml`). The seven skips belong to the combined regression run; the separate strict run had zero skips. `bash -n` passed for both shell scripts. An earlier broad run found a missing-font source-badge fixture; it was fixed before the final remote runs. This resumed checkpoint uses remote test results only; no local test run is claimed.

W4/W5 have partial progress only. W1 authenticated review and W2–W9 remain open, as do the original requirements and gates. Engineering blockers include authenticated source/claim review and handoff, rendition/caption qualification, complete asset and actual-font/dependency validation, durable state/recovery and spend enforcement, and isolated full-entrypoint rehearsal evidence. Owner decisions and release approvals remain blockers where the earlier phases specify them. The supervisor synchronized and validated the isolated candidate over SSH without authoring source remotely. The task-branch checkpoint is about to be committed and pushed; no main merge, production deployment, cron change, paid generation, editorial approval, or publishing occurred, and production remains unchanged. Do not declare all code complete or advance a release gate based on this slice.

## Explicit non-goals and stop conditions

This runbook records the user's authorization to implement the release work
and, after all applicable gates pass, conditionally merge/push, synchronize the
exact candidate to production main/server and execute a generation-only run.
It does not decide source/rights/freshness policy, authenticated editorial
approval, providers or spend caps, approve sample content, authorize external
publication, or authorize new/modified cron. Exact production target, revision,
snapshot, and recovery evidence are mandatory release records, not redundant
permission requests. Stop at any stage for missing policy decisions, dirty or
concurrent user state, hash/revision mismatch, inadequate isolation, changed
remote state, unrecognized queue status, failed/skipped strict gate, unbounded
spend, unresolved external outcome, or unsupported source/content. Preserve
state and report the observed blocker; do not weaken thresholds, self-approve,
or continue through an unverified path.
