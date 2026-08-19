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
TIMEOUT_SECONDS = 120

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
        cmd = [self.cli_path, "--print", "--dangerously-skip-permissions", prompt]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True, stdin=subprocess.DEVNULL
            )
            output = proc.stdout.strip()
            if len(output) > MAX_OUTPUT_CHARS:
                logger.error("CLI output exceeded max size limit.")
                return None

            # Enforce strict raw JSON (do not silently strip markdown)
            if output.startswith("```"):
                logger.error("Unexpected markdown wrapper in JSON output.")
                return None

            return json.loads(output)
        except subprocess.TimeoutExpired as e:
            logger.error(f"CLI timeout. stdout: {e.stdout} stderr: {e.stderr}")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"CLI error: {e.stderr[:200]}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return None
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
        Output ONLY valid JSON, no markdown fencing, no preamble.

        Required structure:
        {{
          "selected_candidate_id": "must belong to candidate_id in inputs",
          "selection_rationale": "reasoning",
          "research_draft": {{
            "landscape": {{
              "existing_content": [
                {{
                  "title": "title string",
                  "url": "canonical_url from candidates",
                  "source": "youtube|blog|tiktok|news",
                  "angle": "narrative approach",
                  "what_it_covers": "summary of coverage"
                }}
              ],
              "saturated_angles": ["string"],
              "underserved_gaps": ["string"]
            }},
            "data_points": [
              {{
                "claim": "specific fact or data point",
                "source_url": "canonical_url from candidates",
                "source_name": "publisher name",
                "credibility": "primary_source|secondary_source|anecdotal"
              }}
            ],
            "audience_insights": {{
              "common_questions": ["string (min 3)"],
              "misconceptions": [
                {{
                  "myth": "common myth",
                  "reality": "actual fact"
                }}
              ],
              "knowledge_level": "beginner|intermediate|advanced"
            }},
            "angles_discovered": [
              {{
                "name": "short angle title",
                "hook": "one-sentence hook",
                "type": "trending|evergreen|contrarian|narrative|data_driven",
                "why_now": "why compelling right now"
              }}
            ],
            "sources": [
              {{
                "url": "canonical_url from candidates",
                "title": "article title",
                "used_for": "section or claim supported"
              }}
            ]
          }}
        }}
        Input candidates:
        {json.dumps(clean_candidates)}"""
