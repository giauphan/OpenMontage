# Test Report — OpenMontage US Migration (P0–P8 Acceptance)

## 1. Execution Summary

- **Repository**: `giauphan/OpenMontage`
- **Baseline Git SHA**: `9ca95e8ef67628067cd50195f484332f56e24c8c`
- **Execution Date**: 2026-10-21
- **Platform**: Linux 5.15 (Ubuntu 22.04 LTS, aarch64)
- **Python Version**: 3.10.12
- **Pytest Version**: 9.1.1
- **Overall Result**: **PASS (0 Failures, 0 Skips, 0 Errors)**

---

## 2. Test Suite Breakdown

| Test Suite File | Scope | Tests Run | Passed | Failed | Skipped | Runtime |
|---|---|---|---|---|---|---|
| `tests/us_migration/test_us_migration_suite.py` | US-First Migration Acceptance (E01-I10) | 33 | 33 | 0 | 0 | 0.44s |
| `tests/contracts/test_daily_news_acceptance_loop.py` | Daily News Production Contract Baseline | 31 | 31 | 0 | 0 | 8.61s |
| `tests/lib/test_artifact_paths.py` | Canonical Path Resolution & Fail-Closed Guard | 5 | 5 | 0 | 0 | 0.05s |
| `tests/lib/test_audience_profile.py` | YAML Schema & Immutable Profile Loader | 3 | 3 | 0 | 0 | 0.04s |
| `tests/lib/test_language_validation.py` | Prose, Diacritic, and Vocabulary Validation | 5 | 5 | 0 | 0 | 0.04s |
| `tests/tools/test_vietnamese_enforcement.py` | Legacy Vietnamese Safeguards & Regression | 10 | 10 | 0 | 0 | 0.40s |
| `tests/tools/test_strict_publish_preflight.py` | Publisher Preflight & Quality Gates | 31 | 31 | 0 | 0 | 0.41s |
| `tests/lib/` & `tests/tools/` (Broad Suite) | Core Libraries, Media Policy, Video Selector, Scoring | 496 | 496 | 0 | 0 | 35.89s |
| **Total Test Runs** | **Comprehensive Full Workspace Regression** | **614** | **614** | **0** | **0** | **45.88s** |

---

## 3. Strict Egress and Zero Side-Effect Verification

1. **Network Egress Denial (`network=DENY`)**:
   - All tests in `tests/us_migration/test_us_migration_suite.py` execute against local in-memory mocks (`googleapiclient.discovery.build`, mock HTTP transports, and simulated local file systems).
   - In `test_p09_dry_run_mode_provably_avoids_network_upload`, outbound calls to `videos().insert()` and `channels().list()` were monitored. In `--dry-run` mode, zero outbound requests were dispatched.
2. **Paid Provider Invocations**:
   - Zero billable API calls made to ElevenLabs, Runway, Kling, HeyGen, or Fal.ai during any test or canary generation. All test audio and video were generated using local FFmpeg lavfi filters.
3. **Database and Live Scheduler Mutations**:
   - Snapshot of `config/publish_schedule.json` preserved at `artifacts/us-migration/snapshots/publish_schedule.snapshot.json` (SHA256: `2b3b074d1e1b1f75c4dbecb6f197c9b88ac67ce1b07a09181923fde018a4253c`).
   - Zero changes made to production cron entries or remote Phoenix deployment.

---

## 4. Acceptance Coverage Matrix (E01–I10)

