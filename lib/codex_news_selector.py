"""Bounded LLM selection and research generation using the Codex CLI."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10
MAX_BODY_CHARS = 2000
MAX_PROMPT_CHARS = 50000
MAX_OUTPUT_CHARS = 100000
TIMEOUT_SECONDS = 300


def resolve_codex_bin() -> str:
    candidates = [
        shutil.which("codex"),
        "/usr/local/bin/codex",
        "/usr/bin/codex",
        "/home/node/.npm-global/bin/codex",
    ]
    for cand in candidates:
        if cand and os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


class CodexNewsSelector:
    """Executes Codex CLI to perform semantic selection and research extraction."""

    def __init__(
        self,
        cli_path: str = "codex",
        *,
        transport: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    ):
        resolved = resolve_codex_bin()
        self.cli_path = resolved if resolved else cli_path
        # Explicit Python dependency injection for isolated rehearsals/tests;
        # normal production construction continues to use subprocess.run.
        self._transport = transport

    def select_and_research(self, top_candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Select best candidate and get raw research brief JSON."""
        if not top_candidates:
            return None
        if len(top_candidates) > MAX_CANDIDATES:
            top_candidates = top_candidates[:MAX_CANDIDATES]

        prompt = self._build_prompt(top_candidates)
        if len(prompt) > MAX_PROMPT_CHARS:
            logger.error("Prompt exceeded max payload size.")
            return None

        result = self._run_codex(prompt)
        if result is None:
            # Fallback to algorithmic selection if CLI execution returns None
            result = self._fallback_selection(top_candidates)

        if result is None:
            return None

        return self._validate_output(result, top_candidates)

    def _fallback_selection(self, top_candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Algorithmic fallback selector when LLM CLI is unavailable or rate-limited."""
        if not top_candidates:
            return None
        sorted_cands = sorted(top_candidates, key=lambda c: c.get("score", 0), reverse=True)
        best = sorted_cands[0]
        cid = best.get("id") or best.get("candidate_id") or "cand_0"
        title = best.get("title", "AI Technology News")
        summary = next((
            value.strip() for value in (
                best.get("summary"), best.get("description"), best.get("content")
            ) if isinstance(value, str) and value.strip()
        ), "")
        source_url = best.get("canonical_url") or best.get("url")
        sources = [{
            "url": source_url,
            "title": title,
            "used_for": "Candidate source; not independently researched",
        }] if source_url else []

        # The fallback has only the candidate title/summary. Never manufacture
        # additional claims, endorsements, misconceptions, or source URLs.
        data_points = []
        if summary and source_url:
            data_points.append({
                "claim": summary,
                "source_url": source_url,
                "credibility": "anecdotal",
            })

        return {
            "selected_candidate_id": cid,
            "research_status": "incomplete",
            "research_draft": {
                "landscape": {
                    "existing_content": [],
                    "saturated_angles": [],
                    "underserved_gaps": [],
                },
                "data_points": data_points,
                "audience_insights": {
                    "common_questions": [],
                    "misconceptions": [],
                    "knowledge_level": "",
                },
                "angles_discovered": [],
                "sources": sources,
            },
        }

    def _run_codex(self, prompt: str) -> Optional[Dict[str, Any]]:
        env = os.environ.copy()
        if "CODEX_HOME" not in env:
            try:
                from scripts.codex_agent_validation import resolve_and_validate_codex_home
                env["CODEX_HOME"] = resolve_and_validate_codex_home(env)
            except Exception:
                pass

        is_codex = "codex" in Path(self.cli_path).name.lower()
        if is_codex:
            codex_cmd = [
                self.cli_path,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
            ]
            model = env.get("CODEX_MODEL", "model-medium-hight")
            codex_cmd.extend(["--config", f'model="{model}"'])
            codex_cmd.append(prompt)
        else:
            for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "CLAUDE_SESSION_ID", "ANTHROPIC_MODEL"):
                env.pop(var, None)
            codex_cmd = [
                self.cli_path,
                "-p",
                "--model",
                "claude-opus-4-7",
                "--dangerously-skip-permissions",
                prompt,
            ]

        try:
            run_transport = self._transport or subprocess.run
            proc = run_transport(
                codex_cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                stdin=subprocess.DEVNULL,
                env=env,
            )
            output = proc.stdout.strip()
            if proc.returncode != 0 or not output or "hit your limit" in output.lower():
                return None

            extracted = self._extract_selection_payload(output)
            if extracted is not None:
                return extracted
        except Exception as e:
            logger.warning("Codex CLI execution failed (%s)", e)

        return None

    def _extract_selection_payload(self, output: str) -> Optional[Dict[str, Any]]:
        for value in self._json_values(output):
            found = self._pick_selection_payload(value)
            if found is not None:
                return found
        return None

    def _pick_selection_payload(self, value: Any) -> Optional[Dict[str, Any]]:
        if isinstance(value, dict):
            if "selected_candidate_id" in value and "research_draft" in value:
                return value
            for key in ("result", "message", "text", "content"):
                nested = value.get(key)
                if isinstance(nested, str):
                    found = self._extract_selection_payload(nested)
                    if found is not None:
                        return found
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    found = self._pick_selection_payload(nested)
                    if found is not None:
                        return found
        elif isinstance(value, list):
            for item in value:
                found = self._pick_selection_payload(item)
                if found is not None:
                    return found
        return None

    def _json_values(self, text: str) -> List[Any]:
        decoder = json.JSONDecoder()
        values: List[Any] = []
        idx = 0
        length = len(text)
        while idx < length:
            start = -1
            for i in range(idx, length):
                if text[i] in "{[":
                    start = i
                    break
            if start < 0:
                break
            try:
                value, end = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                idx = start + 1
                continue
            values.append(value)
            idx = end
        return values

    def _build_prompt(self, candidates: List[Dict[str, Any]]) -> str:
        prompt = (
            "You are an expert news editor and researcher for an automated short-form video channel. "
            "Select the single most impactful, engaging, and high-quality tech/AI story from the list below. "
            "Based on the selected candidate story and your knowledge of the technology landscape, synthesize an accurate, realistic, and comprehensive research draft for the video.\n\n"
            "Return strict JSON matching:\n"
            "{\n"
            '  "selected_candidate_id": "<id>",\n'
            '  "selection_rationale": "...",\n'
            '  "vietnamese_topic": "Tiêu đề tiếng Việt chuẩn xác cho video (ví dụ: Bản cập nhật Ubuntu 26.10 mới nhất)",\n'
            '  "research_draft": {\n'
            '    "landscape": {\n'
            '      "existing_content": [\n'
            '        {"title": "...", "source": "...", "angle": "...", "what_it_covers": "..."}\n'
            '      ],\n'
            '      "saturated_angles": ["..."],\n'
            '      "underserved_gaps": ["..."]\n'
            '    },\n'
            '    "data_points": [\n'
            '      {"claim": "...", "source_url": "https://...", "credibility": "primary_source|secondary_source|anecdotal"}\n'
            '    ],\n'
            '    "audience_insights": {\n'
            '      "common_questions": ["..."],\n'
            '      "misconceptions": [{"myth": "...", "reality": "..."}],\n'
            '      "knowledge_level": "beginner|intermediate|advanced"\n'
            '    },\n'
            '    "angles_discovered": [\n'
            '      {"name": "...", "hook": "...", "type": "trending|educational|comparison|explainer", "why_now": "..."}\n'
            '    ],\n'
            '    "sources": [\n'
            '      {"url": "https://...", "title": "...", "used_for": "..."}\n'
            '    ]\n'
            "  }\n"
            "}\n\n"
            "Requirements: provide at least 3 existing_content entries, 3 data_points, 3 common_questions, "
            "1 misconception with reality, 3 angles_discovered, and 5 distinct sources with URLs.\n\n"
            "Candidates:\n"
        )
        for i, cand in enumerate(candidates):
            cid = cand.get("id") or cand.get("candidate_id") or f"c_{i}"
            title = cand.get("title", "Untitled")
            body = (cand.get("summary") or cand.get("description") or cand.get("content") or "")[:MAX_BODY_CHARS]
            url = cand.get("canonical_url") or cand.get("url") or ""
            publisher = cand.get("publisher") or cand.get("source") or cand.get("source_name") or ""
            prompt += f"ID: {cid}\nTitle: {title}\nSource: {publisher}\nURL: {url}\nSummary: {body}\n---\n"
        return prompt

    def _validate_output(self, data: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        sel_id = data.get("selected_candidate_id")
        valid_ids = {c.get("id") or c.get("candidate_id") for c in candidates}
        if sel_id not in valid_ids and valid_ids:
            # Fallback to first valid candidate id if hallucinated
            data["selected_candidate_id"] = next(iter(valid_ids))
        if not isinstance(data.get("research_draft"), dict):
            return None
        return data
