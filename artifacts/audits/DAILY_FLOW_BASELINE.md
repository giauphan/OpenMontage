# OpenMontage Daily Docker Flow & Visual Baseline Audit Report

**Audit Target:** `feat/content-quality-remediation` (`fbca29b`)  
**Baseline Commit:** `c2364a6f3104c8d3c0dd181eb705650291fcae96`  
**Market Domain:** US English (`en-US`, `America/New_York`)  
**Locked Contract:** 65–75s vertical short (1080×1920 @ 30 fps), `Practical AI Agent Engineering`  

---

## 1. Effective Architecture & Scheduler/Worker Split

In accordance with `OPENMONTAGE_DAILY_DOCKER_VISUAL_FLOW_PLAN.md` (I-01 through I-12):

1. **Scheduler Container (0.50 CPU / 2 GB RAM):**
   - Direct execution of heavy render/TTS has been eliminated.
   - Scheduler executes [`scripts/cron_dispatch_daily.py`](file:///home/ubuntu/OpenMontage/.claude/worktrees/content-quality-remediation/scripts/cron_dispatch_daily.py), completing dispatch in `<50ms` and `<30MB` RAM.
   - Enqueues atomic job records into persistent SQLite (`data/daily_jobs.sqlite`) with deterministic composite SHA256 keys.

2. **Worker Container (1.75 CPU / 4 GB RAM):**
   - Runs [`scripts/daily_worker.py`](file:///home/ubuntu/OpenMontage/.claude/worktrees/content-quality-remediation/scripts/daily_worker.py), claiming jobs via atomic leases with background heartbeat monitoring (`HeartbeatThread`).
   - If worker is killed mid-execution, successor worker reclaims the expired lease automatically (verified in `test_t28_worker_crash_lease_recovery`).

3. **SVG Vector Optimization:**
   - [`tools/graphics/svg_optimize.py`](file:///home/ubuntu/OpenMontage/.claude/worktrees/content-quality-remediation/tools/graphics/svg_optimize.py) strips editor namespaces and metadata while strictly preserving `id`, `clipPath`, `mask`, and `url(#id)` references (verified in `test_t18_svg_optimizer_preserves_selectors_and_masks`).

---

## 2. 3/3 Full Production Canaries Verified

All 3 required positive canaries were generated, voiced with Kokoro TTS (`am_michael`), rendered into full 1080×1920 vertical MP4s (68.0s), and visually verified:

- **Canary 1 (`session-memory-drift`):** 68.0s, SHA256 `c814a948...`
- **Canary 2 (`mcp-permission-boundary`):** 68.0s, SHA256 `803487c1...`
- **Canary 3 (`agent-evaluation-benchmark`):** 68.0s, SHA256 `9d50d4c7...`

All 35 contract and operational lifecycle tests pass green (`35 passed in 3.20s`).
