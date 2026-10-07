# Scoped Haiku coding tasks after supervisor review

## Shared constraints

Exact model claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md and PROJECT_CONTEXT.md before editing. Working directory is remote sandbox-video /home/ubuntu/OpenMontage. Use Read, Edit, Write, Glob, Grep ONLY. Bash is intentionally unavailable: the supervisor will run tests remotely after your edits. Do not claim tests ran. Do not create shell scripts, modify settings/hooks/permissions, perform repository-wide formatting, delete tests, or change files outside your assigned scope. Do not commit or use other models. All external provider calls are prohibited. Implement actual code rather than only prose. Fail closed. You have 30 minutes maximum; avoid scope expansion. End with changed files and precise unverified test command. Earlier agent success claims are not reliable.

## Task B — H2 strict resume

Exclusive write scope: lib/multishot_jobs.py, tests/contracts/test_multishot_jobs_recovery.py, tests/contracts/test_multishot_m2.py, tests/contracts/test_multishot_m5.py, tests/contracts/test_multishot_resume_integrity.py (new), plan/pending/collap-group/15_H2_RESULT.md. No shared schema/continuity/reference/media changes.

Remove production pass_all_validator and imports. Restore strict _reuse and external completed hydration: require original input_hash, content_hash and actual validation report, all matching current spec/readable file; do NOT invent current hashes or replace missing validation evidence with synthetic report. If completed provenance missing/invalid, fail closed without silently reusing or creating duplicate paid requests. Existing known handle may re-download and validate from same provider job. Preserve durable intents, unknown submission fail-closed, bounded retry/concurrency, atomic jobs.json persistence and full payload fingerprinting.

Integration fixtures must be genuine tiny FFmpeg video, not FakeProvider junk bytes with injected pass validator. Keep fake byte provider appropriate only to isolated scheduler unit tests using test-local explicit validator. Production default validation must reject junk. Tests should explicitly distinguish pure mocked scheduler units from real media integration. Remote ffmpeg/ffprobe are available through static_ffmpeg.add_paths(); supervisor runs pytest with those paths. DO NOT add static_ffmpeg dependency to product code. Add regressions for path-only external completion, missing validation, mismatched input hash/content hash, corrupted video, and same-job download retry. Inspect existing recovery tests first to avoid duplicate cases.

M5 reference fixtures may need required master provenance: register actual character master and derive its keyframe correctly rather than weakening new H1 validation. H1 helper task runs concurrently; do not edit its files. For current single-character fixture pass derived_from_character="char_mochi" (use actual character ID from fixture).

