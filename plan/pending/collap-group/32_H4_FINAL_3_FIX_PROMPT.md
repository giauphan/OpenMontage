# Fix current 3 focused H4 failures only

Use claude-haiku-4-5-20251001 only. Read AGENT_GUIDE.md first. Read/Edit/Write/Glob/Grep only. No shell, no commits, no settings/hooks, no paid calls. Supervisor runs tests. 15-minute cap. Write ONLY:
- tests/contracts/test_multishot_public_tool.py
- tests/contracts/test_multishot_session.py
- tests/contracts/test_multishot_session_integrity.py
- lib/multishot_session.py only if needed for retry semantics, not for bad fixtures

Actual focused run: 3 failed, 7 passed.

1) test_multishot_public_tool.py line 90 still hits prerequisite violation for story because idea checkpoint was not actually created before bad story. Fix test by using multishot tool checkpoint operation to complete idea first using valid idea artifacts from actual schema. Read existing BRIEF/request fixture in file or import from test_multishot_checkpoint_recovery. Assert idea checkpoint success before testing bad story. Then bad story at real stage story should fail artifact validation. Do NOT accept prerequisite error as success.

2) test_multishot_session.py line 88 still mutates new_end_state["clothing_state"]. Actual shot end_state schema has character/environment/props only. Change to valid mutation: new_end_state["character"] = new_end_state["character"] + " with apron stained". Assert stale list includes both downstream shots if fixture has 3+ shots, in plan order. Do not invent clothing_state.

3) test_multishot_session_integrity.py tries record_result after FAILED, but source intentionally rejects status FAILED. Required retry flow: after FAILED, call bind_input again with the exact same prompt/references to transition FAILED back to BOUND without changing revision/input hash, preserving failure history. If current lib/multishot_session.bind_input does not allow identical FAILED retry, minimally implement that: identical frozen input on status FAILED -> append prior failure to history if needed, clear error/generated fields, set status BOUND, return same binding; changed input on FAILED remains rejected. Then record_result can complete. Update test to use exact same prompt/references before replacement completed result. Keep negative for changed retry input.

Do not touch production validation or continuity prompt changes. Do not claim tests ran. Report exact edits only in existing H4 result if touched.
