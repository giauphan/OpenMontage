# H4 focused repairs

Shared: Claude Haiku 4.5 only. Read AGENT_GUIDE.md and PROJECT_CONTEXT.md. Read/Edit/Write/Glob/Grep only, no shell/permission changes/paid calls/commits. Supervisor runs tests. Do not claim tests ran. 15-minute cap per scope.

## Task P — public test imports and API defects
Exclusive scope tools/video/multishot.py and tests/contracts/test_multishot_public_tool.py, 25_H4_PUBLIC_RESULT.md.
Actual collection failure: cannot import multishot_session_fixture, SCHEMA_VALID_PLANNING, SCHEMA_VALID_RESULT from tests.contracts.conftest. These symbols do NOT exist. Read actual existing test_multishot_session.py and tests/fixtures/multishot_mochi.py (find actual path), reuse real all_project_data fixture and local real-video helper as appropriate. Define fixtures locally in public-tool test; do not modify conftest or invent imports.
Check every tool helper signature against lib/multishot_session.py and lib/checkpoint.py current API (session task concurrently repairs initialization, no signature changes intended). Public checkpoint must use real write_checkpoint approval gates. Keep tests real, no injected pass validation or direct dict status mutation to fabricate accepted states. Implement init/status/schema/path/unknown-operation/checkpoint tests first. Review/regen tests can be added later but do not document them verified before actual running. Preserve canonical BaseTool/ToolResult discovery compatibility.
