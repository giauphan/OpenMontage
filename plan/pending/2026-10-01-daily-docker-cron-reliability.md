# Reliability Audit Report & Hardening Verification: Daily Docker Cron Pipeline

Status: **PREPARED — AWAITING NEXT-RUN VERIFICATION**
Date: 2026-10-01
Priority: **P0 before next daily trigger (23:00 UTC / 06:00 ICT)**

---

## Executive Summary & Readiness State

All P0 and P1 audit, hardening, concurrency, safe-cleanup, timeout, disk threshold, feed-freshness, and heartbeat monitoring tasks have been implemented and verified via automated test suites (114 passing tests).

The pipeline is **prepared and awaiting next-run verification** for the scheduled cycle at **23:00 UTC (06:00 ICT)**.

---

## 1. Deployed Inventory & Next Trigger Baseline

- **Host Environment**: `sandbox-video` (Linux 6.8.0-1054-oracle)
- **Container Architecture**: Dual containers (`openmontage_scheduler` & `openmontage_worker`) running image `openmontage:latest` with `restart: unless-stopped`.
- **Scheduler Crontab**: Installed at `deploy/openmontage.cron` (`0 23 * * *` daily orchestrator; `15 2,7,14 * * *` slot publishers).
- **Timezone Alignment**:
  - Scheduler system clock: **UTC**
  - Publication timezone (`PUBLISH_TZ`): **Asia/Ho_Chi_Minh (ICT / UTC+7)**
- **Next Trigger Schedule**:
  - Daily Orchestrator Generation: **2026-10-01 23:00 UTC / 2026-10-02 06:00 ICT**
  - Slot 1 (Instagram / Youtube Shorts): **2026-10-02 02:15 UTC / 09:15 ICT**
  - Slot 2 (Instagram / Youtube Shorts): **2026-10-02 07:15 UTC / 14:15 ICT**
  - Slot 3 (Instagram / Youtube Shorts): **2026-10-02 14:15 UTC / 21:15 ICT**

---

## 2. Hardening & Protection Fixes Implemented

### A. Non-Destructive Safe Cleanup & Quarantine
- Replaced unconditioned `rm -rf` on temporary directories with age-gated removal (`find -mmin +120`).
- Replaced destructive `rm -rf` of failed candidate directories in `cleanup_failed_generation` with safe quarantine relocation to `projects/_failed_generation_recovered/`.

### B. Preflight Disk Space Thresholding
- Implemented `MIN_DISK_MB=2000` (project root) and `MIN_TMP_DISK_MB=2000` (`/tmp` root) checks in Stage 0 preflight.
- Pipeline fails closed and writes a `failed` heartbeat state if free space is below safety limits, preventing out-of-disk crashes during generation.

### C. News Feed Freshness Gate
- Added `MAX_STALE_FEED_AGE_HOURS=48` enforcement on fallback `data/newsnow_feed.json`.
- Fail-closed block when fallback feed is older than 48 hours to avoid generating outdated news content.

### D. Schedule Concurrency & Non-Blocking Locking
- Added bounded file locking (`flock -x -w 300`) on `config/publish_schedule.json.lock` around Stage 6 schedule queueing to eliminate race conditions between daily generation and slot publishers.

### E. Publisher Process Timeout Protection
- Added `PUBLISHER_TIMEOUT_SECONDS=3600` (1 hour) enforcement in `scripts/publish_active_projects.py` for child process execution (`publish_manual_video.py`), ensuring hung uploads are terminated while preserving remote publication claims for reconciliation.

### F. Docker & Compose Reliability
- Added `cron` and `jq` directly to the `Dockerfile` build context.
- Configured `restart: unless-stopped` for both `worker` and `scheduler` containers in `docker-compose.yml`.
- Added container healthcheck targeting `cron` in `docker-compose.yml`.

### G. Missed-Run & Failure Monitoring
- Created `scripts/check_missed_runs.py` to inspect `logs/heartbeat/*.json` against configurable age limits and emit structured alerts to `logs/missed_run_alerts.log`.
- Heartbeat state tracking added for daily orchestrator (`daily_orchestrator.json`) and individual publishing slots (`slot_0915.json`, `slot_1415.json`, `slot_2115.json`).

---

## 3. Test Verification Matrix

All 114 test cases in the test suite pass cleanly on `sandbox-video`:

| Test Suite | Passing Tests | Focus Area |
| :--- | :--- | :--- |
| `tests/test_daily_cron_reliability_hardening.py` | 3 | Heartbeat monitoring, stale run detection, failed state detection |
| `tests/test_strict_generation_failure_cleanup.py` | 2 | Directory quarantine relocation & preflight disk space thresholding |
| `tests/scripts/test_strict_cli_preflight.py` | 3 | Stage 0 CLI dependency checks & Codex preflight isolation |
| `tests/test_strict_schedule_only.py` | 3 | Queueing, slot buffer logic, today-versus-tomorrow recovery |
| `tests/test_publish_active_projects.py` | 7 | Active project slot publishing, timeout handling, claim preservation |
| `tests/test_publish_manual_video.py` | 26 | Platform publisher execution, auth checking, claim logging |
| `tests/test_publish_cleanup.py` | 47 | Active project protection & cleanup eligibility |
| Other strict suites | 23 | Pipeline schedule alignment, auth isolation, completion reporting |
| **Total** | **114** | **100% PASS** |

---

## 4. Next-Run Observation Runbook

1. **At 23:00 UTC / 06:00 ICT**: Inspect heartbeat output in `logs/heartbeat/daily_orchestrator.json`.
2. **Verify Stage Progression**: Monitor `logs/strict_docker_publish/run_latest.state`.
3. **Verify Missed Run Detector**: Run `python3 scripts/check_missed_runs.py` to confirm zero alerts.
4. **Observe Slot Executions**: Verify slot heartbeats at 09:15, 14:15, and 21:15 ICT.
