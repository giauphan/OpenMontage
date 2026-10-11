# Main integration verification

**Status:** Engineering integration verified; not a Daily News release or deployment.

## Scope and merge record

After fetching, the current GitHub task branches were:

- `task/daily-news-render-repair` — `4c5518a`
- `task/daily-news-review-handoff` — `dab2693`
- `task/multishot-recovery` — `e3a5efe`

The multishot-recovery branch was already an ancestor of main. The integration candidate brought the first two branches in through `2823c4f` and `b1e944d` on top of main `c08c201`. The existing `docs/DAILY_NEWS_PIPELINE_ERROR_REPORT.md` was preserved. Seven conflicts were reconciled. Compared with the task-review branch, the resulting diff is limited to preserving that audit report and CLI import ordering.

The exact committed source archive, SHA-256 `fe159f444b48859d21269d72985de6701c0321a00e04e0b108b020a1e1b5d521`, was synchronized to the isolated server checkout `/home/ubuntu/OpenMontage-stable-merge-b1e944d` and verified there. The pinned test image was `899dd409a10ce38b32d769d00a263ab3357bddd08f293ba544d898cdf7b6ed50`. It ran with network disabled, UID 1001, all capabilities dropped, and no credentials or production mounts.

## Validation evidence

- Full `tests/` suite: **2,088 passed, 10 skipped, 20 subtests**, 410.27 seconds, exit 0. Report: `merge-full-suite-named.xml`.
- Strict fixed suite (`SUITE` + singleflight + asset integrity + claim review): **278 passed, 10 subtests, 0 skipped**, 25.80 seconds. Report: `merge-strict-final.xml`.
- `make` was unavailable. Its exact lint equivalents were run directly and passed: 11 Python files and 15 shell scripts.

The initial full-suite attempt had 27 failures caused by UID 1001 lacking a username. This was resolved for the rerun by adding read-only `/etc/passwd` and `/etc/group` mounts; no source changes were made to address the environment issue.

Skipped coverage: Backlot UI collection; optional live Kling documentation; absent golden scenario; five missing comparison-footage cases; and two opt-in HyperFrames scaffold/render cases.

## Boundaries and follow-up

No new actual render or human acceptance proof was produced. Tests do not guarantee zero bugs. Main has not yet advanced to this candidate, and CI is pending; do not describe the integration as complete or released until those are resolved.

This report covers the three current GitHub task branches, not every historical local branch. Many older local branches are superseded and require separate, precise review rather than blind merging. In particular, freeze relaxation, hue camouflage, and heuristic subtitle timing were excluded to preserve existing gates. The music-policy implementation is already on main with the same blob; the `a6ec44b` schema-test follow-up remains unintegrated. A test file for that area exists, so its absence is not a reason for omission.

No server deployment, cron change, paid API call, or publication was performed. All coding was done locally; the supervisor ran tests over SSH in the remote container. Retain all branch refs; none were deleted.
