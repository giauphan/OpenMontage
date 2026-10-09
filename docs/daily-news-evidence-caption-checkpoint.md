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

## Remaining release gates

- **N2:** editorial taxonomy, topic selection, and corroboration; consequential claims and corrections need editorial treatment.
- **N5:** actual transport coverage, three successive scheduled-equivalent dry runs with distinct topics, and injected failure/recovery. These are not established by the caption fixture.
- **N6:** human review of representative rendered news samples and comparison against a user-provided or agreed reference; not completed.
- **N7:** agreed budget and controlled deploy/cron activation, followed by real observation; not authorized or completed.

No stable checkout was changed. No spending or publishing occurred. No deployment or cron activation occurred. See the status and plan history in [`../plan/pending/collap-group/61_DAILY_NEWS_RELEASE_PLAN.md`](../plan/pending/collap-group/61_DAILY_NEWS_RELEASE_PLAN.md).
