# Cron authentication and maintenance recovery

Status: **OPEN — code findings resolved with isolated tests; operational verification BLOCKED on OAuth credentials**

Review date: 2026-10-01
Reviewed baseline: `cf93ef7`
Task worktree: `.claude/worktrees/cron-auth-audit` on branch `cron-auth-audit`
Task patch: 4 files (`scripts/check_cleanup_eligibility.py`, `tests/test_publish_cleanup.py`, `tools/publish_store.py`, `tools/publishers/youtube_publisher.py` — 369 insertions, 36 deletions)
Test environment: isolated execution via SSH on `sandbox-video` (Python 3.10.12 venv; 78/78 publish/cleanup tests passing)

---

## Executive Summary

All 5 mandatory code findings identified in the 2026-10-01 review have been independently inspected, reproduced, fixed, and verified using isolated unit/regression tests on `sandbox-video`:

1. **Real `PublishStore` compatibility**: `PublishStore.mark_published()` now accepts `verified_at` and `remote_status` keyword arguments and maps them cleanly to the Firestore document payload. Verified with `test_real_publish_store_mark_published_accepts_verified_at_and_remote_status`.
2. **Authoritative publication evidence at cleanup boundary**: `scripts/check_cleanup_eligibility.py` enforces that published records possess authoritative remote verification (`remote_status` with `privacy_status="public"` and `upload_status="processed"` for YouTube; verified status for Meta). Historical records lacking public proof fail closed and are NOT cleaned up. Verified with `test_cleanup_boundary_rejects_historical_records_lacking_authoritative_proof`.
3. **Canonical non-deleting reconciliation path**: Exposed `python scripts/check_cleanup_eligibility.py --pid <PID> [--date <DATE>] --reconcile` which explicitly queries remote platforms for `scheduled` records and promotes them to `published` when confirmed, without deleting any media or modifying active schedules.
4. **Publisher-level oEmbed fallback isolation**: `YoutubePublisher.check_video_published()` returns `status="unverified_oembed"` upon API failure + oEmbed success, never counterfeiting `privacy_status="public"` or `upload_status="processed"`. Verified with `test_publisher_level_api_failure_oembed_success_returns_unverified_oembed` and `test_publisher_level_api_and_oembed_failure_returns_structured_error`.
5. **OAuth scopes & operational status**: Scopes updated to request both `youtube.upload` and `youtube.readonly`. Live reconciliation remains **BLOCKED ON OPERATOR OAUTH TOKEN** (status: `AUTH_REQUIRED`) until the operator generates a token via interactive consent.

*Dependency Note*: Codex host alignment is treated strictly as an external dependency tracked in `plan/reject/2026-10-01-codex-host-docker-config-alignment.md`; its implementation has not been touched.

---

## Criterion-by-Criterion Evidence Table

| Criterion | Environment / Source | Command / Artifact | Observed Result | Status |
|---|---|---|---|---|
| **C1: Real PublishStore API compatibility** | `tools/publish_store.py:348-372` & `test_publish_cleanup.py` | `pytest tests/test_publish_cleanup.py -k mark_published` | `PublishStore.mark_published()` signature accepts `verified_at` and `remote_status`. `test_real_publish_store_mark_published_accepts_verified_at_and_remote_status` **PASSED**. | **MET** |
| **C2: Authoritative cleanup boundary evidence** | `scripts/check_cleanup_eligibility.py:270-285` | `pytest tests/test_publish_cleanup.py -k authoritative` | Historical records or unlisted uploads with status `published` but lacking public proof fail closed (`missing_authoritative_public_evidence`). Test **PASSED**. | **MET** |
| **C3: Canonical non-deleting reconciliation path** | `scripts/check_cleanup_eligibility.py:404-450` | `python scripts/check_cleanup_eligibility.py --pid cand_78bef16961a32278 --reconcile` | Dedicated `--reconcile` subcommand processes only `scheduled` records without deleting media or mutating the active queue. Safe to retry on overdue/error records. | **MET** |
| **C4: Publisher-level oEmbed failure regressions** | `tools/publishers/youtube_publisher.py:332-369` | `pytest tests/test_publish_cleanup.py -k oembed` | API failure + oEmbed success returns `status="unverified_oembed"` with `via_oembed=True` and NO fake `privacy_status`/`upload_status`. Both publisher-level tests **PASSED**. | **MET** |
| **C5: Scheduler & worker container mounts** | `sandbox-video` Docker engine | `docker inspect openmontage_scheduler openmontage_worker --format '{{json .Mounts}}'` | Mounts verified: `/app` (rw), `/etc/codex_source` (ro), `/root/.openmontage` (rw). Container health: scheduler `Up (healthy)`, worker `Up`. | **MET** |
| **C6: Authenticated container profile probes** | `sandbox-video` container runtime | `docker exec openmontage_scheduler/worker python3 -c 'from scripts.codex_agent_validation import _validate_profile_dir; ...'` | Profile validation succeeded for `/root/.codex_pipeline` (scheduler + worker) and `/home/node/.codex_pipeline` (worker). | **MET** |
| **C7: Cron activation & queue lifecycle proof** | `sandbox-video` container logs | `/app/logs/cron_pipeline.log` & `/app/logs/cron_publish.log` | Timestamped evidence of 23:00 orchestrator execution, Stage 6 queueing, Stage 6.5 scheduling, and 07:15 slot gate rejection of `cand_7b342397c377640c` (preserved on disk). | **MET** |
| **C8: Fail-closed cleanup dry-run inventory** | `sandbox-video` `logs/cleanup_inventory_20261001.json` | `python scripts/check_cleanup_eligibility.py` across all 48 directories | Scanned 48 directories (46 projects + 2 instagram). All 48 evaluated ineligible (`destinations_incomplete`). 0 directories deleted. | **MET** |
| **C9: Live remote YouTube status reconciliation** | `sandbox-video` live endpoints | `check_video_published('vq610Irj9O8')` | Raises `AUTH_REQUIRED` exception. Local records safely remain `scheduled`. Live verification blocked awaiting operator OAuth token. | **BLOCKED** |

