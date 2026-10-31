# OpenMontage Content Quality Baseline & Root Cause Reproduction Report

- **Date:** 2026-10-30
- **Inspected Baseline Commit:** `c2364a6f3104c8d3c0dd181eb705650291fcae96` (HEAD on main)
- **Worktree Branch:** `feat/content-quality-remediation`
- **Owner-Locked Niche Policy:** `config/niches/us-ai-agent-engineering.locked.yaml` (Practical AI Agent Engineering, US English, 65–75s contract)

---

## 1. System Inventory and Production Entrypoints

Production video generation and scheduling runs through three main entrypoints:
1. `scripts/run_daily_news_pipeline.sh`: Daily news pipeline orchestrating discovery, script, evidence binding, visual planning, TTS, rendering, and QA.
2. `tools/news/news_pipeline_cli.py`: Topic ranking, candidate selection, and pipeline initiation.
3. `scripts/run_strict_docker_publish.sh` & `scripts/retry_daily_pipeline.sh`: Strict staging, multi-project execution, scheduling into `config/publish_schedule.json`.
4. Fixed-niche pipeline: `scripts/run_fixed_niche_video.py` and `scripts/run_us_ai_director_pipeline.py`.

---

## 2. Root Cause Verification Ledger

| ID | Issue & Code Location | Mechanism Confirmed at HEAD | Reproducible Failure Scenario | Remediation Phase |
|---|---|---|---|---|
| **RC01** | `scripts/bind_news_evidence.py` (L121-125, L208-242, L284-297) | 1. Generates fake publication/retrieval timestamps relative to `now`.<br>2. Fabricates source documents from `research_brief.json` rather than requiring canonical source files.<br>3. Approves claims via simple token overlap (`min_overlap = 2`). | False claim with matching keywords passes review; unverified numeric statistics pass if present in brief. | Phase 1 (T01, T02, T03) |
| **RC02** | `tools/news/news_pipeline_cli.py` (L152-166), `scripts/run_daily_news_pipeline.sh` | Fixed-niche gate only runs if `FIXED_NICHE_MODE=1` or `OPENMONTAGE_NICHE_LOCKED=1`. When empty, off-niche topics (e.g. iPad, general consumer tech) pass into production. When no candidate passes, exits code 1 triggering retry storms. | Legacy entrypoint generates off-niche video; cron retries repeatedly when no news is available. | Phase 1 (T04, T05) |
| **RC03** | `lib/news_visual/visual_planner.py` (L282, L317, L367, L390) | 1. `claim_ids[idx % len(claim_ids)]` arbitrarily maps claims to beats.<br>2. `layouts[idx % len(layouts)]` cycles layouts regardless of scene content.<br>3. Hard-coded intent templates indexed by modulo. | Beats show unrelated claims; visual layouts are ungrounded in scene function. | Phase 2 (T06) |
| **RC04** | `scripts/prepare_news_visuals.py`, `lib/news_visual/asset_resolver.py` | Staged assets in `assets/visuals/` are not bound into HTML DOM or verified in rendered frames; fallback SVGs lack domain semantics. | Asset exists on disk but is absent from render; replaced by generic card. | Phase 2, 3 (T07, T09, T10) |
| **RC05** | `lib/news_visual/qa.py` (L656-670, L685-690, L712-715) | QA passes beats based on loose text in HTML or `typographic_focus`; visual semantic mismatches are only marked `warning`; layout repetition check only flags all-typographic scenes. | Videos with missing proof, mismatched visuals, or repetitive dark cards return `PASS`. | Phase 4 (T08, T14) |
| **RC06** | `scripts/run_daily_news_pipeline.sh` (L906-962, L949-956) | Extreme edge-tts rate changes (-20% to +30%) and atempo distortion to force 65-74.5s; equal-split retiming (`step = dur / n`) crushes or stretches scene durations arbitrarily. | Unnatural speech cadence, desynchronized visual transitions, distorted audio. | Phase 5 (T15, T16) |
| **RC07** | `scripts/run_strict_docker_publish.sh` (L596-599), `scripts/retry_daily_pipeline.sh` | Queueing hardcodes `today_publish_slots_vn` / `publish_slots_vn`; retry loops trigger without checking for `NO_ELIGIBLE_TOPIC`. | US pipeline scheduled at VN hours; infinite retries on days without eligible topics. | Phase 5 (T17, T18) |
| **RC08** | Missing module `lib/youtube_feedback/` | No automated collector mapping YouTube Analytics retention curves (ratio vs time) to scene beats for data-backed editorial hypotheses. | Retention drops cannot be attributed to specific scenes or visual formats. | Phase 6 (T19, T20) |
| **RC09** | `scripts/run_daily_news_pipeline.sh` (L967, L1233) | `prepare_news_visuals.py` executed after rendering with `|| true`, suppressing errors and leaving rendered MP4 desynchronized. | Post-render changes invalidate media contract without triggering re-render. | Phase 3 (T11, T12) |

---

## 3. Plan Traceability Matrix

Every acceptance test from `plan/pending/ACCEPTANCE_TEST_MATRIX.md` maps directly to this remediation:
- **T01–T05:** Phase 1 (Authentic Receipts, Strict Scope Gate, NO_ELIGIBLE_TOPIC Handling)
- **T06–T10:** Phase 2 (Context-Aware Visual Planner, Authentic Proof Binding, Graceful Fallback)
- **T11–T12:** Phase 3 (Strict Render Order, Pipeline Integrity, Hash Invalidation)
- **T13–T16:** Phase 4 (Frame QA, Safe Zones, Visual Repetition, Sync & Pacing)
- **T17–T18:** Phase 5 (US Eastern Scheduling, DST Safety, Slot Spacing, Quota Idempotence)
- **T19–T20:** Phase 6 (YouTube Feedback Integration, Retention Curve Mapping)
- **T21–T22:** Phase 7 (Canary Validation, Regression Testing, Production Cutover Checklist)
