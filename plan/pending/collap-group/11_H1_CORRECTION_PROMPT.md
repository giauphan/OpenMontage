# H1 correction — actual code changes required

You are Claude Haiku 4.5, coding on sandbox-video /home/ubuntu/OpenMontage. Read AGENT_GUIDE.md and CLAUDE.md. This CLI already runs remotely, so run .venv/bin/python tests here. Maximum 30 minutes. No other models, commits, paid providers, or unrelated changes.

The last agent falsely claimed H1/H2 completion. Supervisor compared every source file with the transfer archive: ZERO application code changed. pass_all_validator still exists in lib/multishot_jobs.py:241. Remote suite was 97 passed, 26 SKIPPED, not 103/103. Fix misleading 10_H1_H2_RESULT.md and current 05 status; do not preserve false verified claims as current status.

Implement H1 ONLY, not H2. Read actual code and callers, then write regressions FIRST and run them to prove the following current defects. Do not repeat existing deep-copy changes as new work.

1. lib/multishot_continuity.py continuity_in_for_shot only requires some accepted predecessor. For shot order 3, acceptance through shot 1 must NOT allow generation; require immediately previous planned shot. Ensure IDs need not sort or encode sequence numerically. Extend helper with explicit plan/order context if needed, updating callers/tests. Fail closed for insufficient ordering context.
2. accept_shot compares merged state for repeat acceptance, not original payload. Accept payload P then attempt different P2 with identical resulting merged state: must raise. Persist exact original accepted shot/order/end-state data or canonical fingerprint, deliberately update schemas/multishot/continuity_state.schema.json (additionalProperties false), validate it, and preserve immutable caller inputs.
3. lib/multishot_references.py generation readiness skips master provenance if absent. Keyframes for shots with required identities must have matching reviewed master/character coverage and fresh content hashes. Test missing provenance, wrong identity/master, corrupt/missing PNG, changed and re-registered master, and valid reference path. Use real PNG fixtures.
4. Remove trailing whitespace in touched files.

Write scope: continuity/reference helpers, their schemas, direct callers only when contract signatures require it, and focused tests. Do not edit scheduler/media code. Supervisor independently handles FFmpeg setup.

Use Read/Edit/Write tools instead of shell cat/heredoc/sed when permissions deny shell commands. Allowed shell .venv/bin/python, git read-only and pytest. Do not waste time trying denied equivalent shell writes.

Run focused tests before and after; preserve negative intent. If unable to implement after two focused attempts, record exact blocker instead of claiming done. Report baseline and post-fix exact commands/counts/skips, actual changed lines, and missing coverage in 12_H1_CORRECTION_RESULT.md. Treat H1 as verified only if these three NEW regressions genuinely exercise and pass corrected code. H2 remains not verified. Return implementation facts, no '100% coverage' claims without measured evidence.
