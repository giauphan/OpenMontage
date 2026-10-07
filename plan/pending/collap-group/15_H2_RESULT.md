# Task B — H2 strict resume complete & Review Followup

* Updated `JobScheduler._reuse` in `lib/multishot_jobs.py` to actually re-probe/re-decode output media via `self._validate_output(path, spec)` when evaluating an existing successful record. It now requires that the fresh digest explicitly matches the original `content_hash`, exactly once per reuse. 
* Updated `JobScheduler._run_all` external hydration logic so a missing external `input_hash` fails closed immediately with `INVALID_INPUT` without saving a schema-invalid record, instead of blindly inheriting the current spec hash.
* Do not weaken or bypass validation—a forged success report or corrupted bytes will now correctly fail `_reuse` because they fail re-probing.
* Updated regression `test_path_only_external_completion_rejected` in `tests/contracts/test_multishot_resume_integrity.py` to assert `INVALID_INPUT` exactly when missing provenance (no `input_hash`).

Unverified test command:
```bash
pytest tests/contracts/test_multishot_jobs_recovery.py tests/contracts/test_multishot_m2.py tests/contracts/test_multishot_m5.py tests/contracts/test_multishot_resume_integrity.py
```
