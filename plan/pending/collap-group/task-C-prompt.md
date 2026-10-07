# Scoped Haiku coding tasks after supervisor review

## Shared constraints

Exact model claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md and PROJECT_CONTEXT.md before editing. Working directory is remote sandbox-video /home/ubuntu/OpenMontage. Use Read, Edit, Write, Glob, Grep ONLY. Bash is intentionally unavailable: the supervisor will run tests remotely after your edits. Do not claim tests ran. Do not create shell scripts, modify settings/hooks/permissions, perform repository-wide formatting, delete tests, or change files outside your assigned scope. Do not commit or use other models. All external provider calls are prohibited. Implement actual code rather than only prose. Fail closed. You have 30 minutes maximum; avoid scope expansion. End with changed files and precise unverified test command. Earlier agent success claims are not reliable.

## Task C — H3 actual media execution

Exclusive write scope: lib/multishot_media.py, lib/multishot_final.py, tests/contracts/test_multishot_m3.py, tests/contracts/test_multishot_m4.py, tests/contracts/test_multishot_media_recovery.py (new), plan/pending/collap-group/16_H3_RESULT.md. No scheduler, references, continuity, shared schemas or status ledger changes.

Read 06_RECOVERY_PLAN.md R4 and original plan acceptance. Repair actual FFmpeg commands: subtitle burn re-encodes video (no filtering with stream-copy); subtitle mux uses explicit stream mapping and compatible codecs; apply actual sidechain ducking, loudness and fades if requested, not amix labelled ducking. Handle silent base, narration, music, SFX and source audio. Validate duration bounds, configured profile, input completeness, atomic publication and bounded subprocesses. Fail-closed completion must verify current accepted revisions, actual final content/validation provenance, not just stale report booleans.

Write executable real-media tests generating tiny distinct colored clips and audio, exercising burn/mux, silent/narration/multiple audio cases, requested ducking/fades, missing middle and corrupt clips, clip ordering via decoded boundary pixels, and stale final evidence. You cannot run tests; supervisor will. ffmpeg/ffprobe provided remotely via static_ffmpeg.add_paths(). Mock-only argv assertions are insufficient. Preserve public API compatibility where possible, do not pretend unsupported options are implemented. If scope too broad, record exact remaining requirements rather than claiming H3 verified.
