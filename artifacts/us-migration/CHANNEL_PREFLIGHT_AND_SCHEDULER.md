# Channel Preflight & Scheduler Evidence — OpenMontage US Migration

This document details the OAuth channel identity verification guard, synthetic media compliance disclosure, and timezone/DST-safe scheduling engine designed for the US-first publication pipeline.

---

## 1. Channel Identity Preflight Guard (Anti-Hijack & Safe Target Check)

### The Threat Model
A host running automated publishing pipelines may hold an OAuth token that belongs to:
1. The developer's personal Google account,
2. An older/unrelated YouTube channel, or
3. A test/staging channel.

Uploading without preflighting the authenticated channel ID risks publishing content to the wrong brand or leaking private canaries publicly. Relying on host geolocation or VPS IP does not guarantee target channel alignment.

### Implementation Architecture
In `tools/publishers/youtube_publisher.py`, an identity preflight gate precedes any upload or metadata mutation:

```python
# Query authenticated channel
request = youtube.channels().list(mine=True, part="id")
response = request.execute()
items = response.get("items", [])
if not items:
    raise RuntimeError("OAuth token does not own or manage any YouTube channel")
authenticated_channel_id = items[0]["id"]

# Compare against expected channel ID
if expected_channel_id and authenticated_channel_id != expected_channel_id:
    raise RuntimeError(
        f"Channel identity mismatch: authenticated as '{authenticated_channel_id}', "
        f"but expected target channel is '{expected_channel_id}'. Upload aborted."
    )
```

### Deterministic Test Verification
- **Test**: `tests/us_migration/test_us_migration_suite.py::TestPublisherSchedulerSecurityP01_P12::test_p02_channel_id_guard_blocks_mismatched_channel`
- **Result**: `PASS`. When `expected_channel_id="UC_CORRECT_CHANNEL_ID"` and the mock OAuth client returns `"UC_WRONG_STOLEN_ACCOUNT"`, the publisher terminates with `RuntimeError` before initiating `videos().insert()`.

---

## 2. OAuth Scopes & Synthetic Media Disclosure

### Required Minimal OAuth Scopes
For the future Phase P9 pilot, only the following scopes are authorized:
- `https://www.googleapis.com/auth/youtube.upload` (Upload videos and manage video metadata)
- `https://www.googleapis.com/auth/youtube.readonly` (Verify channel identity and check playlist/status)

The broader full-control scope (`https://www.googleapis.com/auth/youtube`) is explicitly disallowed to adhere to the principle of least privilege.

### Synthetic Media Disclosure (YouTube 2024 Policy Compliance)
YouTube requires creators to disclose realistic altered or synthetic content (e.g., AI-generated realistic voices, photorealistic characters, or simulated real-world events).
In `tools/publishers/youtube_publisher.py`, the metadata payload dynamically includes the disclosure flag:

```python
body["status"]["containsSyntheticMedia"] = bool(
    metadata.get("containsSyntheticMedia", False)
)
```
Verified by `test_v10_synthetic_photorealistic_disclosure_required` (PASS).

---

## 3. America/New_York Publishing Scheduler & DST Safety

### System Host vs. Audience Timezone
- The physical host server is located in Phoenix, Arizona (`America/Phoenix`, UTC-7 year-round without daylight saving time).
- The audience publication schedule operates on **Eastern Time (`America/New_York`)**, which transitions between EST (UTC-5) and EDT (UTC-4).
- The scheduler engine never relies on local system time or naive datetime math.

### DST-Safe Datetime Construction
`scripts/schedule_today_native.py` implements `make_publish_datetime`:
1. **Spring Forward Gap** (e.g., 2:30 AM does not exist on transition Sunday):
   Detected via `ZoneInfo`. The time is normalized cleanly to the first valid wall-clock time (3:00 AM) without crashing.
   - *Test Proof*: `test_p07_dst_spring_gap_handled_unambiguously` (PASS).
2. **Fall Back Repeated Hour** (e.g., 1:30 AM occurs twice on transition Sunday):
   Handled using `fold=0` (the standard first occurrence in wall-clock time), preventing duplicate release slots or double-publishing.
   - *Test Proof*: `test_p08_dst_fall_repeated_hour_handled_unambiguously` (PASS).

---

## 4. Concurrent Claim Guard & Shadow Simulation (Dry-Run)

### Concurrency and Duplicate Slot Prevention
- Multiple cron instances or supervisor processes cannot claim the same project, rendition, or publication slot.
- `publish_store` uses atomic file creation / claim locking.
- *Test Proof*: `test_p05_duplicate_scheduler_claim_prevented` (PASS).

### Dry-Run Shadow Mode
- The `--dry-run` flag enables full end-to-end simulation of the scheduling and publishing pipeline without calling YouTube APIs or external networks.
- *Test Proof*: `test_p09_dry_run_mode_provably_avoids_network_upload` (PASS: zero outbound HTTP calls, zero file uploads, zero state corruption).
