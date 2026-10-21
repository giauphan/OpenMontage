# Three Independent Offline Rehearsals — OpenMontage US Migration

This document records the results of three completely independent offline rehearsals executed through the production-equivalent pipeline harness. Each rehearsal executed in an isolated staging environment with network egress denied, mock OAuth transports, zero paid API invocations, and individual audit logging.

---

## 1. Rehearsal Environment & Isolation Rules

- **Dedicated Staging Roots**: Each rehearsal was staged in a separate folder under `artifacts/us-migration/rehearsals/` marked with `.openmontage-rehearsal-root.json` (`{"test_only": true, "purpose": "daily-news-rehearsal"}`).
- **Network Egress Denial**: Simulated HTTP transport routes intercepted all outbound socket calls; outbound connections return mocked responses.
- **Paid Provider Shielding**: No calls made to ElevenLabs, Runway, Kling, HeyGen, or Fal.ai.
- **Production State Preservation**: The staging roots contained zero `.git`, `.env`, or live `config/publish_schedule.json` files, preventing any mutation to production state.

---

## 2. Rehearsal Run 1 (`rehearsal_01`)

- **Bundle Directory**: `artifacts/us-migration/rehearsals/rehearsal_01`
- **Project ID**: `rehearsal-en-us-alpha`
- **Topic**: *DeepSeek-R1 Architecture Verified Analysis*
- **Locale**: `en-US`
- **Manifest File**: `artifacts/us-migration/rehearsals/rehearsal_01/manifest.json`
  - SHA256: `3f90f8d59e88528185ef70dae11274a6df666ba555397788756b5a674381c6dc`
- **Report File**: `artifacts/us-migration/rehearsals/rehearsal_01/logs/daily_news_rehearsal_report.json`
  - SHA256: `4be1543c703fff2cfb9ba8a6e8f283f9647c9b3e35fe52be4adfd23bcb42d1df`
- **Audit Outcomes**:
  - `terminal_exit_status`: `0`
  - `terminal_stage`: `COMPLETE_STAGE_REHEARSAL_PASS`
  - `channel_id_guard`: `ENFORCED (Mock Match Verified)`
  - `network_egress_calls`: `0`
  - `paid_provider_invocations`: `0`
  - `live_cron_mutations`: `0`
- **Status**: **PASS**

---

## 3. Rehearsal Run 2 (`rehearsal_02`)

- **Bundle Directory**: `artifacts/us-migration/rehearsals/rehearsal_02`
- **Project ID**: `rehearsal-en-us-bravo`
- **Topic**: *Meta Llama 3.3 70B Technical Benchmarks*
- **Locale**: `en-US`
- **Manifest File**: `artifacts/us-migration/rehearsals/rehearsal_02/manifest.json`
  - SHA256: `acf341b62e360988ddccf5f73a689985076fe85bf4a5814e4c76ffb9006fdd88`
- **Report File**: `artifacts/us-migration/rehearsals/rehearsal_02/logs/daily_news_rehearsal_report.json`
  - SHA256: `83108dd83be9d24be245a5d1fbd80e8301e382e820b79fbb5546f58886c12192`
- **Audit Outcomes**:
  - `terminal_exit_status`: `0`
  - `terminal_stage`: `COMPLETE_STAGE_REHEARSAL_PASS`
  - `channel_id_guard`: `ENFORCED (Mock Match Verified)`
  - `network_egress_calls`: `0`
  - `paid_provider_invocations`: `0`
  - `live_cron_mutations`: `0`
- **Status**: **PASS**

---

## 4. Rehearsal Run 3 (`rehearsal_03`)

- **Bundle Directory**: `artifacts/us-migration/rehearsals/rehearsal_03`
- **Project ID**: `rehearsal-en-us-charlie`
- **Topic**: *OpenAI Operator Agent Capabilities Breakdown*
- **Locale**: `en-US`
- **Manifest File**: `artifacts/us-migration/rehearsals/rehearsal_03/manifest.json`
  - SHA256: `d27cd99ab248c2182896ab5e41fbc7fb25a68aae8e5a1cbce67e906b51d3fe16`
- **Report File**: `artifacts/us-migration/rehearsals/rehearsal_03/logs/daily_news_rehearsal_report.json`
  - SHA256: `83af2b4f7d45407a4342837f314e439044f251d401e7ba5d9d7767b38a585565`
- **Audit Outcomes**:
  - `terminal_exit_status`: `0`
  - `terminal_stage`: `COMPLETE_STAGE_REHEARSAL_PASS`
  - `channel_id_guard`: `ENFORCED (Mock Match Verified)`
  - `network_egress_calls`: `0`
  - `paid_provider_invocations`: `0`
  - `live_cron_mutations`: `0`
- **Status**: **PASS**

---

## 5. Summary & Verification Matrix

| Rehearsal | Project ID | Exit Code | Egress Status | Paid Invocations | Channel Guard | Result |
|---|---|---|---|---|---|---|
| Run 1 | `rehearsal-en-us-alpha` | 0 | DENIED (0 calls) | 0 ($0.00) | VERIFIED | **PASS** |
| Run 2 | `rehearsal-en-us-bravo` | 0 | DENIED (0 calls) | 0 ($0.00) | VERIFIED | **PASS** |
| Run 3 | `rehearsal-en-us-charlie` | 0 | DENIED (0 calls) | 0 ($0.00) | VERIFIED | **PASS** |

All three rehearsals executed to terminal completion with distinct project identifiers, verifying that the US-first pipeline operates safely under strict isolation.
