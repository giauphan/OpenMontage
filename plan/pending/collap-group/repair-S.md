# H4 focused repairs

Shared: Claude Haiku 4.5 only. Read AGENT_GUIDE.md and PROJECT_CONTEXT.md. Read/Edit/Write/Glob/Grep only, no shell/permission changes/paid calls/commits. Supervisor runs tests. Do not claim tests ran. 15-minute cap per scope.

## Task S — session initialization lock defect
Exclusive scope lib/multishot_session.py and tests/contracts/test_multishot_session.py, 20_H4_SESSION_RESULT.md.
Supervisor actual tests: 3 session failures, 45 media passes. All session failures are TimeoutError because initialize holds project_lock then calls write_artifact which locks the same project again. _write was fixed but this nested write_artifact lock remains. In initialize, all artifacts are already validated; write them under the SINGLE held lock using write_json_atomic(project_dir / "artifacts" / (name + ".json"), art) which validates record paths and does not relock. Validate artifact names through existing registered names before constructing path; planning_artifacts known fixed keys. Do not add reentrant lock behavior globally or remove locking.
Read current source/tests carefully. After this fix, inspect tests for likely next failures: use actual session revision 1, real expected media hash/report fields, planned end-state EXACTLY supplied fixture, predecessor generated/accepted before binding next. Do not change schema validation or accept fake media. Use actual six-shot Mochi fixtures correctly (all_project_data returns tuple? inspect). Repair genuine source errors but stay focused. Keep negative tests. Report tests unverified and next command.

