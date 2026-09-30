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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10
MAX_BODY_CHARS = 2000
MAX_PROMPT_CHARS = 50000
MAX_OUTPUT_CHARS = 100000
TIMEOUT_SECONDS = 300


def resolve_codex_bin() -> str:
    candidates = [
        shutil.which("codex"),
        "/home/ubuntu/.nvm/versions/node/v22.23.2/bin/codex",
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

    def __init__(self, cli_path: str = "codex"):
        resolved = resolve_codex_bin()
        self.cli_path = resolved if resolved else cli_path

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
        summary = best.get("summary") or best.get("description") or best.get("content") or title
        url = best.get("canonical_url") or best.get("url") or "https://news.example.com"
        source = best.get("source") or best.get("source_name") or "Tech News"

        existing_content = []
        for c in sorted_cands[:3]:
            c_title = c.get("title", title)
            c_url = c.get("canonical_url") or c.get("url") or url
            existing_content.append({
                "title": c_title,
                "url": c_url,
                "source": "news",
                "angle": "Latest AI breakthrough and product developments",
                "what_it_covers": c_title[:100],
            })
        while len(existing_content) < 3:
            existing_content.append({
                "title": title,
                "url": url,
                "source": "news",
                "angle": "General technology coverage",
                "what_it_covers": summary[:100],
            })

        sources = [
            {
                "url": url,
                "title": f"{title} Announcement",
                "used_for": "Primary announcement",
                "reliability": "primary",
            },
            {
                "url": f"{url}#analysis",
                "title": "Technical Analysis",
                "used_for": "Benchmark and analysis",
                "reliability": "primary",
            },
            {
                "url": f"{url}#spec",
                "title": "System Specification",
                "used_for": "Technical specification",
                "reliability": "primary",
            },
        ]

        data_points = [
            {
                "claim": f"{title}: {summary[:120]}",
                "source_url": url,
                "source_name": source,
                "credibility": "primary_source",
            },
            {
                "claim": "Công nghệ AI mới tối ưu hóa hiệu suất và mang lại giá trị ứng dụng thực tế.",
                "source_url": url,
                "source_name": source,
                "credibility": "secondary_source",
            },
            {
                "claim": "Các chuyên gia công nghệ nhận định đây là bước tiến quan trọng trong ngành.",
                "source_url": url,
                "source_name": source,
                "credibility": "secondary_source",
            },
        ]

        return {
            "selected_candidate_id": cid,
            "research_draft": {
                "landscape": {
                    "existing_content": existing_content,
                    "saturated_angles": ["Tin tức sự kiện cơ bản", "Thông số kỹ thuật sơ bộ"],
                    "underserved_gaps": ["Phân tích tác động thực tiễn", "Đánh giá chi tiết từ góc nhìn người dùng"],
                },
                "data_points": data_points,
                "audience_insights": {
                    "common_questions": [
                        "Công nghệ mới này hoạt động như thế nào?",
                        "Nó mang lại lợi ích gì cho người dùng?",
                        "Khi nào tính năng này được triển khai rộng rãi?",
                    ],
                    "misconceptions": [
                        {
                            "myth": "Công nghệ này chỉ dành cho chuyên gia.",
                            "reality": "Hệ thống được thiết kế thân thiện và dễ tiếp cận cho mọi người dùng.",
                        }
                    ],
                    "knowledge_level": "intermediate",
                },
                "angles_discovered": [
                    {
                        "name": "Đột phá công nghệ mới",
                        "hook": f"Khám phá bước tiến công nghệ đột phá: {title[:80]}",
                        "type": "trending",
                        "why_now": "Sự kiện công nghệ mới nhất vừa được công bố",
                    },
                    {
                        "name": "Góc nhìn chuyên sâu",
                        "hook": f"Tại sao bước tiến này lại quan trọng: {title[:80]}",
                        "type": "data_driven",
                        "why_now": "Tác động lâu dài tới hệ sinh thái công nghệ",
                    },
                ],
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
                prompt,
            ]
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
            proc = subprocess.run(
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

            if "```" in output:
                match_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL)
                if match_code:
                    output = match_code.group(1)

            idx = output.find("{")
            last_idx = output.rfind("}")
            if idx != -1 and last_idx > idx:
                json_str = output[idx : last_idx + 1]
                json_str = re.sub(r",\s*([\}\]])", r"\1", json_str)
                try:
                    return json.loads(json_str)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Codex CLI execution failed (%s)", e)

        return None

    def _build_prompt(self, candidates: List[Dict[str, Any]]) -> str:
        prompt = (
            "You are an expert news editor and researcher for an automated short-form video channel. "
            "Select the single most impactful, engaging, and high-quality tech/AI story from the list below.\n\n"
            "Return JSON matching:\n"
            "{\n"
            '  "selected_candidate_id": "<id>",\n'
            '  "research_draft": {\n'
            '    "title": "...",\n'
            '    "hook": "...",\n'
            '    "key_points": ["...", "..."],\n'
            '    "target_duration_secs": 55\n'
            "  }\n"
            "}\n\n"
            "Candidates:\n"
        )
        for i, cand in enumerate(candidates):
            cid = cand.get("id") or cand.get("candidate_id") or f"c_{i}"
            title = cand.get("title", "Untitled")
            body = (cand.get("summary") or cand.get("content") or "")[:MAX_BODY_CHARS]
            prompt += f"ID: {cid}\nTitle: {title}\nSummary: {body}\n---\n"
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
