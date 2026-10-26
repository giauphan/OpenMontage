# OpenMontage — Root Cause Investigation & Remediation Plan

**Target Commit SHA**: `2b8b8b09ae31c63e13ee370530310ae83f4b973f`  
**Date**: 2026-10-26  
**Auditor**: Independent Principal Systems Architect & Video Pipeline QA Lead  
**Scope**: Reproduction and remediation of all 10 known blockers from `plan/feedback/feedback-today.md`.

---

## Item 1: `local` Declaration in Top-Level Shell Scope
- **File & Location**: `scripts/run_daily_news_pipeline.sh:272`
- **Status**: **REPRODUCED & FIXED** (Commit `2b8b8b09`)
- **Severity**: **P0 — Blocker** (Crashed pipeline on startup)
- **Reproduction Steps & Evidence**:
  - Command: `bash -c 'local edge_tts_cmd="edge-tts"'`
  - Exit Code: `1`
  - Runtime Error: `bash: line 1: local: can only be used in a function`
  - Note: `bash -n scripts/run_daily_news_pipeline.sh` exited 0 because `bash -n` only checks grammatical syntax, not execution-context constraints.
- **Root Cause**: An author attempted to define a local variable outside a function body inside the main project loop.
- **Remediation**: Removed the top-level `local` declaration at line 272; preserved the scoped `local edge_tts_cmd` inside `materialize_hyperframes_assets()` (line 873). Verified via `bash -c 'bash -n ...'` and full dry-run execution.

---

## Item 2: Missing `FixedNicheScopeGate` in Daily News Pipeline
- **File & Location**: `tools/news/news_pipeline_cli.py:57-110`, `scripts/run_daily_news_pipeline.sh:150-220`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P0 — Blocker** (Off-niche content generation)
- **Reproduction Steps & Evidence**:
  - Grepping `FixedNicheScopeGate` across `tools/news/` and `scripts/run_daily_news_pipeline.sh` yields 0 occurrences.
  - Production logs (`logs/cron_pipeline.log`) show the daily pipeline selected and rendered off-niche topics:
    - `cand_7d9acfe4bef468f1`: *MiniMax M3.1 Flash* (general AI model launch)
    - `cand_a7e88d0582d65dc9`: *AllModels* (general AI directory)
  - Both topics violate `blocked_topics` in `config/niches/us-ai-agent-engineering.locked.yaml`:
    - `generic_ai_news`
    - `model_launch_without_agent_impact`
- **Root Cause**: `FixedNicheScopeGate` was implemented and tested solely within `lib/fixed_niche/` and `scripts/run_fixed_niche_video.py`. The production entrypoint (`run_daily_news_pipeline.sh`) continues to invoke the unconstrained `tools/news/news_pipeline_cli.py` with `CodexNewsSelector`.
- **Remediation Plan**:
  1. Wire `from lib.fixed_niche.gate import FixedNicheScopeGate` into `tools/news/news_pipeline_cli.py` prior to candidate project initialization.
  2. Reject any candidate whose `FixedNicheScopeGate.evaluate(candidate).status != ScopeVerdictStatus.ALLOWED`.
  3. If no candidate passes the gate, return exit code 0 with status `NO_ELIGIBLE_TOPIC`.

---

## Item 3: Generic 3-Videos-Per-Day Quota vs `never_force_daily_quota`
- **File & Location**: `scripts/retry_daily_pipeline.sh:45-55`, `deploy/openmontage.cron:42`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P1 — High** (Infinite loops / forced off-niche generation)
- **Reproduction Steps & Evidence**:
  - `deploy/openmontage.cron` runs `retry_daily_pipeline.sh` hourly with `EXPECTED_SUCCESS_COUNT=3`.
  - When fewer than 3 videos are scheduled, `retry_daily_pipeline.sh` re-launches the full generation pipeline.
  - In `config/niches/us-ai-agent-engineering.locked.yaml`:
    ```yaml
    content_rules:
      unavailable_evidence_action: SKIP
      insufficient_topic_action: NO_ELIGIBLE_TOPIC
      never_force_daily_quota: true
    ```
