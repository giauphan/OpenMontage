Requirement / recovery ID: TASK-038 (H4a Persisted Session)
Status and dependency: verified
Expected behavior: The workflow needs a pure persistence/coordination class that tracks planning inputs, revision history, and explicit state machinery for accepted continuity across dependencies, protecting stale edits and unchanged regenerations.
Observed failure / root cause: The project used inline python dict mutation and `read_json_atomic` scattering, with no centralized class enforcing state rules across dependencies (revisions, continuity chaining, bounding).
Code revision and working-diff identity: Added `lib/multishot_session.py` and `tests/contracts/test_multishot_session.py` with tests enforcing state rules.
Environment / dependency versions: None required beyond local Pytest framework.
Regression command, exit code and sanitized log path: `PYTHONPATH=. pytest tests/contracts/test_multishot_session.py`
Repair attempts and changed paths: `lib/multishot_session.py`, `tests/contracts/test_multishot_session.py`
Integration command, exit code and output evidence: `PYTHONPATH=. pytest tests/contracts/test_multishot_session.py` exists with `Exit code 0`.
Skipped checks and why: N/A, tests pass locally.
Reviewer / review findings: System logic conforms to H4a expectations in prompt: validates identities, structure, deep paths.
Remaining blocker and exact next action: Session persistence and boundary tracking established for scheduling tasks. Now clear to progress to H4b scheduling and E2E tools testing.

## Public Method Signatures for BaseTool Use

`class MultishotSession`
- `__init__(self, project_dir: Path)`
- `initialize(self, planning_artifacts: Dict[str, Any]) -> None`
- `get_state(self) -> dict`
- `bind_input(self, shot_id: str, prompt: str, references: list) -> dict`
- `record_result(self, shot_id: str, revision: int, outcome: dict) -> dict`
- `review_shot(self, shot_id: str, revision: int, accepted: bool, end_state: dict, reviewer: str, notes: str) -> dict`
- `regenerate_shot(self, shot_id: str, end_state: dict = None) -> list`
- `invalidate_reference(self, reference_key: str) -> list`