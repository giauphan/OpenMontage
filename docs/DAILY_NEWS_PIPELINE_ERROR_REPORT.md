# Daily-News Pipeline Error & Audit Report

**Date:** 2026-10-10  
**Scope:** OpenMontage Daily-News Pipeline & Completion Plan Audit  
**Status:** Incomplete; Pipeline encounters generation validation errors; initial stabilization patches implemented and tested.

---

## 1. Executive Summary

The daily automated news pipeline cron (`run_strict_docker_publish.sh`) runs at 23:00 UTC daily. Recent production runs have failed at **Stage 3 (Generation)** due to strict artifact validation errors:
> `ERROR: missing or invalid script artifact and both compositions`

This report details the root causes of pipeline failures, summarizes the deep audit findings across editorial, media, and operational layers, documents the implemented stabilization fixes, and outlines the remaining gates required before production activation.

---

## 2. Pipeline Failure Analysis (Cron / Generation Stage)

### Observed Symptoms
- Cron logs show generation attempts 1 and 2 failing with exit code 1.
- Affected candidate projects (`cand_*`) fail the director validation gate because they lack valid script artifacts (`script_vi.json`) or required composition directories.
- Failed projects are automatically moved to quarantine (`projects/_failed_generation_recovered/`).

### Root Causes
1. **Director Output Inconsistency:** The automated director / generation model occasionally produces malformed, incomplete, or unvalidated script structures that fail `schemas/artifacts/script.schema.json` validation.
2. **Strict Evidence Hashing Gate:** Evidence v2 strict validation (`lib/news_evidence.py`) rejects canonical scripts whose byte hash does not match expected evidence or when required sections/claims are missing.
3. **Upstream Source/Date Ambiguity:** Prior fallback behaviors accepted retrieval timestamps as publication dates, leading to stale or unverified items entering candidate selection.

---

## 3. Deep Audit Findings

A comprehensive 3-Luna review identified several systemic architectural gaps across three domains:

### A. Editorial & Source Intake
- **F01 (Timestamp Defect):** `newsnow_feed.py` previously fell back to current UTC time when publication dates were missing, disguising retrieval time as fresh news.
- **F02 (Capture-to-Review Gap):** Feed summaries lacked underlying article capture and structured proof-of-provenance for editorial sign-off.
- **F03 (Script Immutability):** Normalization and retry passes could rewrite canonical script bytes after review binding.

### B. Media & Rendition Lifecycle
- **F04 (Truncated Reels):** Reels audio was frequently truncated or copied from full narration rather than independently edited.
- **F05 (Unverified ASR):** Caption generation `--no-script-comparison` bypassed verification against approved wording.
- **F06–F08 (Asset & Template Provenance):** Fallback mechanisms could silently substitute generic placeholders or modify templates after hash recording.

### C. Operations & Durability
- **F09–F10 (Concurrency & State Racing):** Monitoring writes and process execution lacked complete multi-process file locking (`flock`) and atomic replacement, risking history corruption.
- **F11–F13 (Uncertain Uploads & Budgets):** Publisher sessions and cost tracking lacked robust durability across process crashes and API disconnects.

---

## 4. Implemented Fixes & Verified Slices

The following verified code changes have been authored, tested against **352 regression and contract tests** (zero failures/skips), and synchronized:

1. **Date Integrity & Rejecting Undated/Future Items (`tool/news/`):**
   - Removed fallback to current time for missing publication dates.
   - Added explicit rejection diagnostics for unknown (`unknown_published_at`) and future (`future_published_at`) publication dates.
   - Guarded feed batch processing against malformed non-dictionary items.

2. **Immutable Script Binding (`scripts/validate_newsnow_director_artifacts.py`):**
   - Enforced strict SHA-256 byte binding when `news_evidence.json` exists, preventing normalization/rewrite passes from silently mutating reviewed scripts.

3. **Concurrent-Safe Durable Monitoring (`scripts/pipeline_monitoring.py`):**
   - Added POSIX `flock` serialization around monitoring reads and appends.
   - Implemented atomic replacement via unique temporary files and directory `fsync`.
   - Ensured corrupt history raises explicit errors rather than silently clearing the event log.

4. **Review-Pending Source Capture (`lib/news_source_capture.py` & CLI):**
   - Added bounded, allowlisted HTTPS source capture with IP pinning, TLS SNI verification, redirect validation, and a 20-second supervised worker deadline.
   - Produces immutable revision artifacts (`.raw`, `.extracted.json`, `.provenance.json`) marked `pending_editorial_review` without auto-approving evidence.

---

## 5. Remaining Release Gates

Production activation requires passing all four separate completion gates:

| Gate | Status | Required Action |
|---|---|---|
| **Code Complete** | Partial | Core validation and capture primitives implemented; director output stability pending. |
| **Technical Rehearsal** | In Progress | Requires 3 successive full rehearsals (`run_daily_news_pipeline.sh --rehearsal-bundle`) with hash-bound evidence. |
| **Editorially Approved** | Open | Real editorial review of captured sources, claim worksheets, and sample full/Reels videos. |
| **Operationally Complete** | Blocked | Authorized deployment, canary generation test, and observed real-time cron schedule. |

### Recommended Action Items
1. **Stabilize Director Generation Prompting:** Add stricter schema enforcement and prompt instructions to prevent generation of invalid script structures.
2. **Execute Controlled Dry-Run Generation:** Test candidate generation interactively with the updated validation guards to isolate why recent cron runs produced invalid script artifacts.
3. **Complete Editorial Review Workflow:** Integrate the new `capture-source` CLI tool into the editorial intake checklist.
