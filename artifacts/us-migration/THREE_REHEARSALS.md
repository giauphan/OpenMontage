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
- **Project IDs**: `["rehearsal-en-us-alpha-1", "rehearsal-en-us-alpha-2", "rehearsal-en-us-alpha-3"]` (3 disjoint project executions)
- **Topic**: *DeepSeek-R1 Architecture Verified Analysis*
- **Locale**: `en-US`
- **Manifest File**: `artifacts/us-migration/rehearsals/rehearsal_01/manifest.json`
  - SHA256: `1e98d651dedc997dd118e206fe69b00c1cf8664b9bc812f4bc470b4a7282277c`
- **Report File**: `artifacts/us-migration/rehearsals/rehearsal_01/logs/daily_news_rehearsal_report.json`
  - SHA256: `d7de6f7d54abcd734d22d1e2338dec991d09eb8eabe27d3c73619af1aa67748c`
- **Audit Outcomes**:
  - `terminal_exit_status`: `0`
  - `terminal_stage`: `completed`
  - `n5_complete`: `false` (holding live YouTube upload until explicit P9 authorization)
  - `stage_evidence_paths`: 8 verified paths on disk
  - `channel_id_guard`: `ENFORCED (Mock Match Verified)`
  - `network_egress_calls`: `0`
  - `paid_provider_invocations`: `0`
  - `live_cron_mutations`: `0`
- **Status**: **PASS**

---

## 3. Rehearsal Run 2 (`rehearsal_02`)

- **Bundle Directory**: `artifacts/us-migration/rehearsals/rehearsal_02`
- **Project IDs**: `["rehearsal-en-us-bravo-1", "rehearsal-en-us-bravo-2", "rehearsal-en-us-bravo-3"]` (3 disjoint project executions)
- **Topic**: *Meta Llama 3.3 70B Technical Benchmarks*
- **Locale**: `en-US`
- **Manifest File**: `artifacts/us-migration/rehearsals/rehearsal_02/manifest.json`
  - SHA256: `a7642135047f391fe3f85fae845940004c15ef8a315942e35d4eb0e65b29fc21`
- **Report File**: `artifacts/us-migration/rehearsals/rehearsal_02/logs/daily_news_rehearsal_report.json`
  - SHA256: `03f518b640fac2b5a68c92cd061baf65842aeed417abd7a7ce97a9ca8a7c7771`
- **Audit Outcomes**:
  - `terminal_exit_status`: `0`
  - `terminal_stage`: `completed`
  - `n5_complete`: `false` (holding live YouTube upload until explicit P9 authorization)
  - `stage_evidence_paths`: 8 verified paths on disk
  - `channel_id_guard`: `ENFORCED (Mock Match Verified)`
  - `network_egress_calls`: `0`
  - `paid_provider_invocations`: `0`
  - `live_cron_mutations`: `0`
- **Status**: **PASS**

---

## 4. Rehearsal Run 3 (`rehearsal_03`)

- **Bundle Directory**: `artifacts/us-migration/rehearsals/rehearsal_03`
- **Project IDs**: `["rehearsal-en-us-charlie-1", "rehearsal-en-us-charlie-2", "rehearsal-en-us-charlie-3"]` (3 disjoint project executions)
- **Topic**: *OpenAI Operator Agent Capabilities Breakdown*
- **Locale**: `en-US`
- **Manifest File**: `artifacts/us-migration/rehearsals/rehearsal_03/manifest.json`
  - SHA256: `f3433de710342ad38cc7a1cd00c90f01cc7002f1f9379ac2f20bf1207057ba80`
- **Report File**: `artifacts/us-migration/rehearsals/rehearsal_03/logs/daily_news_rehearsal_report.json`
  - SHA256: `807dd662f3fcc39b0310c1eacf6cd4e7432959f8760929899b8f68b9fe21ad6f`
- **Audit Outcomes**:
  - `terminal_exit_status`: `0`
  - `terminal_stage`: `completed`
  - `n5_complete`: `false` (holding live YouTube upload until explicit P9 authorization)
  - `stage_evidence_paths`: 8 verified paths on disk
  - `channel_id_guard`: `ENFORCED (Mock Match Verified)`
  - `network_egress_calls`: `0`
  - `paid_provider_invocations`: `0`
  - `live_cron_mutations`: `0`
- **Status**: **PASS**

---

## 5. Summary & Verification Matrix

| Rehearsal | Project IDs (Disjoint) | Exit Code | Terminal Stage | N5 Complete | Evidence Paths | Egress Status | Result |
|---|---|---|---|---|---|---|---|
| Run 1 | 3 projects (`rehearsal-en-us-alpha-1..3`) | 0 | `completed` | `false` (Safe) | 8 paths on disk | DENIED (0) | **PASS** |
| Run 2 | 3 projects (`rehearsal-en-us-bravo-1..3`) | 0 | `completed` | `false` (Safe) | 8 paths on disk | DENIED (0) | **PASS** |
| Run 3 | 3 projects (`rehearsal-en-us-charlie-1..3`) | 0 | `completed` | `false` (Safe) | 8 paths on disk | DENIED (0) | **PASS** |

All three rehearsals conform strictly to `verify_rehearsals` in `lib/daily_news_acceptance_loop.py`, executing across 9 distinct project identifiers with 24 verified stage evidence paths, validating that the US-first pipeline operates safely under strict isolation.
