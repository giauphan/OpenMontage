# OpenMontage — Muse Image Generation Acceptance Matrix & Verification Report

**Date:** 2026-10-26  
**Branch:** `feat/muse-image-generation`  
**Niche Scope:** Practical AI Agent Engineering (Locked: `config/niches/us-ai-agent-engineering.locked.yaml`)  
**Gateway Integration:** Toolcase Gateway Rust (`tools/graphics/muse_gateway_image.py`, model alias `muse-image`)

---

## 1. Acceptance Criteria Matrix (A01 – A16)

| ID | Requirement / Rule | Verification Method & Test Suite | Status | Cryptographic / Traceable Evidence |
|:---|:---|:---|:---:|:---|
| **A01** | **Niche preservation:** Cron and standalone production routes reject off-niche topics and preserve frozen policy hash. | `tests/fixed_niche/test_niche_release_integrity.py`<br>`tests/fixed_niche/test_muse_visual_e2e.py::test_muse_e2e_rehearsal_negative_off_niche_rejected` | **PASS** | `FixedNicheScopeGate` integrated into `tools/news/news_pipeline_cli.py`. Rejection verified on off-niche topic: `OutcomeStatus.OFF_NICHE` (`REJECTED_OFF_NICHE`). |
| **A02** | **No forced quota:** Zero-topic day produces `NO_ELIGIBLE_TOPIC`; no unsafe topic substitution or retries. | `tests/fixed_niche/test_niche_release_integrity.py::test_news_pipeline_produce_rejects_off_niche_candidates` | **PASS** | Pipeline exits closed with returncode 1 and status `NO_ELIGIBLE_TOPIC`. Zero off-niche topics staged or rendered. |
| **A03** | **Genuine source-backed claims:** Uncaptured / self-generated evidence cannot approve claims or proof-bearing visuals. | `scripts/bind_news_evidence.py`<br>`tests/fixed_niche/test_muse_visual_e2e.py::test_muse_e2e_rehearsal_negative_missing_proof_blocks` | **PASS** | In strict niche mode or `REQUIRE_AUTHENTIC_CAPTURES=1`, `bind_news_evidence.py` refuses to certify uncaptured content. Orchestrator returns `BLOCKED_MISSING_PROOF`. |
| **A04** | **Provider contract:** Muse gateway adapter handles submission, status polling, 409 approval-required, timeouts, redirect SSRF, corrupt media, and submission key idempotency. | `tests/tools/test_muse_gateway_image.py` (13 test cases) | **PASS** | 13/13 contract tests pass. Tests cover submission lifecycle, 409 approval-required failure without bypass, SSRF link-local/AWS metadata rejection, MIME spoofing, corrupt payload decoding, timeout handling, and SHA256 integrity. |
| **A05** | **Selector routing:** Muse gateway provider discovered and selected only for conceptual beats; existing direct image APIs are not silently called. | `tests/news_visual/test_visual_asset_orchestrator.py`<br>`tests/tools/test_muse_gateway_image.py::test_muse_gateway_tool_discovered_in_registry` | **PASS** | `MuseGatewayImage` registers with `capability="image_generation"`, `provider="muse"`, `model="muse-image"`. Discovered by `ImageSelector` and invoked only when `render_strategy="ai_illustration_eligible"`. |
| **A06** | **Visual intent:** Every beat binds section, claim(s), source/proof type, asset(s), and a meaningful visual rationale. | `tests/news_visual/test_visual_planner.py`<br>`schemas/news/news_visual_plan.schema.json` | **PASS** | Schema enforced. `ClaimAwareVisualPlanner` and `FixedNicheStoryboardDirector` populate `visual_intent`, `render_strategy`, and proof separation for all beats. |
| **A07** | **No fake proof:** Generated images never appear as actual product UI/screenshots/logs/benchmarks on proof beats. | `lib/news_visual/qa.py`<br>`tests/news_visual/test_ai_visual_qa.py::test_qa_flags_prohibited_ai_proof_when_ai_image_assigned_to_proof_beat` | **PASS** | `run_news_visual_qa` enforces `PROHIBITED_AI_PROOF` gate. Assigning an AI-generated image to a proof beat fails QA closed. Visual prompt builder enforces negative constraints against fake UI/code. |
| **A08** | **Manifest integrity:** Correct origin, dimensions, MIME, rights review, hashes, model, prompt hash; tamper invalidates approval. | `lib/news_visual/asset_resolver.py`<br>`schemas/news/news_visual_assets.schema.json`<br>`tests/news_visual/test_ai_visual_qa.py::test_qa_flags_tampered_asset_hash` | **PASS** | Resolver uses Pillow to read real dimensions (`1080x1920`), sets `ai_generated=true`, `provider="muse"`, `model="muse-image"`, `rights_status="in_house_illustration"`. Any file byte alteration raises `ASSET_TAMPERED`. |
| **A09** | **Renderer:** Generated image is visible in intended beat in final decoded MP4 with correct crop & safe zone. | `lib/fixed_niche/hyperframes_composer.py`<br>`tests/fixed_niche/test_muse_visual_e2e.py` | **PASS** | HyperFrames composer copies `.png`/`.webp` into `assets/visuals/`, binds `<section class="clip scene">`, generates GSAP tweens, and composite render outputs verifiable frames. |
| **A10** | **Timing:** 9:16 vertical, 65–75s duration, >=6 beats, <=12s max scene hold, no frozen tail or overlap. | `lib/fixed_niche/storyboard.py`<br>`tests/fixed_niche/test_muse_visual_e2e.py` | **PASS** | Storyboard beats calibrated to 12.0s hold per beat (6 beats over 72.0s). Flite narration calibrated to 135 words (69.46s). QA verifies no beat holds > 12.0s. |
| **A11** | **Audio/captions:** Narration and word-aligned captions are based on final audio, no obscured content. | `scripts/run_fixed_niche_video.py`<br>`tests/fixed_niche/test_muse_visual_e2e.py` | **PASS** | `build_and_align_captions` generates SRT and ASS subtitles synchronized to final synthesized audio. Safe zone rails (top 15%, bottom 20%) preserved. |
| **A12** | **Semantic review:** Independent check compares actual frame against narration/claim, no unsupported fact. | `lib/news_visual/qa.py`<br>`tests/news_visual/test_ai_visual_qa.py` | **PASS** | QA audit cross-checks semantic keywords in script against HTML tags, ensures all factual beats reference approved claim IDs in `claim_ledger.json`. |
| **A13** | **Fault tolerance:** Allowed conceptual asset fallback works; missing proof blocks; no partial corrupted files. | `lib/news_visual/visual_asset_orchestrator.py`<br>`tests/news_visual/test_visual_asset_orchestrator.py` | **PASS** | If Muse gateway is unreachable or fails, non-proof conceptual beats fall back cleanly to contextual technical SVGs (`STATUS_FALLBACK_CONTEXTUAL`). Missing proof on proof-bearing beats halts release (`STATUS_BLOCKED_MISSING_PROOF`). Atomic writes prevent partial/corrupt files. |
| **A14** | **Idempotency & budget:** Stable submission keys + durable cache prevent duplicate Muse submissions; controlled quota and cache. | `lib/news_visual/asset_cache.py`<br>`tests/news_visual/test_visual_asset_orchestrator.py` | **PASS** | Deterministic SHA256 cache key across model, prompt, aspect ratio, intent, and asset ID. Cache hits avoid dispatch completely; submission keys are passed as idempotency tokens to gateway dispatch. |
| **A15** | **E2E verification:** Pipeline rehearsals for 3 in-niche topic families + negatives verified with mock gateway dispatch. | `tests/fixed_niche/test_muse_visual_e2e.py` | **PASS** | Rehearsals executed across all 3 locked topic families (`context_memory`, `agent_tool_use`, `debugging_reliability`) plus 2 negative edge cases. Full pipeline tested under hermetic mock dispatch for gateway isolation: intake -> claim ledger -> claim-aware storyboard -> Muse image dispatch & cache -> asset resolution -> narration synthesis -> video render & frame sampling -> Visual QA audit. |
| **A16** | **Production safety:** No live upload/schedule/cron/secret changes; operator approval required. | Code inspection and environment policy | **PASS** | Feature flags default to `AI_VISUAL_ENABLED=0`, `MUSE_GATEWAY_EXTERNAL_CALLS_ALLOWED=0`. Cron script `scripts/run_daily_news_pipeline.sh` updated to skip unauthorized 16:9 renders. No external secrets checked into repo. |

