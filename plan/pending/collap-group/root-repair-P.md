# H4 root-cause repair tasks

Shared: Haiku 4.5 exact claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md. Read/Edit/Write/Glob/Grep tools only. Supervisor runs all tests. 30 minutes maximum. No shell/permission modifications, paid calls, commits, repo-wide formatting or unrelated files. Do not claim tests ran. Read actual helper signatures before calling.

## Task P — public API correctness (exclusive tool source + public tests)
Write only tools/video/multishot.py, tests/contracts/test_multishot_public_tool.py, 25_H4_PUBLIC_RESULT.md.

Supervisor failure status_res.data[revision] expected 0 but real session starts 1. Fix test. Read actual lib/checkpoint.py: it has NO CheckpointValidationError symbol and does NOT accept guessed keywords. Import/catch real exception types or catch validation errors within execute. Ensure checkpoint operation invokes correct signature and does not set human_approval_required=False to override gated pipeline approval. Repository writer should enforce manifest gates; use correct stage/canonical artifact shape. Tests must complete gated story with human_approved False -> failure, True -> persisted valid checkpoint readback. Read test_multishot_checkpoint_recovery.py for actual fixture and signature.

Review operations currently accept bool(inputs.get(accepted)): strings become approvals. Require actual bool with no default. Missing reviewer/notes should reject, not fabricate approval. Validate project marker/root/project_id and workspace containment before every operation including checkpoint. Input JSON schema and execute both reject unknown operations/unsafe IDs.

Public tests currently mix invented fields/dummy reference outcomes and can fail after init. Reuse actual all_project_data and real tiny media helper; content hash is lib.multishot_jobs.file_hash(path), not probe[file_hash]. Outcomes require status completed and original bound input hash/report binding. Test init/status idempotence/unknown operations/schema/path security/checkpoint gate; no direct status mutation or mocks bypassing validation. Session agent concurrently fixes schema and integrity, so read final signatures. Report only unverified results, no H4 completion claim.
