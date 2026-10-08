# Blocking model-identity mismatch

Plan incomplete. Do not resume coding via current CLI route until exact approved model is verified.

Supervisor always passed --model claude-haiku-4-5-20251001. Initialization and result modelUsage reported that model, but inspection of assistant.message.model contradicts them: regeneration repair/public finalization/durable helper/public finalization tests report gpt-5.6-luna; generation safety/public generate/E2E/docs audit report gemini-3.5-flash-lite. Latest E2E repair also reports gemini-3.5-flash-lite, made no edit attempts, and timed out. This metadata does not establish actual Haiku execution. Prior supervisor statements that the model was confirmed based solely on init/result metadata were too strong. All current-round uncommitted implementation must be treated as model-provenance-unverified. Preserve it; do not silently delete or present it as Haiku-authored.

Latest actual remote tests: tests/contracts -k multishot: 346 passed, 2 failed in 73.44s. Both parameterized E2E cases fail planning continuity_state schema (missing accepted_end_state_fingerprint). Supervisor source review also found invalid invented asset_manifest/edit_decisions fixtures, nonexistent asset paths and missing explicit finalize profile in E2E test. These need actual approved-model repair.

Existing code progress is local and uncommitted: generation preflight/execution/cost handling, public generate/finalization, session regeneration metadata, tests, partial pipeline docs. It was synchronized to isolated remote test checkout only. Stable checkout and cron unchanged, no live paid generation. No supervised agent remains running.

Next: diagnose approved CLI/provider routing without exposing secrets or changing settings without permission; require assistant-event model identity consistent with requested Haiku 4.5 before accepting coding. Then repair E2E fixtures, finish cost-ledger consistency guards and documentation/evidence audit, rerun full suite. Latest docs audit reached turn cap and produced only partial edits; do not count complete.