- **Root Cause**: Legacy Vietnamese production targeted 3 videos per day (morning, afternoon, evening). The fixed-niche policy explicitly permits zero-topic days when no verified evidence exists.
- **Remediation Plan**:
  - Update `scripts/retry_daily_pipeline.sh` to check whether `insufficient_topic_action == NO_ELIGIBLE_TOPIC` has been flagged in `logs/pipeline_monitoring_report.json`. If flagged, exit 0 without retrying.

---

## Item 4: Fail-Open Fact-Checking & Self-Generated Snapshots
- **File & Location**: `scripts/bind_news_evidence.py:121-125, 202-212, 268-285`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P0 — Blocker** (Evidence integrity & hallucination risk)
- **Reproduction Steps & Evidence**:
  - In `scripts/bind_news_evidence.py`:
    - Lines 121-125 fabricate source retrieval and publication timestamps:
      `pub_time = now - timedelta(hours=2)`
    - Lines 202-212 write synthetic source files: `artifacts/source_evidence_s*.txt` composed from the model's own brief (`research_brief.json`).
    - Lines 268-274 approve en-US claims if at least 2 tokens match `frozen_research_excerpt`. Any generic statement sharing words like "code" and "agent" is marked `confidence: verified` and `review_status: approved`.
- **Root Cause**: The evidence binder was designed as an automated synthetic bridge to satisfy downstream schemas rather than performing external fact-checking against authentic captured sources.
- **Remediation Plan**:
  - Adopt `lib/fixed_niche/factcheck.py` in the daily pipeline:
    1. Demand genuine source captures in `artifacts/news_source_capture/` from canonical URLs.
    2. Check claim assertions against captured primary text using semantic entailment or strict sentence-level attribution.
    3. Fail closed (`confidence: unverified`, `review_status: rejected`) if claims cannot be substantiated.

---

## Item 5: Static Feed Recycling vs Live Discovery from Approved Sources
- **File & Location**: `scripts/run_strict_docker_publish.sh:367`, `tools/news/newsnow_feed.py`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P1 — High** (Stale content & vendor unreliability)
- **Reproduction Steps & Evidence**:
  - Log excerpt: `existing NewsNow feed age: 1h (max allowed: 48h)`.
  - The pipeline reuses `data/newsnow_feed.json` for up to 48 hours without fetching fresh primary releases.
  - Policy requires discovery from: Hacker News, GitHub Issues/Releases, ProductHunt, official vendor changelogs.
- **Root Cause**: The daily orchestrator relies on NewsNow RSS scraping with local file caching, whereas the fixed-niche specification defines multi-source live discovery in `lib/fixed_niche/discovery.py`.
- **Remediation Plan**:
  - Replace the NewsNow scraper with `lib.fixed_niche.discovery.discover_sources()` when `OPENMONTAGE_LOCALE=en-US`.

---

## Item 6: TTS Speech Duration Fitting & Retiming
- **File & Location**: `scripts/run_daily_news_pipeline.sh:873-975`
- **Status**: **REPRODUCED & FIXED** (Commits `160360ea` and `2b8b8b09`)
- **Severity**: **P0 — Blocker** (Previously caused duration contract violations)
- **Reproduction Steps & Evidence**:
  - On the Docker host, `edge-tts` is located at `/app/.venv/bin/edge-tts` and was not in the system `PATH`.
  - When narration duration measured 64.4s (outside [65.0, 75.0]s), the rate adjustment loop was skipped.
  - Commit `160360ea` added:
    1. Robust resolution of `edge_tts_cmd` from `/.venv/bin/edge-tts`.
    2. A multi-rate sweep (`+5%..+30%`, `-5%..-20%`).
    3. An `ffmpeg atempo` filter fallback adjusting audio within `[55.0, 85.0]s` to exactly `69.0s`.
    4. Scene timeline and `news_visual_plan.json` realignment to actual narration duration.
- **Verification**: Candidate `cand_1fe6d02cd35a931c` speech duration fitted cleanly to 65.136s, and all 7 visual beats realigned with no beat exceeding 10.0s.

---

