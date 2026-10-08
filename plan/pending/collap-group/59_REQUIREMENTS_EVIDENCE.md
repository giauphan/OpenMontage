# 59. Requirements Evidence & Task Ledger (Multi-Shot Beta Pipeline)

## Status & Execution Notice
- **Status:** Beta (not production-ready).
- **Claim Policy:** No claim of end-to-end or quality release completion.
- **Supervisor Status:** Last supervisor run: 345 passed, 1 failed (failing new eligibility test forwarding execution-only kwargs into preflight; another agent repairing/e2e currently). Do NOT claim tests passed or reference unverified e2e evidence.
- **Quality Gates:** Live provider and human quality gates remain blocked pending approval; stable cron not activated.

---

## Task Ledger (TASK 001 - TASK 021)

| Task ID | Title | Implementation Symbol / Module | Test Symbol / Module | Unresolved Gaps / Notes |
|---|---|---|---|---|
| TASK 001 | Project schemas | `schemas/multishot/` | `tests/contracts/test_multishot_schemas.py` | Complete schema validation rules |
| TASK 002 | Project workspace | `lib/multishot_workspace.py` | `tests/contracts/test_multishot_workspace.py` | Path traversal security verified |
| TASK 003 | Story planner | `lib/multishot_session.py` | `tests/contracts/test_multishot_session.py` | Beat decomposition logic |
| TASK 004 | Character/style bible | `lib/multishot_session.py` | `tests/contracts/test_multishot_m1.py` | Immutable locks and rendering rules |
| TASK 005 | Shot planner | `lib/multishot_session.py` | `tests/contracts/test_multishot_prepare.py` | Minimum 2 shots & state tracking |
| TASK 006 | Continuity engine | `lib/multishot_continuity.py` | `tests/contracts/test_multishot_continuity_recovery.py` | State propagation & stale detection |
| TASK 007 | Prompt builder | `lib/multishot_prompt_builder.py` | `tests/contracts/test_multishot_generation_preflight.py` | Self-contained shot prompt compilation |
| TASK 008 | Reference manager | `lib/multishot_references.py` | `tests/contracts/test_multishot_m2.py` | Keyframe and reference binding |
| TASK 009 | Video provider interface | `lib/multishot_provider.py` | `tests/contracts/test_multishot_m3.py` | Abstract submit/poll/download adapter |
| TASK 010 | Video job scheduler | `lib/multishot_jobs.py` | `tests/contracts/test_multishot_jobs_recovery.py` | Bounded concurrency & job lifecycle |
| TASK 011 | Download manager | `lib/multishot_media.py` | `tests/contracts/test_multishot_media_recovery.py` | Atomic downloads and safety checks |
| TASK 012 | ffprobe wrapper | `lib/multishot_media.py` | `tests/contracts/test_multishot_m4.py` | Duration, resolution, FPS extraction |
| TASK 013 | Shot validator | `lib/multishot_media.py` | `tests/contracts/test_multishot_m5.py` | Clip validation and tolerance checks |
| TASK 014 | FFmpeg normalizer | `lib/multishot_media.py` | `tests/contracts/test_multishot_manifest.py` | Resolution/fps normalization to 1080p30 |
| TASK 015 | Ordered concat | `lib/multishot_final.py` | `tests/contracts/test_multishot_h1_integrity.py` | Plan-ordered deterministic assembly |
| TASK 016 | Audio/subtitle layer | `lib/multishot_final.py` | `tests/contracts/test_multishot_public_tool.py` | Optional narration, music, subtitles |
| TASK 017 | Final master render | `lib/multishot_final.py` | `tests/contracts/test_multishot_finalize_integration.py` | Master `final_video.mp4` output |
| TASK 018 | Final validator | `lib/multishot_finalize_operations.py` | `tests/contracts/test_multishot_public_finalize.py` | Completion validation before commit |
| TASK 019 | Resume | `lib/multishot_session.py` | `tests/contracts/test_multishot_resume_integrity.py` | Crash recovery & state reconciliation |
| TASK 020 | Single-shot retry | `lib/multishot_session.py` | `tests/contracts/test_multishot_generation_execution.py` | Transient error retry on single shot |
| TASK 021 | Single-shot regeneration | `lib/multishot_session.py` | `tests/contracts/test_multishot_public_generate.py` | Re-execution rejection for accepted shots |

---

## Security & Cost Recovery Audit (Read-Only Inspection Evidence)

1. **Path Security:** Verified in `tools/video/multishot.py` and `lib/multishot_workspace.py` using strict regex matching (`^[-_a-zA-Z0-9]+$`), symlink blocking, and relative resolution checks against `PROJECTS_DIR`.
2. **Cost Governance:** `actual_cost_source=estimate` (not real billing); failure/unknown reservation retained; currently accepted generate re-execution rejects (prevents duplicate billing/re-execution of valid shots).
3. **Execution Gaps:** Live provider integration and human review gates require explicit approval; background stable cron not activated.
