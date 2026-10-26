# OpenMontage — Locked-Niche E2E Verification & Release Audit

**Target Commit SHA**: `2b8b8b09ae31c63e13ee370530310ae83f4b973f`  
**Date**: 2026-10-26  
**Auditor**: Independent Principal Systems Architect & Video Pipeline QA Lead  
**Channel Locked Niche**: Practical AI Agent Engineering — How Coding Agents Work, Fail & Get Fixed  
**Policy Status**: `LOCKED_BY_OWNER` (Hash: `adeaaf1e3c8754e952b555bcbba36add0965afa1eebe8dbd352f81e8954aeed1`)  
**Audience Profile**: `en-US` (Hash: `948de1cb240c4a86f96a74f78f58db888e2ae01124fc6060dac4df1666933faf`)  

---

## 1. Niche Enforcement Audit & Negative Test Matrix

The owner-locked policy strictly mandates that OpenMontage videos must address practical software engineering questions regarding AI coding agent internals, reliability, debugging, secure tool use, context/memory, and reproducible agent evaluation.

### A. Allowed Topic Families Verification

| Family ID | Canonical Tags | Example Tested In-Scope Topic | Gate Verdict | Test Case | Status |
|---|---|---|---|---|---|
| `context_memory` | context windows, session persistence, repo context | *Why Coding Agents Lose Project Context Between Sessions* | `ALLOWED` | `test_gate_and_selector.py::test_gate_001` | **PASS** |
| `agent_tool_use` | tool calling, MCP, sandbox execution, permissions | *How Autonomous Coding Agents Execute Tools in Secure Sandboxes* | `ALLOWED` | `test_gate_and_selector.py::test_gate_001` | **PASS** |
| `debugging_reliability` | failed tests, regressions, retries, fallbacks | *Why Coding Agents Fail Complex Multi-File Refactorings* | `ALLOWED` | `test_gate_and_selector.py::test_gate_001` | **PASS** |
| `agent_evaluation` | reproducible benchmarks, test design, SWE-bench | *Benchmarking AI Coding Agents on Real Bug Fix Repositories* | `ALLOWED` | `test_gate_and_selector.py::test_gate_001` | **PASS** |
| `agent_architecture` | orchestration, checkpoints, handoffs, subagents | *Single-Agent vs Multi-Agent Systems for Code Generation* | `ALLOWED` | `test_gate_and_selector.py::test_gate_001` | **PASS** |

### B. Blocked Topics Negative Test Matrix

| Blocked Subject | Test Input Candidate | Expected Behavior | Actual Gate Output | Test Result |
|---|---|---|---|---|
| `generic_ai_news` | "OpenAI Announces New Partnership with Financial Media" | Rejected | `ScopeVerdict(status=REJECTED, reason='generic_ai_news')` | **PASS** |
| `ai_art_image_video_generation` | "Midjourney v7 and Runway Gen-3 Video Generation Tutorial" | Rejected | `ScopeVerdict(status=REJECTED, reason='ai_art_image_video_generation')` | **PASS** |
| `model_launch_without_agent_impact` | "New 7B Base LLM Architecture Released for Mobile Phones" | Rejected | `ScopeVerdict(status=REJECTED, reason='model_launch_without_agent_impact')` | **PASS** |
| `general_tech_hardware` | "Nvidia Blackwell Ultra GPU Architecture Deep Dive" | Rejected | `ScopeVerdict(status=REJECTED, reason='general_tech_hardware')` | **PASS** |
| `unverified_product_rankings` | "Top 10 AI Tools That Will Replace All Software Engineers" | Rejected | `ScopeVerdict(status=REJECTED, reason='unverified_product_rankings')` | **PASS** |
| **Zero Eligible Topics** | Empty feed / all candidates rejected | `NO_ELIGIBLE_TOPIC` | Returns `NO_ELIGIBLE_TOPIC`, generates 0 projects | **PASS** |

---

## 2. Real E2E Rehearsals & Acceptance Evidence

The fixed-niche test suite (`pytest tests/fixed_niche/`) was executed locally against commit `2b8b8b09ae31c63e13ee370530310ae83f4b973f`:
- **Command**: `pytest tests/fixed_niche/`
- **Result**: `68 passed in 442.74s (0:07:22)`
- **Exit Code**: `0`

### Detailed Inspection of In-Scope Rehearsals:

1. **Rehearsal Topic 1: Context Memory (`cand_agent_context_01`)**
   - **Viewer Question**: *Why can an AI coding agent forget project rules between sessions?*
   - **Primary Source**: Official Anthropic / OpenAI Context Engineering Documentation
   - **Narration Duration**: 71.200s (Target [65.0, 75.0]s)
   - **Visual Beats**: 7 distinct visual beats (`news_visual_plan.json`)
   - **Max Scene Hold**: 10.15s (Strictly <= 12.0s policy)
   - **ASR Captions**: Monotonic word timestamps generated via faster-whisper from final audio
   - **Safe Rail Compliance**: Bottom rail (16%) reserved exclusively for captions; 0 overlay collisions
   - **Cryptographic Release Manifest**: HMAC-SHA256 signature verified by `lib/qa_signing.py`

