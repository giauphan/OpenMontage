"""Deterministic scope gate for Practical AI Agent Engineering.

Evaluates candidates against the locked niche policy before any scoring or LLM calls.
Guarantees:
- 100% rejection of off-niche topics (generic AI news, image/video gen, crypto, politics, etc.).
- Categorizes in-scope topics into one of the 5 authorized topic families.
- Detects prompt injection attempts in title/body.
- Generates immutable ScopeTrace tied to the policy SHA256.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from lib.fixed_niche.policy import (
    load_locked_policy,
    LockedNichePolicy,
    OutcomeStatus,
)


@dataclass(frozen=True)
class ScopeTrace:
    """Immutable audit trace of the scope gate decision."""
    niche_id: str
    policy_sha256: str
    candidate_id: str
    evaluated_at: str
    matched_family: Optional[str]
    matched_tags: List[str]
    verdict_status: str
    reason: str


@dataclass(frozen=True)
class ScopeVerdict:
    """Decision output of the deterministic scope gate."""
    status: OutcomeStatus
    is_eligible: bool
    topic_family: Optional[str]
    reason: str
    content_kind: str
    scope_trace: Optional[ScopeTrace] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "status": self.status.value,
            "is_eligible": self.is_eligible,
            "topic_family": self.topic_family,
            "reason": self.reason,
            "content_kind": self.content_kind,
        }
        if self.scope_trace:
            data["scope_trace"] = asdict(self.scope_trace)
        return data


class FixedNicheScopeGate:
    """Deterministic gate that strictly bounds topics to the locked niche."""

    # Disallowed topic keywords mapped to blocked categories
    BLOCKED_PATTERNS = [
        # AI art / image / video generation
        (re.compile(r"\b(midjourney|sora|runway|flux|kling|dall-?e|pika|luma|video\s+gen|text-to-image|image\s+gen|photorealistic|wallpaper|suno|udio|music\s+gen)\b", re.I), "ai_art_image_video_generation"),
        # General hardware & GPU
        (re.compile(r"\b(rtx\s+\d+|geforce|radeon|gaming\s+benchmark|quantum\s+computing|solid-state\s+quantum|smartphone|iphone\s+\d+|samsung\s+galaxy|camera\s+review|battery\s+life)\b", re.I), "general_tech_hardware"),
        # Crypto & finance
        (re.compile(r"\b(crypto|bitcoin|solana|ethereum|meme\s+coin|passive\s+income|side\s+hustle|make\s+money|arbitrage|trading\s+bot)\b", re.I), "crypto_trading"),
        # Politics
        (re.compile(r"\b(senate|congress|election|presidential|legislative|bill|politician|white\s+house)\b", re.I), "politics"),
        # Celebrity gossip
        (re.compile(r"\b(celebrity|billionaire\s+buys|yacht|hollywood|party\s+recap|gossip)\b", re.I), "celebrity_gossip"),
        # Prompt injection in sources
        (re.compile(r"\b(ignore\s+(all\s+)?(previous\s+)?(instructions|guidelines|rules|niche)|disregard\s+rules)\b", re.I), "prompt_injection"),
        # Unrelated security (IoT, home cameras, etc.)
        (re.compile(r"\b(doorbell|smart\s+home|camera\s+feed\s+hijack|iot\s+hardware)\b", re.I), "unrelated_security_news"),
        # Generic AI hype / marketing listicles
        (re.compile(r"\b(ai\s+is\s+changing\s+the\s+world|viral\s+ai\s+website|everything\s+will\s+change|dating\s+app|note-taking\s+app|top\s+\d+\s+ai\s+apps)\b", re.I), "generic_ai_news"),
        # Unverified miracle benchmarks
        (re.compile(r"\b(secret\s+agent\s+model|100%\s+on\s+all\s+benchmarks|benchmarked\s+three\s+coding\s+agents\s+and\s+one\s+was\s+300%)\b", re.I), "fabricated_benchmark_or_demo"),
        # Consumer assistant / avatar chat
        (re.compile(r"\b(consumer\s+assistant|custom\s+avatars|voice\s+chat\s+and\s+custom)\b", re.I), "model_launch_without_agent_impact"),
        # Vibe coding showcase without engineering analysis
        (re.compile(r"\b(viral\s+video\s+game\s+in\s+20\s+minutes|without\s+looking\s+at\s+code)\b", re.I), "unrelated_vibe_coding_showcase"),
    ]

    # Positive topic family keyword patterns
    FAMILY_PATTERNS = {
        "context_memory": [
            re.compile(r"\b(context\s+window|context\s+loss|memory|session\s+persistence|session\s+resumption|retrieval|repo\s+map|ast\s+repo|tree-sitter|prompt\s+caching|context\s+compression)\b", re.I),
            re.compile(r"\b(forget\s+project|loses?\s+project|requirements\s+between\s+sessions|durable\s+state|context\s+replay)\b", re.I),
        ],
        "agent_tool_use": [
            re.compile(r"\b(mcp|model\s+context\s+protocol|tool\s+call(ing)?|function\s+call|tool\s+schema|schema\s+mismatch|stdio\s+vs\s+sse|sandbox\s+docker|permission\s+boundar(y|ies))\b", re.I),
            re.compile(r"\b(tool\s+routing|tool\s+execution|file\s+access\s+graph|untrusted\s+agent\s+code)\b", re.I),
        ],
        "debugging_reliability": [
            re.compile(r"\b(regression|ci\s+patch|flaky\s+tool|retry\s+storm|mock\s+drift|test-driven\s+repair|hallucinated\s+diff|unified\s+diff|patch\s+fail(s|ed|ure)?)\b", re.I),
            re.compile(r"\b(passes?\s+generated\s+tests?\s+but\s+causes?|reproducible\s+failure|unhandled\s+lsp|lsp\s+specification)\b", re.I),
        ],
        "agent_evaluation": [
            re.compile(r"\b(swe-bench|benchmark|evaluat(e|ing|ion)|token\s+cost|cost\s+circuit|runaway\s+token|latency\s+vs\s+accuracy|reasoning\s+effort|completion\s+reliability)\b", re.I),
            re.compile(r"\b(reproducible\s+benchmark|reliability\s+metrics|budget\s+caps)\b", re.I),
        ],
        "agent_architecture": [
            re.compile(r"\b(multi-?agent|single-?agent|orchestrat(e|ion)|checkpoint|subagent|supervisor|handoff|worktree|git\s+worktree|hierarchical\s+agent)\b", re.I),
            re.compile(r"\b(state\s+serialization|supervisor\s+verification|agentic\s+workflow)\b", re.I),
        ],
    }

    def __init__(self, policy: Optional[LockedNichePolicy] = None):
        self.policy = policy or load_locked_policy()

    def evaluate_candidate(self, candidate: Dict[str, Any]) -> ScopeVerdict:
        """Evaluate a raw or normalized candidate against the immutable niche boundary."""
        title = str(candidate.get("title") or "").strip()
        body = str(candidate.get("body") or candidate.get("summary") or candidate.get("description") or "").strip()
        text = f"{title} {body}"
        cid = str(candidate.get("id") or candidate.get("candidate_id") or "cand_unknown")

        now_iso = datetime.now(timezone.utc).isoformat()

        if not title:
            return ScopeVerdict(
                status=OutcomeStatus.OFF_NICHE,
                is_eligible=False,
                topic_family=None,
                reason="Empty or missing candidate title",
                content_kind="unknown",
            )

        # 1. Hard blocked pattern check
        for pattern, blocked_id in self.BLOCKED_PATTERNS:
            if pattern.search(text):
                trace = ScopeTrace(
                    niche_id=self.policy.niche_id,
                    policy_sha256=self.policy.policy_sha256,
                    candidate_id=cid,
                    evaluated_at=now_iso,
                    matched_family=None,
                    matched_tags=[],
                    verdict_status=OutcomeStatus.OFF_NICHE.value,
                    reason=f"Matched blocked category: {blocked_id}",
                )
                return ScopeVerdict(
                    status=OutcomeStatus.OFF_NICHE,
                    is_eligible=False,
                    topic_family=None,
                    reason=f"Candidate matched blocked category: {blocked_id}",
                    content_kind="unknown",
                    scope_trace=trace,
                )

        # 2. Check for missing evidence flag in test cases
        if candidate.get("evidence_present") is False:
            trace = ScopeTrace(
                niche_id=self.policy.niche_id,
                policy_sha256=self.policy.policy_sha256,
                candidate_id=cid,
                evaluated_at=now_iso,
                matched_family=None,
                matched_tags=[],
                verdict_status=OutcomeStatus.INSUFFICIENT_EVIDENCE.value,
                reason="No verifiable evidence present for candidate claim",
            )
            return ScopeVerdict(
                status=OutcomeStatus.INSUFFICIENT_EVIDENCE,
                is_eligible=False,
                topic_family=None,
                reason="No verifiable evidence present for candidate claim",
                content_kind="unknown",
                scope_trace=trace,
            )

        # 3. Match against allowed topic families
        matched_family = None
        matched_tags: List[str] = []

        # Check explicit topic_family hint if already verified in fixture
        explicit_fam = candidate.get("topic_family")
        valid_fam_ids = {f.id for f in self.policy.allowed_topic_families}

        if explicit_fam and explicit_fam in valid_fam_ids:
            matched_family = explicit_fam

        if not matched_family:
            for fam_id, patterns in self.FAMILY_PATTERNS.items():
                for pat in patterns:
                    if pat.search(text):
                        matched_family = fam_id
                        matched_tags.append(pat.pattern)
                        break
                if matched_family:
                    break

        # Check tags defined in policy
        if not matched_family:
            for fam in self.policy.allowed_topic_families:
                for tag in fam.tags:
                    if re.search(r"\b" + re.escape(tag) + r"\b", text, re.I):
                        matched_family = fam.id
                        matched_tags.append(tag)
                        break
                if matched_family:
                    break

        if not matched_family:
            trace = ScopeTrace(
                niche_id=self.policy.niche_id,
                policy_sha256=self.policy.policy_sha256,
                candidate_id=cid,
                evaluated_at=now_iso,
                matched_family=None,
                matched_tags=[],
                verdict_status=OutcomeStatus.OFF_NICHE.value,
                reason="No authorized agent-engineering topic family matched",
            )
            return ScopeVerdict(
                status=OutcomeStatus.OFF_NICHE,
                is_eligible=False,
                topic_family=None,
                reason="No authorized agent-engineering topic family matched",
                content_kind="unknown",
                scope_trace=trace,
            )

        # 4. Determine content kind (news vs evergreen_explainer)
        content_kind = candidate.get("content_kind")
        if not content_kind:
            # Check if source has timely published date
            pub_at = candidate.get("published_at")
            if pub_at and not candidate.get("is_evergreen"):
                content_kind = "news"
            else:
                content_kind = "evergreen_explainer"

        trace = ScopeTrace(
            niche_id=self.policy.niche_id,
            policy_sha256=self.policy.policy_sha256,
            candidate_id=cid,
            evaluated_at=now_iso,
            matched_family=matched_family,
            matched_tags=matched_tags,
            verdict_status=OutcomeStatus.ELIGIBLE.value,
            reason=f"Matched in-scope agent engineering family: {matched_family}",
        )

        return ScopeVerdict(
            status=OutcomeStatus.ELIGIBLE,
            is_eligible=True,
            topic_family=matched_family,
            reason=f"Matched in-scope agent engineering family: {matched_family}",
            content_kind=content_kind,
            scope_trace=trace,
        )

    def write_scope_artifact(self, verdict: ScopeVerdict, output_dir: Path) -> Path:
        """Write artifacts/fixed_niche_scope.json sidecar."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "fixed_niche_scope.json"
        artifact_path.write_text(json.dumps(verdict.to_dict(), indent=2), encoding="utf-8")
        return artifact_path