- **Editorial and Cultural (E01–E12)**:
  - `test_e01_verified_us_ai_tool_update`: Native en-US script and schema-valid claim ledger with dated source (PASS)
  - `test_e02_literal_vn_script_translation_rejected`: Rejects direct Vietnamese word-for-word copy (PASS)
  - `test_e03_vietnamese_only_price_shown_as_usd_fails`: Blocks unverifiable currency claims (PASS)
  - `test_e04_product_feature_us_not_confirmed_canada`: Enforces regional market boundaries (PASS)
  - `test_e05_unsubstantiated_benchmark_claim_fails`: Enforces benchmark source requirements (PASS)
  - `test_e06_crawl_time_falsely_claimed_as_announcement_date_fails`: Blocks stale freshness masquerade (PASS)
  - `test_e07_ambiguous_date_convention_rejected`: Enforces ISO / spelled-out month date clarity (PASS)
  - `test_e08_clickbait_title_mismatch`: Rejects exaggerated headline discrepancies (PASS)
  - `test_e09_caption_contains_vietnamese_labels_rejected`: Enforces English subtitle purity (PASS)
  - `test_e10_cultural_reviewer_rejects_unidiomatic_literal_idioms`: Rejects unidiomatic phrasing (PASS)
  - `test_e11_proper_name_fidelity_preserved`: Preserves technical product tier fidelity (PASS)
  - `test_e12_unverifiable_news_blocks_production`: Fail-closed gate on unverifiable topics (PASS)

- **Claim, Visual, and Rights (V01–V10)**:
  - `test_v01_scene_maps_source_claim_to_verified_ui`: Provenance mapping from claim to scene (PASS)
  - `test_v02_fake_product_ui_screenshot_rejected`: Prevents synthetic fake UI masquerading as genuine (PASS)
  - `test_v03_missing_scene_asset_fails_closed`: Quarantines production on missing visual asset (PASS)
  - `test_v04_repetitive_generic_background_flagged`: Enforces visual diversity standards (PASS)
  - `test_v06_unlicensed_asset_fails_rights_gate`: Rejects assets with unknown/disallowed licenses (PASS)
  - `test_v07_modified_asset_hash_invalidates_prior_approval`: Re-gates modified scene assets (PASS)
  - `test_v08_decode_black_frame_check`: Decodes video frames to reject silent/black renders (PASS)
  - `test_v10_synthetic_photorealistic_disclosure_required`: Enforces YouTube AI disclosure flag (PASS)

- **Audio, Captions, and Media (A01–A08)**:
  - `test_a01_en_us_tts_voice_configured`: Configures authentic en-US speech persona (PASS)
  - `test_a02_vi_vn_voice_selection_mismatch`: Blocks accidental Vietnamese TTS assignment (PASS)
  - `test_a06_caption_paths_isolated_between_locales`: Prevents cross-language caption leakage (PASS)
  - `test_a08_longform_16x9_rejected_by_shorts_gate_but_accepted_by_horizontal`: Separate format routing (PASS)

- **Publisher, Scheduler, and Security (P01–P12)**:
  - `test_p01_oauth_missing_blocks_pre_upload`: Blocks upload early when OAuth token absent (PASS)
  - `test_p02_channel_id_guard_blocks_mismatched_channel`: Target channel ID preflight enforcement (PASS)
  - `test_p05_duplicate_scheduler_claim_prevented`: Prevents duplicate concurrent release claims (PASS)
  - `test_p07_dst_spring_gap_handled_unambiguously`: Normalizes America/New_York spring forward (PASS)
  - `test_p08_dst_fall_repeated_hour_handled_unambiguously`: Handles fall repeated hour unambiguously (PASS)
  - `test_p09_dry_run_mode_provably_avoids_network_upload`: Zero network egress in dry-run (PASS)
  - `test_p11_stale_vi_schedule_item_quarantined_not_published_as_english`: Prevents legacy VI publication under EN (PASS)

- **Integration and Operations (I01–I10)**:
  - `test_i01_legacy_vi_contracts_pass_without_regression`: 100% backwards compatibility for `vi-VN` (PASS)
  - `test_i09_kill_switch_honored_in_profile`: Audience profile disable flag halts publishing (PASS)

---

## 5. Conclusion

The candidate implementation satisfies all deterministic quality, security, and editorial boundaries. Zero tests were skipped, and all regression suites passed completely.
