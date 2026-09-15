# Claude Agents Stability Rules

## 1. Headless Pipeline Agents (Director)
Claude agents operating within the automated pipeline (e.g., `run_daily_news_pipeline.sh`) run in **headless mode** (`claude --bare -p`). 
To ensure stable activation and execution:
- **No Background Processes:** Headless agents must not use `TaskCreate`, `TodoWrite`, `Agent`, or start background shell commands. All JSON/HTML artifacts must be written synchronously in a single turn using `Write`, `Edit`, or `Bash`.
- **Strict Schema Injection:** Prompts MUST explicitly include exact JSON schemas (e.g., `{"version":"1.0", "title": "...", "total_duration_seconds": 120, "sections": [...]}`). Do not rely on external schema files being discovered.
- **GSAP Guidelines:** Always use standard exact initialization for timeline. Use `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>`, no vendored GSAP. Use `let` instead of `const` for dynamic variables to prevent Chromium JS executor crashes.
- **Fail-safe Auto-Normalization:** In `scripts/validate_newsnow_director_artifacts.py`, auto-patch minor schema mistakes (e.g., convert `scenes` to `sections`) before giving up.
- **Quality Verification:** Any generated composition must endure verification thresholds: > 30s runtime, > 0.5% edge-density, no freeze-canvas, etc.

## 2. Agent Interactive Publishing Workflow Validation
When fixing the daily pipeline, verify the full stage progression completely manually or via monitoring:
1. Re-run `run_strict_docker_publish.sh`
2. Pass `preflight` -> `prepare` -> `today-batch`
3. Check `STAGE 3: generate` completion (`artifacts/script_vi.json` and renders validated).
4. Verify `STAGE 6: queue-next-day` populates `config/publish_schedule.json`.
5. Confirm `STAGE 6.5: platform-schedule` and `STAGE 8: final-state` execute, successfully triggering `publish_active_projects.py` to social platforms.
