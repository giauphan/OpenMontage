# Multi-shot AI video pipeline — operator guide

Instruction-driven pipeline that turns a topic into a final video from **2 or
more** independently generated AI clips, preserving character/style/continuity
across shots and supporting retry, resume, and single-shot regeneration. Every
generation request is stateless: the pipeline owns the story memory; a video
provider is only a renderer for the current shot.

## Layout

```
lib/multishot_schemas.py      — cross-field validators (8 JSON schemas in schemas/multishot/)
lib/multishot_workspace.py    — project workspace + crash-safe run manifest
lib/multishot_prompt_builder.py— self-contained per-shot prompt
lib/multishot_continuity.py   — continuity engine (accepted state, stale propagation)
lib/multishot_references.py   — reference/keyframe store + invalidation
lib/multishot_jobs.py         — provider-neutral job boundary + bounded-concurrency scheduler
lib/multishot_media.py        — ffprobe validation, normalization, ordered concat
lib/multishot_final.py        — audio/subtitle master + fail-closed completion gate
lib/multishot_metrics.py      — §8 observability aggregation
pipeline_defs/multi-shot.yaml — stage manifest (idea→…→compose)
skills/pipelines/multi-shot/  — director skills per stage
```

Python is tooling/validation/persistence only. The agent orchestrates via the
stage manifest + director skills; there is no Python orchestrator.

## Stage order

`idea → story → identity → shot_plan → planning → assets → edit → compose`

Each stage is resumable and idempotent. Deterministic ordering and shot
filenames come from `shot_plan.json`, never from directory listings.

## Fail-closed gate

Finalization is blocked when any of the following is true: shot count < 2,
a required shot is missing or failed or stale, a normalized clip is corrupt,
shot order is unresolved, or the final duration / resolution / FPS is invalid.
`validate_final_master` returns the offending checks; `can_transition_to_completed`
permits COMPLETED only from `FINALIZING` with a clean validation. There is no
"best-effort final.mp4" when mandatory shot data is incomplete.

## Resume / retry / regeneration

- **Resume** — a prior run's completed shots (by file path) and any known
  in-flight handle are reused without re-submission; remaining shots continue.
- **Single-shot retry** — a transiently failed shot re-runs only itself with
  its identical `continuity_in`; downstream is untouched until the shot is valid.
- **Single-shot regeneration** — a materially changed end state marks every
  later shot `STALE` (`mark_downstream_stale`); a changed character master
  invalidates every derived keyframe (`invalidate_dependent_jobs`).

Retry policy: capped exponential backoff + jitter + provider retry-after.
Retryable codes (rate limit, 5xx, timeout, download, job failure) retry;
permanent codes (auth, quota, invalid input, safety) never loop.

## Observability

`summarize_run` emits the §8 metrics (project/planning/generation/normalization/
final-render time, attempts per shot, provider failure count by code, raw vs
final duration) with dimensions provider/model/project/shot/error-type.

## Media target

Canonical output is the `tiktok` profile: 1080×1920, 30 fps, H.264, yuv420p.
Mixed source clips are normalized to this target before ordered concat.

## Tests

`tests/contracts/test_multishot_m{1..5}.py` + `test_multishot_{schemas,workspace,manifest}.py`.
Run on `sandbox-video` (ffmpeg-backed media tests skip where the binaries are
absent):

```bash
.venv/bin/python -m pytest tests/contracts/test_multishot_*.py -q
```
