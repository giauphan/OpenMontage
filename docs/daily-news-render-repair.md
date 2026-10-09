# Daily news render repair — local runbook

## Scope and status

This is a documentation-only record of an isolated render-repair rehearsal. It is not a production approval, deployment procedure, or claim that news content is verified. The production checkout was unchanged; application code did change on the task branch. No paid generation calls were made, and nothing was published.

The local task context was base `e3a5efe`, branch `task/daily-news-render-repair`. Coding was local and used the requested `openai-subscribed/gpt-6-luna` model. Remote execution, when performed for this rehearsal, was isolated to `/home/ubuntu/OpenMontage-daily-news-render-repair`; it did not target the stable checkout. The disposable container used the existing image `sha256:899dd409a10ce38b32d769d00a263ab3357bddd08f293ba544d898cdf7b6ed50`, ran as non-root UID 1001, and had no credentials. Existing `node_modules` supplied Playwright; HyperFrames was 0.7.111. These are run-context facts, not prerequisites for a live deployment.

## Rehearsal evidence

The ignored `projects/render-freeze-rehearsal` project was corrected for the rehearsal. Both HTML compositions passed nine browser samples in forward, reverse, and repeat playback. Both passed HyperFrames lint, validate, and inspect with no errors. The original read-only negative case failed as intended because of excessive timeline duration (`10000000046.6 sec`), not because of playback time.

| Output | Duration | Static-frame ratio | Edge density | Mean audio (`volumedetect`, dBFS) | Integrated loudness | True peak |
|---|---:|---:|---:|---:|---:|---:|
| MP4 | 71.066667 s | 0.8705440765921948 | 0.03631758133112401 | -18.5 dBFS | -15.51 LUFS | -2.73 dBTP |
| Reels | 58.033333 s | 0.8506605505494576 | 0.036671323867478026 | -18.3 dBFS | -15.37 LUFS | -2.73 dBTP |

The existing strict gate exited 0; no thresholds were changed. These measurements establish only that these sample outputs passed that gate, not that they meet an independently approved quality target. Captions synchronization was not established. Archived unsupported statements remain in the technical sample, so it is **not publishable**.

The final test/contracts run, including `tests/tools/test_newsnow_pipeline.py` and `tests/test_codebase_updates.py`, reported 1057 passed, 7 skipped in 126.43 seconds. This is the supplied rehearsal result; this documentation change did not rerun tests.

## Evidence limitation and required acceptance work

The research fixes block insufficient evidence rather than inserting fabricated generic expert, performance, angle, or source filler. That is an important guard, but it does not prove that surviving claims are true. Before any publishable run, require per-claim dated evidence and a freshness gate, with traceable sources and review outcomes. Define stale/missing/contradictory evidence behavior as a block, not a silent fallback.

Acceptance remains open until all of the following are completed and reviewed:

1. Complete per-claim evidence, dates, source traceability, and freshness-gate behavior.
2. Three distinct current-topic dry rehearsals, including failure recovery.
3. An approved live-run budget and approved quality/sample reference.
4. Separately authorized deployment and a monitored cron window.
5. Caption synchronization and content review, plus explicit release approval for each publishable output.

Do not claim the full plan is complete. Do not publish the archived sample or infer verified claims from the rendering checks.

## Safe validation reference

The rehearsal used HyperFrames CLI checks (`lint`, `validate`, `inspect`) and browser sampling against the isolated project. The real seek-harness invocation shape is:

```sh
node scripts/verify_hyperframes_seek.cjs projects/render-freeze-rehearsal/<composition-dir> \
  --options projects/render-freeze-rehearsal/<options-file>.json \
  --output projects/render-freeze-rehearsal/<seek-report-dir>
```

Replace the angle-bracketed paths with the actual local composition directory, a JSON options file containing `timelineId` and at least two unique `{ "time": ..., "activeScene": ... }` samples for at least two distinct scenes, and a report output directory. This example shows the interface only: the script does not generate the project or options file, and a stock clone does not contain this rehearsal's generated project. Optional `--playwright-module <file-or-dir>` (or `PLAYWRIGHT_MODULE`) selects the Playwright module when it is not resolvable as `playwright`; optional `--executable-path <browser>` (or `PLAYWRIGHT_EXECUTABLE_PATH`) selects a browser binary when the default Chromium executable is unsuitable. The harness tests direct GSAP timeline seeking in a real browser, not HyperFrames renderer parity.

The actual test invocation bootstrapped FFmpeg and ran pytest in the same Python process, in the isolated remote checkout:

```sh
.venv/bin/python -c "import static_ffmpeg,pytest; static_ffmpeg.add_paths(); raise SystemExit(pytest.main(['tests/contracts','tests/tools/test_newsnow_pipeline.py','tests/test_codebase_updates.py','-q','--tb=short','-p','no:cacheprovider','--junitxml=projects/render-freeze-rehearsal/qa/regression-results.xml']))"
```

These commands record validation already reported above; they were not run locally for this docs edit and are not instructions to run against production. Keep future rehearsals isolated and credential-free unless separately authorized. Do not copy generated media into Git. This runbook deliberately contains no publish, deploy, or cron activation command.