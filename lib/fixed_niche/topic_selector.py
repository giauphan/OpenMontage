"""Candidate-bound topic selector strictly operating within the locked US niche."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import subprocess

from lib.fixed_niche.policy import load_locked_policy, LockedNichePolicy, OutcomeStatus

logger = logging.getLogger(__name__)


class CandidateBoundSelectionError(ValueError):
    """Raised when the LLM selector hallucinates or returns a candidate outside the authorized pool."""
    pass


class FixedNicheTopicSelector:
    """Selects exactly one verifiable agent engineering topic from an authorized candidate pool."""

    def __init__(
        self,
        policy: Optional[LockedNichePolicy] = None,
        *,
        transport: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    ):
        self.policy = policy or load_locked_policy()
        self._transport = transport
        self.prompt_template_path = Path("scripts/prompts/fixed_us_topic_selection.prompt.md")

    @staticmethod
    def _candidate_id(cand: Dict[str, Any], index: int) -> str:
        cid = cand.get("id") or cand.get("candidate_id")
        return str(cid) if cid is not None else f"cand_{index}"

    def validate_selection(
        self,
        data: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate LLM selection output. Strictly rejects unknown candidate IDs."""
        if not isinstance(data, dict):
            raise CandidateBoundSelectionError(f"Selection output must be a JSON object, got {type(data).__name__}")

        # Check for explicit NO_ELIGIBLE_TOPIC
        if data.get("status") == OutcomeStatus.NO_ELIGIBLE_TOPIC.value:
            return data

        selected_id = data.get("selected_candidate_id")
        if not selected_id:
            raise CandidateBoundSelectionError("Selection output omitted 'selected_candidate_id'")

        valid_ids = {self._candidate_id(c, i) for i, c in enumerate(candidates)}
        if str(selected_id) not in valid_ids:
            # HARD REQUIREMENT: Reject unknown ID; no silent remap!
            raise CandidateBoundSelectionError(
                f"Selected candidate ID {selected_id!r} is outside the allowed candidate pool {sorted(list(valid_ids))}"
            )

        # Enforce constant niche_id
        if data.get("niche_id") and data["niche_id"] != self.policy.niche_id:
            raise CandidateBoundSelectionError(
                f"Selection attempted to alter niche_id from {self.policy.niche_id} to {data.get('niche_id')}"
            )

        return data

    def build_prompt(self, candidates: List[Dict[str, Any]]) -> str:
        """Build US-native prompt with policy SHA and candidate pool."""
        template = ""
        if self.prompt_template_path.is_file():
            template = self.prompt_template_path.read_text(encoding="utf-8")

        prompt = (
            f"{template}\n\n"
            f"Policy ID: {self.policy.niche_id}\n"
            f"Policy SHA256: {self.policy.policy_sha256}\n\n"
            "Authorized In-Scope Candidates:\n"
        )
        for i, cand in enumerate(candidates):
            cid = self._candidate_id(cand, i)
            title = cand.get("title", "Untitled")
            body = cand.get("body") or cand.get("summary") or ""
            url = cand.get("canonical_url") or cand.get("url") or ""
            family = cand.get("topic_family") or "general"
            prompt += (
                f"Candidate ID: {cid}\n"
                f"Topic Family: {family}\n"
                f"Title: {title}\n"
                f"Source URL: {url}\n"
                f"Summary: {body}\n---\n"
            )
        return prompt

    def select_topic(
        self,
        candidate_pool: List[Dict[str, Any]],
        *,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Select a single in-scope candidate. Returns NO_ELIGIBLE_TOPIC if pool is empty."""
        if not candidate_pool:
            return {
                "status": OutcomeStatus.NO_ELIGIBLE_TOPIC.value,
                "niche_id": self.policy.niche_id,
                "policy_sha256": self.policy.policy_sha256,
                "reason": "No in-scope candidates passed the deterministic gate",
                "selected_candidate_id": None,
                "projects_created": 0,
            }

        # If custom transport provided, invoke it
        if self._transport is not None:
            prompt = self.build_prompt(candidate_pool)
            res = self._transport(prompt)
            if res.returncode != 0:
                return {
                    "status": OutcomeStatus.SYSTEM_ERROR.value,
                    "niche_id": self.policy.niche_id,
                    "selected_candidate_id": None,
                    "projects_created": 0,
                    "reason": f"selector transport exit {res.returncode}",
                }
            try:
                parsed = json.loads(res.stdout)
            except json.JSONDecodeError as e:
                raise CandidateBoundSelectionError(f"Selector returned non-JSON output: {e}") from e
            return self.validate_selection(parsed, candidate_pool)

        # Deterministic top-ranked selection when transport not provided or for offline tests
        top_cand = candidate_pool[0]
        cid = self._candidate_id(top_cand, 0)
        return {
            "status": OutcomeStatus.ELIGIBLE.value,
            "selected_candidate_id": cid,
            "niche_id": self.policy.niche_id,
            "policy_sha256": self.policy.policy_sha256,
            "topic_family": top_cand.get("topic_family", "context_memory"),
            "viewer_question": top_cand.get("viewer_question") or f"How to resolve: {top_cand.get('title')}",
            "selection_rationale": "Top ranked in-scope topic with verifiable primary source evidence.",
            "canonical_url": top_cand.get("canonical_url") or top_cand.get("url"),
            "publisher": top_cand.get("publisher", "Official Documentation"),
            "content_kind": top_cand.get("content_kind", "evergreen_explainer"),
            "projects_created": 1,
        }
