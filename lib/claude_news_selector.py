"""Bounded LLM selection and research generation using the Claude CLI."""

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10
MAX_BODY_CHARS = 2000
MAX_PROMPT_CHARS = 50000
MAX_OUTPUT_CHARS = 100000
TIMEOUT_SECONDS = 300

class ClaudeNewsSelector:
    """Executes Claude CLI to perform semantic selection and research extraction."""

    def __init__(self, cli_path: str = "claude"):
        self.cli_path = cli_path

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

        result = self._run_claude(prompt)
        if result is None:
            return None

        return self._validate_output(result, top_candidates)

    def _run_claude(self, prompt: str) -> Optional[Dict[str, Any]]:
        import os, shlex, re
        model = "model-medium-hight"
        env = os.environ.copy()
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
        env["ANTHROPIC_DEFAULT_FABLE_MODEL"] = model
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = model
        claude_cmd = " ".join(
            [
                f"ANTHROPIC_DEFAULT_OPUS_MODEL={shlex.quote(model)}",
                f"ANTHROPIC_DEFAULT_SONNET_MODEL={shlex.quote(model)}",
                f"ANTHROPIC_DEFAULT_FABLE_MODEL={shlex.quote(model)}",
                f"ANTHROPIC_DEFAULT_HAIKU_MODEL={shlex.quote(model)}",
                "claude",
                "-p",
                shlex.quote(prompt),
                "--model",
                shlex.quote(model),
            ]
        )
        if os.geteuid() == 0:
            cmd = ["su", "node", "-s", "/bin/bash", "-c", claude_cmd]
        else:
            cmd = ["bash", "-c", claude_cmd]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True, stdin=subprocess.DEVNULL, env=env
            )
            output = proc.stdout.strip()
            if "```" in output:
                match_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL)
                if match_code:
                    output = match_code.group(1)
            idx = output.find("{")
            last_idx = output.rfind("}")
            if idx != -1 and last_idx > idx:
                json_str = output[idx:last_idx+1]
                json_str = re.sub(r",\s*([\}\]])", r"", json_str)
                try:
                    return json.loads(json_str)
                except Exception:
                    pass
                try:
                    obj, _ = json.JSONDecoder().raw_decode(json_str)
                    return obj
                except Exception as ex:
                    logger.warning(f"raw_decode failed: {ex}")
            return json.loads(output)
        except subprocess.TimeoutExpired as e:
            logger.error(f"CLI timeout. stdout: {e.stdout} stderr: {e.stderr}")
        except subprocess.CalledProcessError as e:
            logger.error(f"CLI error: {e.stderr[:200]}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in _run_claude: {e}")
        return None

    def _validate_output(self, parsed: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        required = ["selected_candidate_id", "selection_rationale", "research_draft"]
        if not all(k in parsed for k in required):
            logger.error("Missing required output fields.")
            return None

        valid_ids = {c["candidate_id"] for c in candidates}
        if parsed["selected_candidate_id"] not in valid_ids:
            logger.error(f"Illicit selected_candidate_id: {parsed['selected_candidate_id']}")
            return None

        valid_urls = {c["canonical_url"] for c in candidates if c.get("canonical_url")}
        valid_urls.update({c["original_url"] for c in candidates if c.get("original_url")})

        draft = parsed["research_draft"]
        for k in ["landscape", "data_points", "audience_insights", "angles_discovered", "sources"]:
            if k not in draft:
                logger.error(f"Missing research_draft field: {k}")
                return None

        # Validate all evidence URLs strictly belong to candidates.
        evidence_urls = []
        evidence_urls.extend(
            item.get("url") for item in draft.get("sources", []) if isinstance(item, dict)
        )
        evidence_urls.extend(
            item.get("source_url") for item in draft.get("data_points", []) if isinstance(item, dict)
        )
        landscape = draft.get("landscape", {})
        evidence_urls.extend(
            item.get("url")
            for item in landscape.get("existing_content", [])
            if isinstance(item, dict) and item.get("url") is not None
        )
        for url in evidence_urls:
            if url not in valid_urls:
                logger.error(f"Illicit evidence URL: {url}")
                return None

        return parsed

    def _build_prompt(self, candidates: List[Dict[str, Any]]) -> str:
        clean_candidates = []
        for c in candidates:
            clean_candidates.append({
                "candidate_id": c["candidate_id"],
                "title": c["title"],
                "publisher": c["publisher"],
                "canonical_url": c["canonical_url"],
                "published_at_utc": c["published_at_utc"],
                "body": c.get("body", "")[:MAX_BODY_CHARS],
                "score": c.get("scoring", {}).get("total_score", 0)
            })
        return f"""You are a senior news producer for OpenMontage. Select the best candidate for short-form video.
Output ONLY valid JSON object. No markdown, no preamble, no commentary.

Requirements for research_draft:
- existing_content: Array of 3 items minimum
- data_points: Array of 3 items minimum
- common_questions: Array of 3 items minimum
- angles_discovered: Array of 3 items minimum
- sources: Array of items using canonical_url from input candidates

JSON Schema:
{{
  "selected_candidate_id": "candidate_id matching input",
  "selection_rationale": "brief reasoning",
  "research_draft": {{
    "landscape": {{
      "existing_content": [
        {{
          "title": "string",
          "url": "canonical_url from candidates",
          "source": "youtube|blog|tiktok|news",
          "angle": "string",
          "what_it_covers": "string"
        }},
        {{
          "title": "string 2",
          "url": "canonical_url from candidates",
          "source": "news",
          "angle": "string",
          "what_it_covers": "string"
        }},
        {{
          "title": "string 3",
          "url": "canonical_url from candidates",
          "source": "blog",
          "angle": "string",
          "what_it_covers": "string"
        }}
      ],
      "saturated_angles": ["string"],
      "underserved_gaps": ["string"]
    }},
    "data_points": [
      {{
        "claim": "fact 1",
        "source_url": "canonical_url from candidates",
        "source_name": "publisher name",
        "credibility": "primary_source|secondary_source|anecdotal"
      }},
      {{
        "claim": "fact 2",
        "source_url": "canonical_url from candidates",
        "source_name": "publisher name",
        "credibility": "primary_source|secondary_source|anecdotal"
      }},
      {{
        "claim": "fact 3",
        "source_url": "canonical_url from candidates",
        "source_name": "publisher name",
        "credibility": "primary_source|secondary_source|anecdotal"
      }}
    ],
    "audience_insights": {{
      "common_questions": ["question 1", "question 2", "question 3"],
      "misconceptions": [
        {{
          "myth": "string",
          "reality": "string"
        }}
      ],
      "knowledge_level": "intermediate"
    }},
    "angles_discovered": [
      {{
        "name": "angle 1",
        "hook": "one sentence hook",
        "type": "trending",
        "why_now": "string"
      }},
      {{
        "name": "angle 2",
        "hook": "one sentence hook",
        "type": "data_driven",
        "why_now": "string"
      }},
      {{
        "name": "angle 3",
        "hook": "one sentence hook",
        "type": "contrarian",
        "why_now": "string"
      }}
    ],
    "sources": [
      {{
        "url": "canonical_url from candidates",
        "title": "article title",
        "used_for": "claim 1"
      }}
    ]
  }}
}}

Input candidates:
{json.dumps(clean_candidates)}"""
