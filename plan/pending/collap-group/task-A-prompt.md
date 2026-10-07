# Scoped Haiku coding tasks after supervisor review

## Shared constraints

Exact model claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md and PROJECT_CONTEXT.md before editing. Working directory is remote sandbox-video /home/ubuntu/OpenMontage. Use Read, Edit, Write, Glob, Grep ONLY. Bash is intentionally unavailable: the supervisor will run tests remotely after your edits. Do not claim tests ran. Do not create shell scripts, modify settings/hooks/permissions, perform repository-wide formatting, delete tests, or change files outside your assigned scope. Do not commit or use other models. All external provider calls are prohibited. Implement actual code rather than only prose. Fail closed. You have 30 minutes maximum; avoid scope expansion. End with changed files and precise unverified test command. Earlier agent success claims are not reliable.

## Task A — finish H1

Exclusive write scope: lib/multishot_continuity.py, lib/multishot_references.py, schemas/multishot/continuity_state.schema.json, tests/contracts/test_multishot_continuity_recovery.py, tests/contracts/test_multishot_h1_integrity.py (new), plan/pending/collap-group/14_H1_RESULT.md. Do not edit M1/M5 tests: supervisor will flag fixture callers for next repair.

Read source carefully. Prior changes added expected_previous_shot_id and accepted_end_state_fingerprint but did not persist accepted order. Fix repeat acceptance so changing both expected_order and shot_order to a new equal value cannot pass for the same accepted shot. Persist accepted_order explicitly and validate new acceptance contiguity. Keep new schema metadata optional to load old artifacts, but fail closed when trying to repeat/resume acceptance without enough provenance. Do not require newly added metadata on all old initial schemas. Do not equate revision/version with shot order.

References currently skip all provenance checks if derived_from_character is None and don't check that the derived character is in shot.characters. Add multi-character keyframe provenance (e.g. optional derived_from_characters list whose master hashes are persisted), retaining derived_from_character compatibility. For each required character, insist keyframe provenance includes the matching current master hash, ownership, readable content. Reject missing provenance even when a keyframe exists. Return unique reference keys. Validate referenced masters belong to their stated characters. Update invalidation to cover all keyframe characters. Preserve environment semantics.

Add durable tests in tests/contracts/test_multishot_h1_integrity.py for missing provenance, wrong identity, two-character incomplete/complete provenance, corrupt images, replaced/re-registered masters, omitted ordering context, arbitrary nonnumeric IDs, changed repeat payload yielding same merged state, changed repeat order, and schema validation of new/legacy initial state. Use real PNG fixtures. Do not fabricate test runs.

