# Daily-news offline component replay

This tool has two deliberately distinct modes:

- Stage-only (`--feed`) validates and copies a frozen feed, then exits nonzero
  because it executes no pipeline stages.
- Bounded execute (`--execute --manifest`) invokes the **public**
  `CodexNewsSelector.select_and_research` and
  `CodexAgentValidator.validate_technical_contract` /
  `codex_agent_strict_review` APIs. Selector and reviewer subprocess
  boundaries are replaced with inert, manifest-supplied JSON fixture
  transports. The production technical validator and reviewer frame extraction
  stay enabled. This does not execute `scripts/run_daily_news_pipeline.sh`,
  run a renderer, or establish an N5/full-shell rehearsal.

Every execute-mode result has `test_only: true`,
`publication_enabled: false`, `shell_executed: false`, and `n5_complete: false`.
A passing result means only that the listed component stages completed using
those fixture replies and the supplied project media. It is not factual
verification, human review, publication authorization, or production evidence.
The fixture selector/reviewer adapters make no provider calls, and the manifest
loader rejects common credential filenames and secret/config directory names.
This is only path/name screening: it does not inspect allowed file contents, so
supplied fixture bundles must never contain credentials. The harness does not
enforce outbound network isolation, and some media validator subprocesses do not
have individual timeouts. The execution supervisor
must apply a hard wall-clock timeout that terminates the process group and an
egress-deny policy; do not infer network isolation from a successful replay. Do
not set either `PRODUCTION_RELEASE=1` or `STRICT_PRODUCTION=1`; the replay
refuses production mode. Use a new, empty stage directory for each run. Existing
destinations are never overwritten or removed.

## Fixture bundle contract (schema version 1)

Paths must be relative (no absolute paths or `..` traversal), remain within
the manifest directory, and may not traverse symlinks in any path component.
The project bundle is copied recursively into the fresh stage and is bounded to
500 files, 1,000 total entries, and 2 GB. Credential files (`.env*`, auth,
token, private-key, and common secret names) and common credential/config
folders (including `.ssh`, `.aws`, `.config`, `.codex`, `.claude`, `config`, and
`node_modules`) are rejected rather than copied. Keep bundles minimal. It should
contain the actual media and project inputs to inspect, including the HTML
composition, script, metadata, assets, and rendered video. The video and
metadata paths below are relative to that project bundle.

```json
{
  "schema_version": 1,
  "fixture_bundle": true,
  "feed": "fixtures/feed.json",
  "selection_reply": "fixtures/selector-reply.json",
  "review_reply": "fixtures/reviewer-reply.json",
  "projects": [
    {
      "id": "fixture-project-01",
      "bundle": "fixtures/project-01",
      "video": "renders/final.mp4",
      "metadata": "metadata.json"
    }
  ]
}
```

The feed is the frozen NewsNow JSON array expected by the news producer
(`id`, `title`, `url`, and timezone-bearing `published_at`; optional summary
fields are passed through). It must have at least three distinct, fresh items.
The selector reply is the JSON object returned at the selector transport
boundary, for example:

```json
{
  "selected_candidate_id": "fixture-topic-01",
  "research_draft": {"title": "SYNTHETIC FIXTURE ONLY"}
}
```

The reviewer reply must include all four category objects and the overall
boolean. Scores, notes, and `overall_passed` are fixture input only; they are
never treated as human approval or factual evidence:

```json
{
  "visual_quality": {"passed": true, "score": 4, "notes": "fixture only"},
  "audio_sync": {"passed": true, "score": 4, "notes": "fixture only"},
  "content_appropriateness": {"passed": true, "score": 4, "notes": "fixture only"},
  "brand_compliance": {"passed": true, "score": 4, "notes": "fixture only"},
  "overall_passed": true,
  "summary": "Synthetic response; not a human review"
}
```

At most three projects can be included per bounded run. All media must be
supplied in the bundle. The replay does not download or synthesize it. It
copies the repository's actual `scripts/run_daily_news_pipeline.sh` into the
stage only as provenance; the entrypoint is not invoked. Review the
`rehearsal-report.json` stage list and hashes rather than inferring unlisted
gates passed.

## Usage

Run only in the project's prescribed isolated execution environment after
synchronizing the reviewed local revision; do not execute against a production
checkout or live state:

```sh
python3 scripts/rehearse_daily_news_offline.py \
  --execute \
  --manifest /path/to/fixture-bundle/rehearsal.json \
  --stage-dir /path/outside/source/daily-news-replay-001 \
  --max-source-age-hours 24
```

A zero exit means the bounded component replay passed. Nonzero means preflight
or one or more replay stages failed. The report is written even when a replay
stage fails once the fresh stage has been created. Each staged project receives
`OFFLINE_REHEARSAL_TEST_ONLY.json` at the project root; the release guard rejects
any project carrying this marker regardless of project classification or force /
preflight flags. Preserve the marker with copied projects. Never reuse that
stage path. The per-project marker is a release-blocking tripwire, not a
cryptographic integrity boundary; do not remove it to make a fixture releasable.

The project-level execution policy may prohibit local test/runtime execution;
this document does not authorize running the command locally. It describes the
interface for an approved isolated execution environment.

## Historical-media QA runner

