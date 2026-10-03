"""Bounded LLM selection and research generation using the Claude CLI.

Backwards-compatible alias of :class:`CodexNewsSelector` that restores the
Claude CLI invocation contract the NewsNow pipeline tests rely on. The CLI
invocation deliberately does NOT pass the approvals-off bypass flag.
"""
import json
import logging
import os
import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from lib.codex_news_selector import TIMEOUT_SECONDS, CodexNewsSelector

logger = logging.getLogger(__name__)

_HARNESS_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_SESSION_ID",
    "ANTHROPIC_MODEL",
)


class ClaudeNewsSelector(CodexNewsSelector):
    """Claude CLI variant of :class:`CodexNewsSelector` (backward-compatible)."""

    def __init__(self, cli_path: str = "claude"):
        # Keep the caller-provided CLI path verbatim so the alias is
        # host-independent and the Claude CLI contract is testable.
        self.cli_path = cli_path

    def _run_claude(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Run the Claude CLI and parse JSON from its (possibly markdown-wrapped) stdout."""
        env = os.environ.copy()
        for var in _HARNESS_VARS:
            env.pop(var, None)

        scrub = " ".join(f"-u {var}" for var in _HARNESS_VARS)
        inner = (
            f"env {scrub} {self.cli_path} -p --model claude-opus-4-7 "
            f"{shlex.quote(prompt)}"
        )
        if os.geteuid() == 0:
            cmd = ["su", "node", "-s", "/bin/bash", "-c", inner]
        else:
            cmd = ["bash", "-c", inner]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Claude CLI execution failed (%s)", exc)
            return None

        output = proc.stdout.strip()
        if not output:
            return None

        fenced = re.search(r"```[a-zA-Z]*\s*(\{.*\})\s*```", output, re.DOTALL)
        if fenced:
            output = fenced.group(1)

        idx = output.find("{")
        last = output.rfind("}")
        if idx != -1 and last > idx:
            try:
                return json.loads(output[idx : last + 1])
            except Exception:
                pass
        try:
            return json.loads(output)
        except Exception:
            return None

    def _validate_output(self, data, candidates):
        result = super()._validate_output(data, candidates)
        if result is None:
            return None
        draft = result.get("research_draft") or {}
        valid_urls = set()
        for cand in candidates:
            for key in ("canonical_url", "original_url"):
                url = cand.get(key)
                if url:
                    valid_urls.add(url)
        if not valid_urls:
            return result
        for source in draft.get("sources") or []:
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            if url and url not in valid_urls:
                logger.warning("Rejecting selection: foreign research source URL %s", url)
                return None
        return result