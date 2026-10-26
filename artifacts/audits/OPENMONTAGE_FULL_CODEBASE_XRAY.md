# OpenMontage — Full Codebase & Architecture X-Ray

**Target Commit SHA**: `2b8b8b09ae31c63e13ee370530310ae83f4b973f`  
**Target Date**: 2026-10-26  
**Auditor**: Independent Principal Systems Architect & Video Pipeline QA Lead  
**Channel Locked Niche**: Practical AI Agent Engineering — How Coding Agents Work, Fail & Get Fixed  
**Policy Hash (SHA256)**: `adeaaf1e3c8754e952b555bcbba36add0965afa1eebe8dbd352f81e8954aeed1`  
**Profile Hash (SHA256)**: `948de1cb240c4a86f96a74f78f58db888e2ae01124fc6060dac4df1666933faf`  

---

## 1. Executive Summary & Codebase Baseline

OpenMontage currently contains two parallel architecture tracks that share infrastructure components (such as HyperFrames rendering, Whisper ASR captioning, and YouTube publishing), but diverge significantly in topic selection, evidence verification, and execution orchestration:

1. **The Fixed-Niche Architecture** (`lib/fixed_niche/`, `scripts/run_fixed_niche_video.py`, `tests/fixed_niche/`):
   - Fully designed, tested (68/68 passing tests), and aligned with the owner-locked policy (`us-ai-agent-engineering.locked.yaml`).
   - Implements strict gate filtering (`FixedNicheScopeGate`) allowing only 5 approved agent engineering topic families.
   - Enforces the `NO_ELIGIBLE_TOPIC` contract when insufficient evidence is found.
   - Enforces exact Shorts bounds: [65.0, 75.0] seconds.

2. **The Daily Production Pipeline** (`scripts/run_strict_docker_publish.sh`, `scripts/run_daily_news_pipeline.sh`, `tools/news/`):
   - Active in Docker on Phoenix production host (`sandbox-video`), triggered via crontab (`deploy/openmontage.cron`).
   - Uses `tools/news/news_pipeline_cli.py` with `CodexNewsSelector` to scrape NewsNow feeds.
   - **Architectural Disconnection**: The daily pipeline does NOT invoke `FixedNicheScopeGate`. As a result, it selected off-niche topics like *MiniMax M3.1 Flash* and *AllModels*.
   - **Legacy Longform Overhead**: The daily shell runner unconditionally renders both 16:9 Longform (`final_long_en_US_16x9.mp4`) and 9:16 Shorts (`final_short_en_US_9x16.mp4`), despite the locked niche explicitly specifying `longform.enabled_initially: false`.

---

## 2. Complete Runtime Dependency Graph & Stage Audit

### Pipeline A: Fixed-Niche Pipeline (Specification Path)

| Stage | Exact Entrypoint | Inputs & Dependencies | Outputs | Failure & Fallback Behavior | Production Reachability | Test Coverage | Status |
|---|---|---|---|---|---|---|---|
| **A1. Source Discovery** | `lib.fixed_niche.discovery.discover_sources` | HN, GitHub API, Vendor changelogs | Candidate raw items | Empty list if network/rate-limited | Called by `run_fixed_niche_video.py` | `test_research_and_demo.py` | **PASS** |
| **A2. Niche Scope Gate** | `lib.fixed_niche.gate.FixedNicheScopeGate.evaluate` | Candidate topic, tags, URL | `ScopeVerdict(status=ALLOWED/REJECTED, family=...)` | Rejects off-niche, returns `NO_ELIGIBLE_TOPIC` | Called by `run_fixed_niche_video.py` | `test_gate_and_selector.py` (10 tests) | **PASS** |
| **A3. Claim Fact-check** | `lib.fixed_niche.factcheck.verify_claims` | Pinned repo source, official docs, arxiv | `claim_ledger.json` with verified confidence | Fails closed on ungrounded figures | Called by `run_fixed_niche_video.py` | `test_research_and_demo.py` | **PASS** |
| **A4. Storyboard & Visuals** | `lib.fixed_niche.storyboard.generate_storyboard` | Script sections, claim ledger | `news_visual_plan.json` (>=6 beats, <=12s hold) | Re-segments beats if hold >12s | Called by `run_fixed_niche_video.py` | `test_storyboard_and_visuals.py` (7 tests) | **PASS** |
| **A5. Narration & Audio** | `lib.audio.narration_orchestrator` | Script text, edge-tts, ffmpeg atempo | `narration.mp3` [65.0, 75.0]s | Sweeps rate ±5% to ±30%, applies ffmpeg atempo fallback | Called by `run_fixed_niche_video.py` | `test_audio_and_qa.py` | **PASS** |
| **A6. Captions & Timestamps** | `lib.fixed_niche.captions.generate_captions` | `narration.mp3`, whisper/faster-whisper | `word_timestamps.json`, `subtitles.srt` | Fails closed if non-monotonic cues | Called by `run_fixed_niche_video.py` | `test_captions.py` (6 tests) | **PASS** |
| **A7. Media Rendering** | `scripts.run_fixed_niche_video.render_project_composition` | `hyperframes_reels/`, Chromium, ffmpeg | `renders/final_short_en_US_9x16.mp4` | Serialized via `MediaCpuLock` (max parallel: 1) | Standalone CLI | `test_production_runner.py` (17 tests) | **PASS** |
| **A8. Independent QA** | `scripts.independent_editorial_qa.evaluate_project` | Decoded frames, ffprobe, ledger | QA Score (target: 40/40) | Quarantine project on failure | Rehearsal & manual preflight | `test_audio_and_qa.py` | **PASS** |
| **A9. Cryptographic Signing** | `lib.qa_signing.sign_release_manifest` | Media hash, ledger hash, metadata hash | `approval.json` (HMAC-SHA256) | Release rejected without valid signature | Release preflight | `test_audio_and_qa.py` | **PASS** |

