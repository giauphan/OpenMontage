"""News selection and research generation using Codex CLI."""
import subprocess  # re-exported so tests can patch lib.claude_news_selector.subprocess.run

from lib.codex_news_selector import CodexNewsSelector
from typing import Any, Dict, List, Optional


class ClaudeNewsSelector(CodexNewsSelector):
    """Backwards-compatible alias for CodexNewsSelector.

    Keeps ``subprocess`` importable at module level so callers and test
    fixtures can patch ``lib.claude_news_selector.subprocess.run`` without
    reaching into the internal ``codex_news_selector`` module.
    """

    def __init__(self, cli_path: str = "codex"):
        super().__init__(cli_path=cli_path)

    # ------------------------------------------------------------------
    # Public alias expected by external callers that pre-date the rename
    # ------------------------------------------------------------------

    def _run_claude(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Execute the CLI and return parsed JSON output.

        Uses a bash ``env -u`` wrapper for non-codex CLIs so that Claude
        Code environment variables are stripped at the shell level without
        manipulating the env dict.  subprocess is accessed through this
        module so test fixtures can patch ``lib.claude_news_selector.subprocess.run``.
        """
        import json
        import re
        from pathlib import Path

        is_codex = "codex" in Path(self.cli_path).name.lower()

        if is_codex:
            cmd = [
                self.cli_path,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                prompt,
            ]
        else:
            # Strip Claude Code session vars at the shell level via env -u.
            strip_vars = " ".join(
                f"-u {v}"
                for v in (
                    "CLAUDECODE",
                    "CLAUDE_CODE_ENTRYPOINT",
                    "CLAUDE_CODE_SSE_PORT",
                    "CLAUDE_SESSION_ID",
                    "ANTHROPIC_MODEL",
                )
            )
            inner = (
                f"{self.cli_path} -p --model claude-opus-4-7"
                f" --dangerously-skip-permissions {prompt}"
            )
            cmd = ["bash", "-c", f"env {strip_vars} {inner}"]

        try:
            from lib.codex_news_selector import TIMEOUT_SECONDS
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            output = proc.stdout.strip() if proc.stdout else ""
            if not output:
                return None
            if "hit your limit" in output.lower():
                return None

            # Parse markdown-wrapped JSON if present.
            if "```" in output:
                match_code = re.search(
                    r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL
                )
                if match_code:
                    output = match_code.group(1)

            idx = output.find("{")
            last_idx = output.rfind("}")
            if idx != -1 and last_idx > idx:
                json_str = output[idx: last_idx + 1]
                json_str = re.sub(r",\s*([\}\]])", r"\1", json_str)
                try:
                    return json.loads(json_str)
                except Exception:
                    pass
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Override: tighten source-URL provenance check
    # ------------------------------------------------------------------

    def _validate_output(
        self,
        data: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Validate selector output and reject foreign source URLs.

        In addition to the base-class checks (candidate ID membership,
        research_draft shape), this override rejects any result whose
        ``research_draft.sources[*].url`` is not anchored in the candidate
        URL set.  A foreign URL indicates the LLM hallucinated a source
        outside the provided candidate pool, which must not pass the gate.
        """
        result = super()._validate_output(data, candidates)
        if result is None:
            return None

        # Build the set of allowed URL prefixes from candidate URLs.
        from urllib.parse import urlparse

        candidate_hosts: set = set()
        for c in candidates:
            url = c.get("canonical_url") or c.get("original_url") or c.get("url") or ""
            if url:
                parsed = urlparse(url)
                candidate_hosts.add(f"{parsed.scheme}://{parsed.netloc}")

        sources = result.get("research_draft", {}).get("sources", [])
        for source in sources:
            src_url = source.get("url", "")
            if not src_url:
                continue
            parsed = urlparse(src_url)
            src_host = f"{parsed.scheme}://{parsed.netloc}"
            if candidate_hosts and src_host not in candidate_hosts:
                return None

        return result
