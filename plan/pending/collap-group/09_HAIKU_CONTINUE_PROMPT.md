# Haiku continuation — implement, verify, hand off

Use only claude-haiku-4-5-20251001. You are the coding agent. The user authorizes implementation of the multi-shot plan through all offline acceptance gates, not just another planning document. Work in bounded 30-minute tasks; this invocation has a 30-minute cap. Prioritize H1 follow-up then H2, and leave exact handoff evidence. Do not attempt the entire remaining plan in one invocation.

Read AGENT_GUIDE.md, PROJECT_CONTEXT.md, CLAUDE.md, scoped instructions, and plan/pending/collap-group/01 through 08. All execution is on sandbox-video; this CLI invocation already runs there at /home/ubuntu/OpenMontage, so shell commands here are remote execution, not local tests. Use .venv/bin/python for pytest. Preserve existing dirty repairs transferred by the supervisor. Do not touch credentials, commit, change branches, revert unrelated files, call paid media providers, or substitute models.

## H1 follow-up

Fix the review gaps in 08_H1_RESULT.md with genuine negative regressions:
- Require the immediate planned predecessor, not merely any accepted shot.
- Idempotent acceptance requires identical original shot/order/end-state input, not just an equal merged result.
- Required identity references and master provenance must not silently be omitted.
- Make deliberate backward-compatible schema changes if metadata is necessary; continuity_state forbids additional properties.
- Remove trailing whitespace in touched source.

Write scope: lib/multishot_continuity.py, lib/multishot_references.py, related multishot schemas, focused continuity/M1/M5 reference tests, and plan reports. Inspect callers before changing signatures. Do not invent a Python creative orchestrator.

## H2 once H1 is verified

Restore strict scheduler resume provenance in lib/multishot_jobs.py. Remove production pass_all_validator and test imports of it. Never manufacture current hashes for path-only records. Reuse must bind readable current media, content hash, full payload/input revision fingerprint, and genuine validation evidence. Missing/corrupt/stale outputs cannot be completed. Preserve durable handles/intents, fail-closed uncertain submission, download retry from the same job, bounded concurrency, and full real-provider payloads. Use real tiny video fixtures for integration tests; no junk-byte media accepted by production. Mock transport only for provider API behavior. Keep immutable planned input and persisted acceptance eligibility distinct.

Write scope additionally: lib/multishot_jobs.py, lib/multishot_provider.py, relevant job schemas and multishot job/M2/M5 tests. Preserve cost-tracker integration requirements for H4 if out of scope; report explicitly.

## Validation and report

Run baseline and post-repair focused tests with actual exit codes, then the multishot contract suite if time permits. Never weaken a negative assertion to obtain green tests. No piping pytest through head/tail. Diagnose missing tools: ffmpeg was absent from login-shell PATH, but do not mark media tests verified if skipped. You may install compatible test/media dependencies in the existing remote environment if needed; no sudo/system changes without approval. Do not inspect secret values.

At 25 minutes stop adding scope, verify, and write plan/pending/collap-group/10_H1_H2_RESULT.md with exact changed paths, tests/counts/failures/skips, remaining gates, and restart command. Update the current status portion of 05_IMPLEMENTATION_STATUS.md accurately, retaining historical evidence as historical. If blocked on one task, record why; do not claim the full plan done. Return a concise implementation handoff.
