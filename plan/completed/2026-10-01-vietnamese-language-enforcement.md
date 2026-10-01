# Completed: enforce Vietnamese throughout video production and publishing

Status: **COMPLETED — verified on remote isolated sandbox-video worktree**
Date: 2026-10-01

## Summary

Enforced natural Vietnamese prose across all audience-facing text (titles, descriptions, narration inputs, captions). English is permitted only for specialized technical terms (API, GPU, Docker, AI, etc.).

## Changes

1. `tools/narration_text.py` — Added `_VIETNAMESE_DIACRITICS` (full NFC set), `_VIET_NO_DIAC`, `_ENGLISH_STOP_WORDS`, `_DEFAULT_TERMS`. Implemented `check_vietnamese_prose()`.
2. `scripts/validate_publish_metadata.py` — Added Vietnamese prose validation on title+description.
3. `scripts/validate_newsnow_director_artifacts.py` — Fail-closed fallback synthesis for non-Vietnamese brief titles.
4. `tools/publishers/youtube_publisher.py` — Prose validation before credential/network checks.
5. `scripts/schedule_today_native.py` — Pre-claim validation gate.
6. `tests/tools/test_vietnamese_enforcement.py` — 5 regression tests.

## Evidence

All 5 regression tests pass on sandbox-video isolated worktree:
- test_language_heuristics
- test_metadata_validation_enforces_vietnamese
- test_director_artifacts_enforces_vietnamese
- test_youtube_publisher_rejects_english_prose
- test_schedule_today_native_blocks_invalid_metadata

Acceptance criteria 1-7: addressed via heuristic rejection, fail-closed boundaries, technical-term whitelist, and isolated remote testing. No public videos modified or re-uploaded.

## Rollback

Revert commit `dfad6c7` and subsequent branch work via `git revert dfad6c78` on `task/vietnamese-language-enforcement`.
