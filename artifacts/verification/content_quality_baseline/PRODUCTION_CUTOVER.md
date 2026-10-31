# OpenMontage Production Cutover, Rollout & Rollback Runbook

**Remediation Branch:** `feat/content-quality-remediation`  
**Base Release:** `c2364a6f`  
**Target Release:** Remediated Content Quality Architecture (Phases 1–7)  
**Governance Constraint:** Owner-locked niche `Practical AI Agent Engineering`  

---

## 1. Feature Flags & Production Configuration

The remediated pipeline relies on deterministic environment toggles configured in `config/environments/production.env`:

| Flag | Default | Recommended Cutover | Description |
|---|---|---|---|
| `FIXED_NICHE_MODE` | `1` | `1` | Strictly enforces `FixedNicheScopeGate` across all pipelines. Rejects off-niche topics immediately. |
| `STRICT_VISUAL_QA` | `1` | `1` | Fails closed on missing DOM proof assets (`VISUAL_NOT_RENDERED`) and claim/visual mismatches. |
| `PUBLISH_TZ` | `America/New_York` | `America/New_York` | US Eastern timezone for all English publication slots, handling EDT/EST transitions safely. |
| `MAX_DAILY_PUBLISH_COUNT` | `3` | `3` | Maximum 3 uploads per US-local calendar day with >= 2 hours spacing between slots. |
| `STRICT_AUDIO_PACING` | `1` | `1` | Enforces natural speech rate (max ±10%) and bounds ffmpeg `atempo` between 0.90x and 1.10x. |
| `PUBLISH_LIVE` | `0` | `0` (Canary) -> `1` (Live) | Safety gate preventing unauthorized public publishing until human inspector signs off. |

---

## 2. Step-by-Step Staging & Cutover Procedure

### Step 1: Local Pre-Flight Check & Git Tree Cleanliness
```bash
# Verify all remediation tests pass locally
pytest tests/contracts/test_remediation_phase*.py -v
# Verify syntax of all shell runners
bash -n scripts/run_daily_news_pipeline.sh scripts/run_strict_docker_publish.sh scripts/retry_daily_pipeline.sh
```

### Step 2: Safe Remote Synchronization to `sandbox-video`
*In accordance with project rules, remote execution is delivery and validation only; no remote editing is permitted.*
```bash
# Push validated branch to remote repository
git push origin feat/content-quality-remediation

# On sandbox-video (via SSH), fast-forward the test checkout
git fetch origin feat/content-quality-remediation
git checkout feat/content-quality-remediation
git verify-commit HEAD
```

### Step 3: Offline Staging Canary Execution
Run the daily news pipeline in offline / test mode on `sandbox-video`:
```bash
PUBLISH_LIVE=0 \
FIXED_NICHE_MODE=1 \
STRICT_VISUAL_QA=1 \
PUBLISH_TZ="America/New_York" \
bash scripts/run_daily_news_pipeline.sh
```

### Step 4: Verification Checklist (Human Gate)
Before switching `PUBLISH_LIVE=1`, the designated editorial lead must verify:
- [ ] Topic selection strictly matches `Practical AI Agent Engineering` (no consumer hardware, crypto, or hype listicles).
- [ ] All claims trace to authentic capture files in `artifacts/news_source_capture/` with genuine dates.
- [ ] Proof beat screenshots or SVG diagrams are visibly rendered in MP4 frames without blank tail or sync drift.
- [ ] Audio narration sounds natural (no metallic distortion, no chips-in-mouth +30% speedup).
- [ ] Subtitles and captions are contained within safe 9:16 margins without overlapping TikTok/Shorts UI elements.
- [ ] Cryptographic approval record in `approval.json` verifies successfully against project hashes.

### Step 5: Activate Production Scheduling
Once approved, update `PUBLISH_LIVE=1` in the production runner crontab or systemd service unit.

---

## 3. Rollback & Emergency Containment Procedure

If a defect or regression is detected in production:

### Emergency Stop (P0 Containment)
Immediately stop active scheduler cron jobs to prevent pending uploads:
```bash
# Disable daily publisher immediately
touch data/.no_eligible_topic_marker
# Cancel pending scheduled YouTube uploads
python3 scripts/schedule_youtube_today.py --cancel-pending
```

### Safe Downgrade
```bash
# Revert to stable baseline commit
git checkout c2364a6f3104c8d3c0dd181eb705650291fcae96
# Verify active queue items are untouched in outputs/projects/
```

### Quarantine Policy
Any failed build or rejected proof is quarantined in `outputs/quarantine/` with its full audit trace. The pipeline will never attempt to auto-publish quarantined artifacts.
