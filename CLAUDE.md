# OpenMontage

Remember: You're an amazing performance engineer, making things lightning fast. But speed without correctness is useless. Measure, optimize, verify.

**MANDATORY: Read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

Additional execution rule below applies alongside `AGENT_GUIDE.md`.

## Local coding; remote execution (required)

Follow the execution-location rule in [`AGENTS.md`](AGENTS.md).

Run Claude CLI or the Claude editor extension **locally** to inspect and edit source in the authorized local workspace or task worktree. Launching a local coding agent is explicitly permitted; it is not a remote-only project command. **Do not launch Claude or any other coding agent over SSH, and do not implement source changes on `sandbox-video`.**

Use `sandbox-video` only for project setup, dependency installation, builds, tests, application execution, servers, renders and other runtime/validation commands. Do not run those workloads locally. Use an isolated remote test checkout/environment, not live production state.

Use this exact SSH prefix:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "<command>"
```

Run commands from the remote project root:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "cd ~/OpenMontage && <command>"
```

Source inspection and editing, including Claude coding-agent work, stay local. Before remote execution, safely synchronize the exact local source revision into the isolated remote checkout without overwriting unrelated work. Review the agent's changes and verify remotely before claiming completion. Older prompts that direct coding agents to the server are superseded by this rule.
