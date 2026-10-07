# Fix the one current H4 public tool failure

Use claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md first. Read/Edit/Write/Glob/Grep only. No shell, no commits, no settings/hooks, no paid calls. Supervisor runs tests. 10-minute cap.

Write ONLY tests/contracts/test_multishot_public_tool.py unless you discover the tool is definitely wrong.

Actual focused run: 1 failed, 9 passed. Failure is test_multishot_tool_public_api line 90. The test first sends an invalid idea checkpoint with artifacts {"bad": {}} and then expects artifact validation wording. Actual error is correct and stricter: "Stage 'idea' with status 'completed' must include canonical artifact 'brief'". This is not wrong behavior. Fix the test semantics.

Required test flow:
1. Unknown operation, init, status remain.
2. Complete a valid idea checkpoint FIRST using BRIEF and REQUEST and assert success.
3. Then test invalid story artifact at stage "story" with idea prerequisite satisfied; expect artifact validation/unknown artifact/invalid artifact wording.
4. Then test unapproved valid story gate rejection, then approved valid story success/readback.

Remove the initial invalid idea artifact expectation entirely; it is testing canonical artifact presence, not the intended invalid story artifact validation. Do not make story assertion accept prerequisite/canonical-brief failures. Do not call init a second time on same project. Keep path/security and unknown operation tests. Do not claim tests ran.