---

### Pipeline B: Daily Production Pipeline (Active Server Path)

| Stage | Exact Entrypoint | Inputs & Dependencies | Outputs | Failure & Fallback Behavior | Production Reachability | Test Coverage | Status |
|---|---|---|---|---|---|---|---|
| **B1. Cron Trigger** | `deploy/openmontage.cron` (23:00 UTC) | Docker host cron, environment variables | Execution of `run_strict_docker_publish.sh` | Appends to `logs/cron_pipeline.log` | **Active on server** | System smoke test | **PASS** |
| **B2. Strict Orchestrator** | `scripts/run_strict_docker_publish.sh` | `config/publish_schedule.json`, lockfiles | Multi-stage lifecycle execution | Retries up to 2 times; flock prevents overlap | **Active on server** | System smoke test | **PASS** |
| **B3. NewsNow Ingest & Select** | `tools/news/news_pipeline_cli.py` | `data/newsnow_feed.json`, `CodexNewsSelector` | Candidate project directories in `projects/` | Recycles feed up to 48h; unconstrained by locked niche | **Active on server** | `test_news_pipeline_cli.py` | **FAIL** (Missing Niche Gate) |
| **B4. AI Director Generation** | `scripts/run_daily_news_pipeline.sh` | Codex CLI, LLM prompts, project dir | `script_en_US.json`, HTML compositions | Retries up to 3 times; quarantine on error | **Active on server** | Rehearsal tests | **PASS** |
| **B5. Evidence Binder** | `scripts/bind_news_evidence.py` | `research_brief.json`, script | `claim_ledger.json`, source snapshots | Fabricates source timestamps; approves on 2-token match | **Active on server** | `test_bind_news_evidence.py` | **FAIL** (Fail-Open Factcheck) |
| **B6. TTS Speech Generation** | `scripts/run_daily_news_pipeline.sh:873` | `narration_text.txt`, edge-tts, ffmpeg | `narration.mp3` [65.0, 74.5]s | Rate sweep ±5%..±30% + `ffmpeg atempo` fallback | **Active on server** | Audio integration tests | **PASS** (Fixed in 160360ea) |
| **B7. ASR Caption Alignment** | `scripts/install_news_captions.py` | `narration.mp3`, faster-whisper | Burned-in & HTML GSAP seek-safe clips | Safe rail check; fallbacks for offline test | **Active on server** | `test_install_news_captions.py` | **PASS** |
| **B8. HyperFrames Rendering** | `hyperframes render` CLI | `hyperframes/`, `hyperframes_reels/` | `final_short_en_US_9x16.mp4`, `final_long_en_US_16x9.mp4` | Quarantines candidate on exit != 0 | **Active on server** | Docker render rehearsals | **PARTIAL** (Unneeded Longform) |
| **B9. Visual QA Gate** | `lib/news_visual/qa.py` | Rendered MP4s, ffmpeg frame sampling | `visual_qa_report.json` | Quarantines if beat >12s or contrast low | **Active on server** | `tests/news_visual/` (43 tests) | **PARTIAL** (No Semantic Match) |
| **B10. Queue & Slot Allocation** | `scripts/run_strict_docker_publish.sh:658` | Validated projects, `publish_schedule.json` | Scheduled slot assignments in schedule JSON | Assigns VN slots; deduplicates project IDs | **Active on server** | `test_publish_cleanup.py` | **PARTIAL** (VN vs US Slot Mismatch) |
| **B11. YouTube Platform Publisher** | `tools/publishers/youtube_publisher.py` | `youtube_token.json`, OAuth credentials | Private video uploaded with `publishAt` | Fails closed on missing asset or invalid token | **Active on server** | `test_youtube_publisher.py` | **PASS** |
| **B12. Published Project Cleanup** | `scripts/cleanup_published_projects.py` | `PublishStore`, active schedule queue | Deletes only confirmed published project dirs | Preserves all active queued projects | **Active on server** | `test_published_cleanup_sweep.py` | **PASS** |

---

## 3. Disconnected Implementations & Architectural Divergence

1. **Gate Disconnection**: `FixedNicheScopeGate` in `lib/fixed_niche/gate.py` is completely disconnected from `tools/news/news_pipeline_cli.py`. The daily cron pipeline generates candidates from arbitrary tech news instead of locking strictly to *Practical AI Agent Engineering*.
2. **Factcheck Rigor Divergence**: The fixed-niche pipeline enforces real source captures from official documentation or repositories, whereas `scripts/bind_news_evidence.py` fabricates source text files from the model's own brief and approves claims with superficial token overlap.
3. **Redundant Longform Generation**: The locked niche explicitly disables longform, yet `run_daily_news_pipeline.sh` renders `final_long_en_US_16x9.mp4` on every single run, wasting GPU/CPU time and introducing unnecessary failure points (e.g. beat timing mismatch in 16:9).
4. **Timezone & Slot Key Mismatch**: The daily cron assigns slots under `today_publish_slots_vn` and `publish_slots_vn` with `Asia/Ho_Chi_Minh`, while the US audience profile specifies `America/New_York` and `publish_slots_us`.
