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

## 3. Meta Publisher Token Lifecycle
`TOKEN_FACEBOOK` (Meta Graph API User Access Token) expires or gets revoked periodically. When Instagram/Facebook publish fails with HTTP 400 Bad Request:
- **Root cause is always token expiry**, not code. Renew at [Meta Business Suite > Tools > Tokens](https://business.facebook.com/settings/accountsandusers/tokens-apps).
- The fail-closed preflight in `publish_manual_video.py:_meta_preflight_error_for_platform()` correctly blocks doomed token attempts and records a visible `failed` status without burning API calls.
- **YouTube is never blocked** by Meta token failures — each platform is gated independently.
- The strict workflow no longer requires all projects to publish; partial success (YouTube green) passes the pipeline.

## 4. Claude CLI Review Gate
`scripts/claude_agent_validation.py` parses Claude CLI `--output-format json` output:
- Claude CLI returns a wrapper object `{"is_error": false, "result": <review_json>}` where `result` is a JSON string of the review dict.
- `parse_claude_review()` unwraps nested JSON; `_is_review_dict()` validates required keys `visual_quality`, `audio_sync`, `content_appropriateness`, `brand_compliance`. `overall_passed` is optional — Claude CLI does not always include it.
- Missing CLI, nonzero exit, timeout, malformed JSON, or missing required review sections must produce failed `ValidationResult`s — never substitute `non_interactive_strict_pass`.
