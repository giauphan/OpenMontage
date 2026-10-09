# Daily-news evidence and caption checkpoint

**Checkpoint date:** 2026-10-09  
**Scope:** documentation of the current implementation and validation evidence; not a production release or acceptance sign-off.

## Route and status

The initial Haiku-route blocker is superseded by approval to use the native Luna coding route. This records approval of the route, not independent verification of any earlier model-identity claims. Implementation and isolated validation are partial. The release plan remains open; there is no authorization here to spend, publish, deploy to the stable checkout, or activate cron. Deployment is not authorized by this document.

## Evidence policy and limits

- Production must provide an explicit, finite source-age policy. No default source-age limit is selected or implied; missing policy or required evidence blocks production.
- Evidence validation checks structure, provenance links, timestamps/freshness, paths and hashes, review fields, and coverage. It does **not** prove semantic truth, that every assertion has been identified, that an excerpt supports a claim, or source/publisher authenticity.
- Reviewer identity and timestamp fields are recorded editorial attestations. The validator cannot authenticate the reviewer or the attestation; these fields are not proof of truth or automated approval.

## Caption implementation scope

- Captions use cached-only small ASR for full and reels, as an independent transcript path. There is no comparison against the canonical script and no human verification in this caption workflow. Do not describe these captions as script-verified or editorially approved.
- The installation adapter rejects legacy caption markup and requires the main root to contain a start-at-zero paused timeline. It inserts native timed clips and replaces only its own generated block, idempotently.
- Reels still truncates the existing full-version audio; it is not a substantive editorial recut.
- New production configuration without explicit evidence and source-age policy fails closed. Existing templates may be rejected until their legacy captions are migrated.

## Validation evidence and limits

Remote isolated QA project `projects/qa-caption-installation.Y3Ow5X` reported:

- 0 lint errors and 0 warnings;
- browser validation with no console errors and 12 WCAG text elements;
- inspect with 0 issues at 0.7, 1.7, 3.4, and 9.5 seconds;
- a 10-second silent synthetic caption fixture rendered to a 66.8 KB MP4.

A supervisor inspected the contact sheet: the first caption cue appears at 0.7 and 1.7 seconds, the second at 3.4 seconds, and there are no captions at 9.5 or 9.7 seconds. This is a limited visual fixture check, not speech-accuracy validation or human editorial acceptance.

The completed final remote broad regression reported 1249 passed, 7 skipped, and 19 subtests in 142.01 seconds. JUnit results: `projects/render-freeze-rehearsal/qa/evidence-caption-final-results.xml`. An initial shell syntax regression and a fixture-root missing start were caught and fixed.

## 2026-10-09 replay follow-up

- Evidence 2.0 declares corroboration classifications and guards distinct source IDs, publishers, normalized URLs, and content hashes. `authority_attested` is a declared classification, not authentication or proof of truth. The public selector/reviewer is injected; a test-only marker is rejected for release.
- Replay exercised an executable component, not the full shell entrypoint. It did not generate or render media. QA copied a historical MP4 and ran actual technical checks and frame extraction on that copy.
- Remote broad regression: 1,284 passed, 7 skipped, 19 subtests in 140.15s, **before** the final helper metadata fix. After that fix, targeted tests: 25 passed in 0.74s. Provenance note: one agent initially ran evidence tests locally (51 passed); the supervisor reran the revised code remotely. Do not conflate the local initial result with the remote revised-code evidence.
- Real Docker replay used `--network none`, read-only `/app`, and external output `/home/ubuntu/OpenMontage-daily-news-replay-qa/probe-20261009-02`. The valid component passed; malformed missing `audio_sync` failed, preserving the first report with SHA-256 `2a8be06bb383545db1d66f638f21fbe5f5336ce1d5743c99dade1f4391da4975`.
- QA metadata is now always synthetic; source metadata is not copied.

## Remaining release gates

- **N2:** editorial taxonomy, topic selection, and corroboration; consequential claims and corrections need editorial treatment.
- **N5:** actual transport coverage, three successive scheduled-equivalent dry runs with distinct topics, and injected failure/recovery. These are not established by the caption fixture.
- **N6:** human review of representative rendered news samples and comparison against a user-provided or agreed reference; not completed.
- **N7:** agreed budget and controlled deploy/cron activation, followed by real observation; not authorized or completed.

No stable checkout was changed. No spending or publishing occurred. No deployment or cron activation occurred. See the status and plan history in [`../plan/pending/collap-group/61_DAILY_NEWS_RELEASE_PLAN.md`](../plan/pending/collap-group/61_DAILY_NEWS_RELEASE_PLAN.md).

## 2026-10-09 rehearsal-bundle follow-up — partial, not done

The actual `scripts/run_daily_news_pipeline.sh --rehearsal-bundle` mode consumes exactly three frozen, unique evidence bundles in a marked stage isolating environment and live state; an explicit source-age policy is mandatory. Live fetch, production, director, and TTS are disabled. The mode shares existing downstream validators and caption/render stages, but a positive complete render was not run. Atomic marked copies preserve interruption state. Strict fixture review requires both markers; publication gates reject fixtures carrying either marker.

A real shell subprocess test supplied three invalid evidence bundles. Real validators rejected and quarantined all three, with no external providers invoked. Results report successful, failed, and quarantined counts plus exit status; all three bundles must succeed for rehearsal success. Remote final regression: 1298 passed, 7 skipped, 19 subtests in 144.48s. JUnit: `projects/render-freeze-rehearsal/qa/daily-entrypoint-regression-results.xml`.

Selection acquisition was skipped and is not covered. Do not call this an all-source-to-video E2E run. N5 remains open pending three complete successful runs and real recovery/resume with complete frozen input bundles. N6 human content/sample approval and N7 policy, budget, deployment, and real observation remain open. No runtime source changed in this documentation update; stable deployment state is unchanged, with no spending or publication.