`scripts/qa_daily_news_replay.py` prepares a test-only fixture bundle from one
explicit historical project and video, then calls the existing replay twice:
first with a valid-shaped synthetic reviewer reply and next with a deliberately
malformed reviewer reply. It verifies that the malformed case records a failed
strict-review stage and that the first run's report hash is unchanged. The
runner returns success only when the valid-reply replay passes its real
technical validation, the malformed reply is rejected, and the first report is
preserved.

The script requires `--project`, `--video-relative`, and `--output-root`; it has
no production/sample defaults. `--video-relative` must name a local video file
inside the supplied project. It copies only `artifacts/script_vi.json`,
`hyperframes/index.html`, the `hyperframes_reels/index.html` composition when
the chosen video name contains `reels`, the explicitly selected video, and
synthetic publish metadata in `metadata.json`. It never reads or copies source
metadata. It does not copy other assets, evidence bundles, project
configuration paths or the rest of the sample tree. Both the output root and
staged projects carry explicit test-only markers. The real FFProbe/FFmpeg validation and representative
frame extraction are not mocked. Feed items, selector/reviewer responses, and
metadata are synthetic fixtures; neither the old script nor the historical video
is thereby fact-checked or approved for release. Source script, HTML, and video
bytes are copied as supplied; the helper does not inspect their contents for
credentials, so select only inputs approved for this isolated test.

The supervising executor must use an isolated disposable container with
network disabled (`--network none`), a fresh output path outside the source
checkout, a hard wall-clock limit, and process-group termination. Native media
subprocesses do not all set their own timeout. An invocation shape inside that
supervised container is:

```sh
timeout --signal=TERM --kill-after=30s 20m \
  python3 scripts/qa_daily_news_replay.py \
    --project projects/render-freeze-rehearsal \
    --video-relative renders/final_full_vi_9x16.mp4 \
    --output-root /tmp/daily-news-replay-UNIQUE
```

Replace `UNIQUE` with a fresh path that does not already exist. The runner
refuses existing output roots and paths inside the source checkout. Metadata is
always synthetic and source metadata is never copied. The output contains
separate reports for both fixture transports plus `qa-summary.json`. No render, news-generation
step, publication, or human review is performed.

## Full daily entrypoint frozen-bundle mode

`bash scripts/run_daily_news_pipeline.sh --rehearsal-bundle PATH` now selects a
separate frozen-input path in the **actual daily entrypoint**. It first requires
the root marker `.openmontage-rehearsal-root.json` to contain exactly
`{"test_only":true,"purpose":"daily-news-rehearsal"}`. It rejects git worktrees,
`.env` files, symlinked roots/paths, existing `projects` or `logs` state, a
pre-existing NewsNow feed, and an existing live `config/publish_schedule.json`;
it also refuses `PRODUCTION_RELEASE=1` or
`STRICT_PRODUCTION` or `PRODUCTION_RELEASE` set to any nonempty value.
`NEWS_MAX_SOURCE_AGE_HOURS` is mandatory, finite, and in
`(0, 720]`; it is validated before bundle copying and is never defaulted. This
preflight runs before `.env` sourcing, log creation, acquisition, or director
invocation. The manifest must live under the staged root and use version 1:

```json
{
  "version": 1,
  "bundles": [
    {"project_id": "fixture-one", "project_dir": "bundles/one"},
    {"project_id": "fixture-two", "project_dir": "bundles/two"},
    {"project_id": "fixture-three", "project_dir": "bundles/three"}
  ]
}
```

Each bundle is a complete project tree containing nonempty
`artifacts/research_brief.json`, `script_vi.json`, `proposal_packet.json`,
`selector_reply.json`, `director_reply.json`, `reviewer_reply.json`, and
`news_evidence.json` (the existing version-2.0, script-hash-bound evidence
contract), plus `assets/narration.mp3`, `assets/music-bg.mp3`, and both
HyperFrames `index.html` compositions. Bundle paths must stay under the manifest
folder, exactly three project IDs, selected candidate IDs, and topic titles must
be unique, and existing staged project destinations are never overwritten.
Bundles reuse the existing replay copier's symlink/credential denial plus 500-file,
1,000-entry, and 2 GB limits. After successful staging, the helper writes an
empty-active-project synthetic publish schedule for configuration loading; it
never uses or overwrites a live schedule. The selector/director reply files are
retained fixture provenance;
the director reply is copied to the director result log rather than invoking an
agent. The reviewer reply is passed to `CodexAgentValidator`'s existing public
injected review transport; the real frame/audio/quality checks and actual review
response parser still run. Captions use the existing cached-only Vietnamese ASR
path (`local_files_only=True`); no model download fallback is enabled.

The entrypoint bypasses live fetch/produce and director execution only. A guard
inside `run_directors` also rejects any accidental direct or retry-path call. Use
an explicit freshness value when invoking, for example:

```sh
NEWS_MAX_SOURCE_AGE_HOURS=24 bash scripts/run_daily_news_pipeline.sh \\
  --rehearsal-bundle /isolated/stage/manifest.json
```

It then
joins the same evidence validation, asset materialization, caption installation,
HyperFrames render, and strict quality/reviewer validation paths used by normal
runs. These renders are test outputs, not release artifacts. Each staged project
receives `OFFLINE_REHEARSAL_TEST_ONLY.json`; the shared `news_release_gate` and
publishing preflight reject projects carrying it. Rehearsal output is never
queued or published by this entrypoint. Run only in the required network-none
isolated container; this local implementation session did not execute it.
