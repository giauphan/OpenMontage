# Codex Agents Stability Rules

## 1. Headless Pipeline Agents (Director)
Codex agents operating within the automated pipeline (e.g., `run_daily_news_pipeline.sh`) run via `codex exec --dangerously-bypass-approvals-and-sandbox --json`.
To ensure stable activation and execution:
- **No Background Processes:** Headless agents must not start background shell commands. All JSON/HTML artifacts must be written synchronously in a single turn.
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

## 4. Codex CLI Review Gate
`scripts/codex_agent_validation.py` performs strict quality validation:
- Validates required criteria: `visual_quality`, `audio_sync`, `content_appropriateness`, `brand_compliance`.
- Uses autonomous fallback when Codex CLI is unavailable (rate-limited or offline).
- Missing CLI, nonzero exit, timeout, malformed JSON, or missing required review sections must produce failed `ValidationResult`s — never substitute `non_interactive_strict_pass`.

## 5. Outcome-Focused Plans and Independent Investigation

Plans are problem-solving contracts, not implementation scripts. Keep them concise and specify:
- **Problem and goal:** What is wrong and what observable outcome resolves it.
- **Inputs:** Relevant artifacts, interfaces, environment, evidence, and known unknowns. Separate verified facts from assumptions.
- **Expected outputs:** Required behavior, deliverables, and failure behavior.
- **Constraints and scope:** Compatibility, security, data preservation, and actions requiring explicit approval.
- **Acceptance criteria:** How to verify the goal, including relevant failure cases and deployment evidence when applicable.

Do not over-prescribe algorithms, code structure, exact edits, or long command sequences. Include implementation detail only when it is necessary to explain a verified defect, an interface contract, or a non-negotiable constraint. Label suggested solutions as hypotheses, not mandatory recipes.

The implementing agent must independently search and inspect the current codebase, check applicable documentation, reproduce or isolate the problem, and validate the plan's assumptions before choosing a solution. Do not blindly translate a plan into code. Adapt the approach when new evidence warrants it, recording the reason; obtain approval before changing the goal, scope, provider, or other protected decisions.

Continue investigating, implementing, and testing within the authorized scope until the acceptance criteria are met or a concrete blocker requires user input. A successful patch or passing narrow test suite alone does not establish completion. If criteria remain unmet or unverified, report the evidence and remaining work rather than marking the plan completed. A plan itself does not authorize deployment, paid calls, publishing, or deletion.

Review feedback should identify the observed failure, evidence, expected outcome, and acceptance gap without prescribing unnecessary implementation details.

## 6. Isolated Implementation Worktrees

- For authorized implementation tasks, create or reuse a dedicated Git worktree on a task-specific branch. Do not implement directly on `main` or in the live deployment checkout. This is the user's standing instruction to create the necessary isolated task branch/worktree; it does not authorize implementation merely because a plan exists.
- Before editing, inspect the worktree status, identify and report the base revision, branch and worktree path, and check for concurrent work. Never reset, overwrite, stash or move unrelated user changes to make room. Bring any required uncommitted plan or task inputs into the worktree explicitly without removing the originals; do not assume Git worktree creation includes them.
- Keep edits and tests tied to the same isolated revision. Follow the project's SSH execution rules: use an isolated server worktree and test environment, not the production `/app` mount. Ensure tests cannot mutate live queues, credentials, publication records or media. Git isolation alone does not isolate shared runtime state.
- Independent agents must use separate worktrees/branches or explicitly disjoint write scopes; never make concurrent changes to the same files without coordination.
- Report results and remaining blockers against the task branch. Commit, push, merge, deploy, or remove the worktree/branch only when requested or explicitly authorized. Preserve unfinished work and do not clean it up merely to report a clean checkout.
- Read-only reviews and documentation-only requests do not require creating a worktree unless the user asks.

## 7. Local Coding Agents; Remote Validation Only

Follow `AGENTS.md`'s execution-location rule: launch Claude CLI/editor coding agents locally and make source changes in the local task worktree. Never launch coding agents over SSH or implement source changes on `sandbox-video`. Synchronize the exact local revision safely, then use the isolated server checkout only for setup, execution, tests, builds and renders. This supersedes older prompts directing coding work to the server.