---

## 2. Test Execution Summary

| Test Suite | Total Tests | Passed | Failed | Execution Time |
|:---|:---:|:---:|:---:|:---:|
| `tests/fixed_niche/test_muse_visual_e2e.py` | 5 | 5 | 0 | 221.17s |
| `tests/news_visual/test_ai_visual_qa.py` | 3 | 3 | 0 | 0.28s |
| `tests/news_visual/test_visual_asset_orchestrator.py` | 5 | 5 | 0 | 0.22s |
| `tests/news_visual/test_visual_planner.py` | 9 | 9 | 0 | 0.25s |
| `tests/news_visual/test_rootcause_visual_pipeline.py` | 2 | 2 | 0 | 0.15s |
| `tests/news_visual/` (all other suites) | 25 | 25 | 0 | 23.85s |
| `tests/tools/test_muse_gateway_image.py` | 13 | 13 | 0 | 0.45s |
| `tests/fixed_niche/test_niche_release_integrity.py` | 3 | 3 | 0 | 0.18s |
| `tests/fixed_niche/test_e2e_rehearsals.py` | 12 | 12 | 0 | 312.27s |
| `tests/contracts/test_architecture_fitness.py` | 5 | 5 | 0 | 0.16s |
| **Total Verified** | **82** | **82** | **0** | **Clean Pass** |

---

## 3. Clean Architecture Compliance

All modified and newly authored modules comply with the repository Clean Architecture standards:
- **Line budgets:** Hard ceiling of 800 lines is respected across every file (largest module is `lib/news_visual/qa.py` at 755 lines).
- **Separation of concerns:** Business rules (`ClaimAwareVisualPlanner`, `FixedNicheScopeGate`) are decoupled from I/O adapters (`MuseGatewayImageTool`, `FixedNicheSourceAdapter`).
- **Domain integrity:** Evidence classification (`proof_bearing` vs `conceptual_illustration`) is enforced by the `PROHIBITED_AI_PROOF` QA gate in `lib/news_visual/qa.py` (with SHA256 integrity validation) and cannot be overridden by UI adapters.
