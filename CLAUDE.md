# OpenMontage

**MANDATORY: Read [`AGENT_GUIDE.md`](AGENT_GUIDE.md) before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

Additional execution rule below applies alongside `AGENT_GUIDE.md`.

## Remote execution (required)

Run every project environment, setup, dependency-install, build, test, server, render, and other project command on `sandbox-video` over SSH. Do not run project commands on the local machine.

Use this exact SSH prefix:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "<command>"
```

Run commands from the remote project root:

```bash
ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video "cd ~/OpenMontage && <command>"
```

Use local filesystem tools only for reading and editing source files. When a command needs newly edited source, ensure the remote checkout contains those changes before running it.
