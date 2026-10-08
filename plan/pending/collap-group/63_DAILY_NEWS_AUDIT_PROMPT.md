# Bounded daily-news audit prompt (after model-route gate)

Read root instructions and 61_DAILY_NEWS_RELEASE_PLAN.md. Work locally; READ-ONLY application source. Write ONLY plan/pending/collap-group/64_DAILY_NEWS_AUDIT_RESULT.md. No Bash, SSH, tests, generation, publication, commits, settings or hook edits. Supervisor handles any approved remote read-only inspection and execution. Cap 25 turns / 15 minutes.

Goal: identify the concrete implementation gaps between the existing daily-news path and release-ready Vietnamese videos, without assuming multishot completion solves the daily pipeline.

Inputs: scripts/run_daily_news_pipeline.sh, scripts/run_strict_docker_publish.sh, deploy/openmontage.cron, tools/news/news_pipeline_cli.py, scripts/validate_render_quality.py, scripts/codex_agent_validation.py, scripts/validate_newsnow_director_artifacts.py; discover applicable news/publishing tests and schemas by targeted searches.

Deliver: actual stage map, model/provider/runtime choices, factual provenance/freshness behavior, retry/idempotency/budget controls, quality rejection paths, failed-project preservation, publishing/cleanup guards, heartbeat/alert behavior and relevant test symbols. Flag unsafe fallbacks, unsupported claims, duplicate publishing risks and source edits by runtime directors. Distinguish code-proven facts, hypotheses and unverified runtime state. Do not print secrets or read credential stores/live publication payloads.

Known observations to verify: daily script deletes failed quality-review project; strict orchestrator has recovery directory handling; cron comments say YouTube-only but include Instagram slot entries. Do not declare a defect merely from comments; trace behavior. Existing test file names are not proof coverage exists.

Output a ranked list of small disjoint implementation tasks with exact files, observable acceptance cases and failure behavior. Use statuses VERIFIED_FROM_SOURCE, NEEDS_TEST, NEEDS_RUNTIME_INSPECTION, APPROVAL_BLOCKED. Do not claim tests/cron/video quality passed. Preserve existing user work.