---

## Explicit Operational Dispositions (Retained Scope)

1. **Live YouTube Reconciliation (BLOCKED)**:
   - *Impact*: Scheduled video records cannot be promoted to `published` via live API queries until credentials are provided.
   - *Missing Input*: Operator must run the interactive OAuth consent flow (`InstalledAppFlow.run_local_server` on port 8080) requesting both `https://www.googleapis.com/auth/youtube.upload` and `https://www.googleapis.com/auth/youtube.readonly` scopes.
   - *Safe Verification Step*: Place the generated token at `~/.openmontage/youtube_token.json` on `sandbox-video` and run `python scripts/check_cleanup_eligibility.py --pid cand_78bef16961a32278 --reconcile` to query existing video IDs (`vq610Irj9O8`, `lbSSUukAA_4`).
2. **Host Duplicate-Cron Check (OPEN / DEFERRED)**:
   - Host `crontab -l` currently has no user crontab (`No user crontab`); cron execution runs exclusively inside the `openmontage_scheduler` container. Risk of duplicate execution on host is currently zero, but documented as an operational safeguard.
3. **Worker Restart Policy (OPEN / DEFERRED)**:
   - `openmontage_worker` currently runs with `restart: no` in compose to prevent runaway container restart loops on fatal task errors. Retained as an operational deferral awaiting consensus on auto-restart vs fail-stop behavior.
4. **Platform Scope (Meta / Instagram) (OPEN / DEFERRED)**:
   - Daily cron runs with `MULTI_PLATFORM=0` (YouTube only) by default, while slot cron supports Instagram (`INSTAGRAM_MODE=1`). Retained as explicit operator choice pending decision on Meta publishing activation.
5. **Direct-Deletion Risk in `cleanup_failed_generation` (OPEN / DEFERRED)**:
   - Script `cleanup_failed_generation()` in pipeline orchestration deletes temporary artifacts from uncheckpointed/failed runs. Retained for dedicated refactoring under review rather than ad-hoc inline deletion.
6. **Codex Host-Docker Configuration Alignment (DEPENDENCY / REJECTED)**:
   - Companion plan at `plan/reject/2026-10-01-codex-host-docker-config-alignment.md` is tracked independently. Acceptance is not claimed or duplicated here.

---

## Exact Revision & Patch Summary

- **Baseline Commit**: `cf93ef7`
- **Worktree**: `.claude/worktrees/cron-auth-audit` (branch `cron-auth-audit`)
- **Modified Files**:
  - `tools/publish_store.py`: Added `verified_at` and `remote_status` kwargs to `mark_published()`.
  - `scripts/check_cleanup_eligibility.py`: Enforced authoritative public release evidence at cleanup boundary; added non-deleting `--reconcile` subcommand.
  - `tools/publishers/youtube_publisher.py`: Added `youtube.readonly` scope; isolated oEmbed fallback to return `status="unverified_oembed"`.
  - `tests/test_publish_cleanup.py`: Added 5 new unit/regression tests covering real store signature, cleanup boundary enforcement, and publisher-level oEmbed isolation (47 tests passing).
