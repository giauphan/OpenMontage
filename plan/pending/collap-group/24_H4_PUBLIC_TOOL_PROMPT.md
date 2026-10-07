# H4b — registry-discovered multishot tool

Model: claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md and PROJECT_CONTEXT.md before editing. This CLI runs remotely on sandbox-video. Supervisor runs tests. Tools Read/Edit/Write/Glob/Grep only. No Bash, settings/hooks, unrelated formatting, commits, model fallback, secret inspection, paid providers or live generation. 30-minute maximum.

Exclusive write scope: NEW tools/video/multishot.py, NEW tests/contracts/test_multishot_public_tool.py, NEW plan/pending/collap-group/25_H4_PUBLIC_RESULT.md. Another Haiku agent is repairing lib/multishot_session.py and its tests: do NOT edit those files. Read its API; reread before writing wrapper calls if needed. Also read tools/base_tool.py and an existing local tool such as tools/video/video_trimmer.py. Registry discovers concrete BaseTool subclasses automatically; do not change global registry.

Implement class Multishot(BaseTool), name="multishot", beta/experimental as warranted, accurately described capability metadata and schema, offline technical operations. Python does not choose creative decisions or advance stage approvals. Public tool must expose actual available operations, reject unknown inputs safely and return ToolResult with errors for validation failures. Keep tool discovery import free of paid provider calls.

Operations initially required:
- init: validated project_id/title/root directory (test override), canonical init_multishot_project and MultishotSession.initialize(planning_artifacts). Return workspace/session paths, preserve unrelated existing work.
- status: reload session and report current per-shot revision/status without synthetic completion.
- bind_input: explicit shot_id/full prompt/reference metadata; call session.bind_input, return immutable bound input/fingerprint.
- record_result: explicit current revision and technical outcome, delegate strict session validation. Never auto-review or accept.
- review: explicit revision/accepted boolean/planned end state/reviewer/notes, delegate persisted review; no default approval or forged review.
- regenerate: preserve history and revision, return stale IDs from session, not just in-memory metadata.
- invalidate_reference: persist invalidation through session.
- checkpoint: call existing public write_checkpoint with supplied stage/canonical artifact and explicit human_approved. Use real pipeline manifest approval gates; cannot complete gated stage without approval. Validate extra supporting artifacts with the registered multishot schema path, not a test-only helper. If session failure not repaired yet, tests may be blocked, record accurately.

Path security: validate supplied project directory ownership/marker, ensure tool outputs stay inside workspace, reject traversal/symlink escapes using existing helpers. Optional root override needed for tests must not bypass marker checks. Do not accept arbitrary caller-controlled stage policy to skip approval. Read lib/checkpoint.py actual API, not guessed signatures.

Public registry tests should use ToolRegistry.discover("tools.video.multishot") or register_module imported concrete module, registry.get("multishot"), execute through public ToolResult API. Include init/status, invalid artifact and unsafe ID rejection, unknown operation failure, no-approval checkpoint rejection, valid approved checkpoint write/reload, pending/rejected shot cannot complete, and actual persisted review/regen behavior where session supports it. Reuse SCHEMA-VALID fixtures from multishot M1/M5/checkpoint tests; no schema validator monkeypatches, fake approvals, or junk media.

Scheduler/provider lifecycle, cost integration and finalization will be added in a separate H4c invocation after core wrappers pass. Do not declare the whole H4 complete or document unavailable generation operations as implemented. Record real changed files, actual operation schemas, tests NOT run, dependencies and next exact action in 25_H4_PUBLIC_RESULT.md. Never claim supervisor ran tests before it did.