2. **Rehearsal Topic 2: Sandbox Tool Governance (`us_ai_short_01`)**
   - **Viewer Question**: *How do coding agents safely execute untrusted bash commands?*
   - **Primary Source**: SWE-bench (ICLR 2024), DORA 2024 Report
   - **Video File**: `artifacts/us-migration/production_deliverables/us_ai_short_01/renders/final_short_en_US_9x16.mp4`
   - **Duration**: 72.000s (1080x1920 portrait, 30fps)
   - **Editorial QA Score**: 40.0 / 40.0 (`EDITORIAL_QA_REPORT.md`)

3. **Rehearsal Topic 3: Debugging & Regressions (`cand_agent_debug_03`)**
   - **Viewer Question**: *Why do coding agents write hallucinated test assertions?*
   - **Primary Source**: MetaGPT (ICLR 2024), ACM Computing Surveys
   - **Narration Duration**: 68.500s (Fitted via edge-tts rate sweep + atempo filter)
   - **Visual Beats**: 6 beats with genuine code terminal snippets and architecture flowcharts

---

## 3. Server Production State & YouTube Publishing Audit

### A. Current Publishing Schedule State (`config/publish_schedule.json` on `sandbox-video`)

```json
{
  "version": "1.0",
  "timezone": "Asia/Ho_Chi_Minh",
  "active_projects": [
    {
      "project_id": "cand_7d9acfe4bef468f1",
      "publish_date": "2026-10-26",
      "publish_time": "21:15"
    },
    {
      "project_id": "cand_a7e88d0582d65dc9",
      "publish_date": "2026-10-27",
      "publish_time": "09:15"
    }
  ]
}
```

- **Today (2026-10-26)**: Exactly **1 video scheduled** (`cand_7d9acfe4bef468f1`, MiniMax M3.1 Flash, 71.37s Shorts) for 21:15 ICT (14:15 UTC). Uploaded to YouTube as private with native scheduling.
- **Tomorrow (2026-10-27)**: Currently **1 video scheduled** (`cand_a7e88d0582d65dc9`, 71.60s Shorts) for Slot 1 (09:15 ICT). Slots 2 (14:15 ICT) and 3 (21:15 ICT) will be populated upon completion of ongoing pipeline candidate generation.

### B. YouTube OAuth & Release Safety Checks

- **Single-Platform Mode**: `MULTI_PLATFORM=0` in crontab ensures single-platform YouTube distribution. Facebook publishing is completely disabled.
- **Platform-Native Scheduling**: Video uploads specify `status.privacyStatus: "private"" and `status.publishAt`, guaranteeing zero premature public releases.
- **Project Retention Invariant**: Verified that `scripts/cleanup_published_projects.py` will NOT delete any active project from disk until its YouTube publication is confirmed via `PublishStore.get_record(pid)`. Active queue items are strictly preserved.

---

## 4. Final Verdict & Acceptance Decision

### **VERDICT: NOT DONE (PARTIALLY IMPLEMENTED)**

#### Summary of Proven Accomplishments:
1. **Duration Contract Solved**: Narration speech and MP4 rendering are strictly bound to [65.0, 75.0]s across all pipelines via edge-tts rate sweeping, `ffmpeg atempo` fallback, and dynamic scene retiming.
2. **Visual Pacing Verified**: Scene hold times are strictly capped at <= 12.0s with >= 6 visual beats. Post-render frame extraction validates non-blank frames, contrast, and scene transitions.
3. **Fixed-Niche Architecture Proven**: `tests/fixed_niche/` passes 68/68 tests with complete topic family gating, `NO_ELIGIBLE_TOPIC` support, and HMAC-SHA256 manifest signing.
4. **Today / Tomorrow YouTube Publishing Secured**: Candidate `cand_7d9acfe4bef468f1` is successfully scheduled for Today (21:15 ICT), and `cand_a7e88d0582d65dc9` is scheduled for Tomorrow (09:15 ICT).

#### Exact Remaining Blockers Preventing "DONE":
1. **Architectural Disconnection**: `FixedNicheScopeGate` is not invoked inside `tools/news/news_pipeline_cli.py` or `scripts/run_daily_news_pipeline.sh`. Production cron generated off-niche topics (*MiniMax M3.1 Flash*, *AllModels*).
2. **Fail-Open Fact-Checking**: `scripts/bind_news_evidence.py` fabricates synthetic source text files and source dates, approving claims on superficial 2-token matches rather than independent verification against authentic documentation.
3. **Unneeded Longform Generation**: `scripts/run_daily_news_pipeline.sh` unconditionally renders 16:9 longform videos despite the locked-niche policy explicitly disabling longform, adding ~5-10 minutes of unnecessary render time and false-positive QA failures.
4. **Timezone & Slot Schema Mismatch**: Daily cron reads `publish_slots_vn` and `Asia/Ho_Chi_Minh` rather than the US audience profile's `publish_slots_us` and `America/New_York`.
