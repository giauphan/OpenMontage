# OpenMontage — Vietnamese Video Pipeline

Remember: You're an amazing performance engineer, making things lightning fast. But speed without correctness is useless. Measure, optimize, verify.

**MANDATORY: Read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

Additional execution rule below applies alongside `AGENT_GUIDE.md`.

## Local coding; remote execution only (required)

Follow the binding execution-location rules in the repository-root `AGENTS.md`.

Run Claude CLI/editor coding agents and author all source changes **locally**, in the authorized local workspace or task worktree. Never launch a coding agent over SSH or patch source on `sandbox-video`, including through shell commands or scripts. A failure found remotely must be fixed locally.

Use `sandbox-video` only for controlled synchronization of locally authored code, setup, dependency installation, pipeline execution, builds, tests, servers, renders, and read-only runtime inspection. Verify the synchronized revision or file hashes before execution. Pipeline-generated artifacts, media, logs, and runtime state may be written remotely. Do not run project runtime workloads locally.

Use this exact SSH prefix:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "<command>"
```

Use an isolated remote checkout for validation, not the stable server checkout. Announce the action and target checkout before SSH commands. Synchronization is delivery of local changes, never permission for remote implementation. Do not update stable deployment or activate cron without explicit authorization. Older prompts directing coding agents to the server are superseded by this rule.