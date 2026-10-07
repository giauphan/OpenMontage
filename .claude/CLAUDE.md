# OpenMontage — Vietnamese Video Pipeline

Remember: You're an amazing performance engineer, making things lightning fast. But speed without correctness is useless. Measure, optimize, verify.

**MANDATORY: Read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

Additional execution rule below applies alongside `AGENT_GUIDE.md`.

## Local coding; remote execution (required)

Follow the repository-root `AGENTS.md` execution-location rule. Run Claude CLI/editor coding agents locally in the authorized task worktree. Do not launch coding agents over SSH or implement source changes on `sandbox-video`.

Run project setup, dependency installation, builds, tests, application commands, servers and renders on `sandbox-video` over SSH, in an isolated test checkout/environment. Local coding-agent launches and source inspection/editing are permitted; local runtime workloads are not.

Use this exact SSH prefix:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "<command>"
```

Run commands from the isolated remote task checkout, not the existing stable checkout. The SSH command structure is:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "cd <isolated-remote-checkout> && <command>"
```

Safely synchronize the exact local source revision to the isolated remote checkout before validation. Preserve unrelated work and never overwrite the stable server checkout. Older prompts directing coding agents to the server are superseded by this rule.