## Item 7: Scene Duration <=12.0s & Meaningful Rendered Visual Coverage
- **File & Location**: `lib/news_visual/qa.py:150-242, 273-340`
- **Status**: **REPRODUCED & PARTIALLY MITIGATED**
- **Severity**: **P1 — High**
- **Reproduction Steps & Evidence**:
  - Candidate `cand_1c267eba35d74b5f` failed QA with:
    `Final visual beat 'vb-07' holds for 12.10s in final_long_en_US_16x9.mp4 (from 60.00s to 72.10s, >12.0s max)`.
  - `lib/news_visual/qa.py` strictly decodes video frames via `ffmpeg` and checks:
    - Beat duration <= 12.0s.
    - Scene standard deviation (non-blank).
    - Mean Absolute Difference (MAD) between scenes.
  - However, it does not verify semantic alignment between scene illustration and the narration topic.
- **Remediation Plan**:
  - Add visual semantic tagging check in `lib/news_visual/qa.py` matching scene keywords with section narration keywords.

---

## Item 8: Publish Queue Deduplication After Available-Slot Truncation
- **File & Location**: `scripts/schedule_youtube_today.py:80-130`, `scripts/run_strict_docker_publish.sh:658-705`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P1 — High** (Potential crash on duplicate active_projects)
- **Reproduction Steps & Evidence**:
  - In `scripts/schedule_youtube_today.py`:
    - Lines 80-118 iterate `cfg.get("active_projects", [])` without prior set deduplication.
    - Slots are assigned using `slot_times[idx % len(slot_times)]`.
    - If duplicate projects exist in `active_projects`, or if `len(active_projects) > len(slot_times)`, two entries receive the exact same datetime.
    - Line 123 then triggers: `raise RuntimeError(f"slot gap under 2h: {previous.isoformat()} -> {publish_at.isoformat()}")`.
  - In `scripts/run_strict_docker_publish.sh`:
    - Queue deduplication occurs at line 699, *after* appending entries to ``.
- **Remediation Plan**:
  - In `scripts/schedule_youtube_today.py`, deduplicate `active_projects` by `project_id` and filter for the target `publish_date` *before* the slot assignment loop (matching the pattern in `scripts/schedule_today_native.py`).

---

## Item 9: US Scheduling Using Vietnamese Slot Keys / Timezone
- **File & Location**: `config/publish_schedule.json:12-21`, `scripts/run_strict_docker_publish.sh:600-610`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P1 — High** (Audience scheduling mismatch)
- **Reproduction Steps & Evidence**:
  - `run_strict_docker_publish.sh` lines 606 & 609 query `.slots.today_publish_slots_vn` and `.slots.publish_slots_vn` (`09:15`, `14:15`, `21:15` ICT).
  - `config/audience_profiles/en-US.yaml` specifies:
    - `application_timezone: America/New_York`
    - US slots: `09:00`, `13:00`, `18:00` EDT/EST.
- **Root Cause**: The daily orchestrator was authored for Vietnam local publication and has not yet been localized to query `.slots.publish_slots_us` when `OPENMONTAGE_LOCALE=en-US`.
- **Remediation Plan**:
  - Add locale awareness in `scripts/run_strict_docker_publish.sh`: if ` == "en-US"`, read `.slots.publish_slots_us` and compute slot datetimes using `America/New_York`.

---

## Item 10: Unconditional Longform Creation Despite Policy Disabling Longform
- **File & Location**: `scripts/run_daily_news_pipeline.sh:1158-1172`
- **Status**: **REPRODUCED & OPEN**
- **Severity**: **P1 — High** (Render time waste & false-positive QA failures)
- **Reproduction Steps & Evidence**:
  - Policy contract in `config/niches/us-ai-agent-engineering.locked.yaml`:
    ```yaml
    longform:
      enabled_initially: false
    ```
  - Yet `run_daily_news_pipeline.sh` lines 1167-1170 unconditionally render `final_long_en_US_16x9.mp4`.
  - This doubled the render time (adding ~5 minutes per candidate) and directly caused `cand_1c267eba35d74b5f` to fail QA due to a 12.10s beat in the longform composition.
- **Root Cause**: Legacy architecture coupled 16:9 and 9:16 into every run.
- **Remediation Plan**:
  - In `scripts/run_daily_news_pipeline.sh`, check `if [ "0" = "1" ]`; skip longform rendering and longform QA when `format == "short"`.
