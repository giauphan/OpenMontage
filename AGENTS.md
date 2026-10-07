# OpenMontage

**MANDATORY: Read `AGENT_GUIDE.md` before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

The production workflow is defined in `AGENT_GUIDE.md`. The execution-location rule below also applies.

## Local coding; remote execution only

- Run Claude CLI, the Claude editor extension, and other coding agents **locally**, in the authorized local workspace or isolated task worktree. Agent launch and source inspection/editing are local development activities, not remote project execution.
- **Never launch a coding agent over SSH or ask an agent on `sandbox-video` to implement or edit source code.** The server is an execution and validation environment, not a coding workstation.
- Run project setup, dependency installation, tests, builds, application commands, servers and renders on `sandbox-video` over SSH, using the project's prescribed SSH configuration and an isolated test checkout/environment. Do not run those workloads locally or against live production state.
- Before remote validation, safely synchronize the exact local source revision under test. Preserve unrelated local and remote changes; do not blindly overwrite either checkout. Synchronization is allowed; remote implementation is not.
- When supervising Claude, prepare the task locally, launch the locally installed Claude with the user-approved model, wait for its result, review the local changes, then synchronize and verify remotely. Do not substitute models or claim completion from the agent's report alone.
- This rule supersedes older task prompts that instruct agents to code on the SSH server. Follow existing worktree/isolation requirements for implementation; documentation-only changes do not require a new worktree.
