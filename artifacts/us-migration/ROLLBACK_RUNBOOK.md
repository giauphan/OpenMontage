# Rollback & Incident Response Runbook — OpenMontage US Migration

This runbook establishes deterministic, fail-safe procedures to halt publishing, quarantine impacted jobs, and revert configuration or code should any defect or unexpected behavior occur during testing or future authorized pilots.

---

## 1. Immutable Pre-Release Snapshot Inventory

Before executing any external operation, the following immutable references are preserved:
- **Baseline Git SHA**: `9ca95e8ef67628067cd50195f484332f56e24c8c`
- **Publish Schedule Snapshot**:
  - Path: `artifacts/us-migration/snapshots/publish_schedule.snapshot.json`
  - SHA256: `2b3b074d1e1b1f75c4dbecb6f197c9b88ac67ce1b07a09181923fde018a4253c`
- **Audience Profile Backup**:
  - Legacy Vietnamese: `config/audience_profiles/vi-VN.yaml`
  - US Pilot Profile: `config/audience_profiles/en-US.yaml`

---

## 2. Immediate Incident Triggers (Fail-Closed Conditions)

A production hold and incident review must be triggered **immediately** if any of the following occur:
1. **Channel Identity Mismatch**: Any attempt or simulated attempt to upload to an unapproved Google account or YouTube Channel ID.
2. **Vietnamese Language Leak**: Spoken Vietnamese phrases, diacritics, or Vietnamese tags detected in an `en-US` publish payload.
3. **Factual Integrity Breach**: Publication of an unverified factual claim, unsubstantiated benchmark, or distorted source quote.
4. **Media Quality Defect**: Rendered MP4 exhibiting silence (< -50 dB), black frame sequences (> 30%), or caption timing drift.
5. **Scheduler Collision / Duplicate**: Concurrent dispatchers claiming the same slot, or duplicate video uploads.
6. **Paid API Overrun / Leak**: Accidental outbound billable requests to HeyGen, ElevenLabs, Runway, or Fal.ai during dry-run or rehearsal.

---

## 3. Step-by-Step Rollback Procedure

### Step 1: Activate Global Publishing Kill Switch
Disable the `en-US` audience profile immediately by toggling `enabled: false`:
```bash
# Set en-US profile to disabled (fails closed in all publishers and schedulers)
sed -i 's/enabled: true/enabled: false/' config/audience_profiles/en-US.yaml
```
Verify that `AudienceProfile.is_active("en-US")` returns `False`.

### Step 2: Stop All In-Flight Schedulers & Background Tasks
Terminate any background publisher or cron dispatch processes:
```bash
# Search and kill active schedule runners
pkill -f "scripts/schedule_today_native.py" || true
pkill -f "scripts/run_daily_news_pipeline.sh" || true
```

### Step 3: Reconcile External State (YouTube Studio)
1. Do **NOT** blindly delete uploaded videos.
2. If an erroneous video was uploaded under the US pilot:
   - Query YouTube Data API via authenticated script to retrieve the video ID.
   - Set visibility to `private`:
     ```python
     youtube.videos().update(
         part="status",
         body={"id": video_id, "status": {"privacyStatus": "private"}}
     ).execute()
     ```
3. Never modify or delete historical Vietnamese Shorts.

### Step 4: Restore Original Publication Schedule
Restore the verified snapshot of the publication schedule:
```bash
cp artifacts/us-migration/snapshots/publish_schedule.snapshot.json config/publish_schedule.json
# Verify hash
sha256sum config/publish_schedule.json
# Expected: 2b3b074d1e1b1f75c4dbecb6f197c9b88ac67ce1b07a09181923fde018a4253c
```

### Step 5: Code Reversion (If Necessary)
If software defects require reverting to the baseline release:
```bash
git checkout 9ca95e8ef67628067cd50195f484332f56e24c8c -- lib/ scripts/ tools/
```

### Step 6: Post-Rollback Verification
Run the baseline acceptance test suite to confirm full system integrity:
```bash
pytest tests/contracts/test_daily_news_acceptance_loop.py -v
pytest tests/tools/test_vietnamese_enforcement.py -v
```
Confirm 100% test pass before lifting the hold.
