from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from lib.application.content_strategy.ports import HookEvaluatorPort
from lib.domain.content_strategy.entities import (
    ContextPlatform,
    HookSpectrumScore,
    PreFlightChecklist,
    RuleCompliance,
    SkillSignals,
)


_SENSATIONAL_METRIC_RE = re.compile(r"\b\d+%\b|\b\d+x\b|\bcuts?\b(?:\s+[\w-]+){0,6}?\s+by\s+\d+\b")
_AGGRESSIVE_CONFLICT_RE = re.compile(
    r"^(?:why\s+your|the\s+reason\s+your|your)\s+[^.!?\n]{0,40}?\b(is\s+(?:\w+\s+)?breaking|breaks|fails|is\s+broken|is\s+ruined|destroys)\b"
)


class DeterministicHookEvaluator(HookEvaluatorPort):
    """Deterministic, rule-based evaluator implementing HookEvaluatorPort.
    
    Zero external network calls or non-deterministic LLM hallucinations;
    evaluates lexical features, syntactic markers, and semantic indicators.
    """

    # Jargon markers that filter casual viewers and signal peer-to-peer expertise
    INSIDER_JARGON: Set[str] = {
        "vector database", "vector search", "hybrid search", "embedding",
        "embeddings", "rlhf", "constitutional ai", "context collapse",
        "context window", "schema", "invariants", "ast", "reproducible",
        "reproducibility", "eval matrix", "subagent", "mcp", "tool call",
        "tool calling", "session persistence", "serialization", "graph traversal",
        "entity resolution", "retrieval", "rag", "fine-tuning", "hallucination",
        "multi-turn", "token budget", "latency", "deterministic", "checkpoint",
        "immutability", "concurrency", "prompt caching", "type system",
        "architecture", "memory pattern", "state machine", "reproduction test",
    }

    # High-intensity emotional trigger words associated with clickbait
    EMOTIONAL_TRIGGERS: Set[str] = {
        "wrong", "disaster", "nightmare", "ruining", "insane", "crazy",
        "shocking", "horrible", "stupid", "worst", "secret", "mind-blowing",
        "unbelievable", "urgent", "terrifying", "warning", "catastrophe",
    }

    # Urgent or time-pressure expressions
    URGENCY_TRIGGERS: Set[str] = {
        "stop", "immediately", "now", "hurry", "before it's too late",
        "before your next deploy", "don't wait", "last chance", "urgent",
    }

    # Context / background opening phrases
    CONTEXT_STARTERS: List[str] = [
        "in the last", "over the past", "for teams running", "when building",
        "as systems scale", "here is how", "in production", "after years",
        "across real deployments", "if you've been working with", "when you have time",
    ]

    # Humble / experience-based / trust-first openings
    TRUST_FIRST_MARKERS: List[str] = [
        "after years", "what we learned", "what i learned", "here is what breaks",
        "in production", "here's how", "hard way", "experience shows",
        "a common pattern", "when you have time",
    ]

    # Anti-clickbait / qualifying markers
    QUALIFYING_MARKERS: List[str] = [
        "might help", "one approach", "trade-off", "tradeoffs", "not a silver bullet",
        "consider", "depending on", "interesting approach", "explore", "check out",
    ]

    def evaluate_spectrum(self, text: str) -> HookSpectrumScore:
        clean = text.strip()
        lower = clean.lower()

        # 1. Specificity (0-25)
        # Scroll-stopping clickbait dumps sensational metrics ("cuts by 60%", "40% in 3 turns", "10x") -> High specificity (20-25)
        # High-trust weak hook buries exact metrics, focusing on conceptual mechanisms -> Target 11-15
        # Ineffective weak hook is completely empty / devoid of concepts -> Low specificity (0-8)
        has_sensational_metric = bool(_SENSATIONAL_METRIC_RE.search(lower))
        has_jargon_concept = any(j in lower for j in self.INSIDER_JARGON)

        if has_sensational_metric:
            specificity = 22.0  # Clickbait metric dump upfront
        elif has_jargon_concept or any(w in lower for w in ("agent", "memory", "pipeline", "model", "system")):
            specificity = 13.0  # Ideal target (buried specificity, conceptual)
        else:
            specificity = 6.0   # Generic / empty

        # 2. Emotional Trigger (0-25)
        # Clickbait uses fear, alarm, urgency -> High trigger (20-25)
        # Mild architectural tension ("silently breaks", "fails", "drops") -> 10-12
        # High-trust weak hook maintains neutral tone -> Target 5-10
        found_emotional = [word for word in self.EMOTIONAL_TRIGGERS if re.search(rf"\b{word}\b", lower)]
        found_urgency = [word for word in self.URGENCY_TRIGGERS if re.search(rf"\b{word}\b", lower)]

        if (found_emotional and found_urgency) or len(found_emotional) >= 2:
            emotional_trigger = 24.0
        elif found_emotional or found_urgency:
            emotional_trigger = 18.0
        elif any(tension in lower for tension in ("silently breaks", "breaks", "fails", "loses", "reset")):
            emotional_trigger = 10.0
        elif "!" in clean or "?" in clean:
            emotional_trigger = 9.0
        else:
            emotional_trigger = 6.0  # Clean neutral tone

        # 3. Accessibility / Casual Appeal (0-25)
        # Reverse of barrier: High-trust weak hook has HIGH technical barrier (low accessibility: 0-6)
        # Casual viral hook is accessible to anyone -> High accessibility (18-25)
        jargon_count = sum(1 for j in self.INSIDER_JARGON if j in lower)
        if jargon_count >= 2:
            accessibility = 4.0   # Strong audience filter
        elif jargon_count == 1:
            accessibility = 6.0   # Solid peer filter
        elif any(term in lower for term in ("agent", "model", "database", "code", "pipeline", "api")):
            accessibility = 12.0
        else:
            accessibility = 20.0  # Mass market / broad layman appeal

        # 4. Payoff Promise / Hype (0-25)
        # Clickbait overblown promises ("secret", "10x", "never again", "fix forever") -> High hype (20-25)
        # High-trust weak hook qualifies claims and under-promises -> Target 11-15
        # Ineffective weak hook has zero payoff or direction -> 0-8
        has_hype_promise = any(h in lower for h in ("secret", "10x", "never again", "fix forever", "best way"))
        has_qualifier = any(q in lower for q in self.QUALIFYING_MARKERS)

        if has_hype_promise:
            payoff_promise = 23.0  # Overblown promise
        elif has_qualifier or any(starter in lower for starter in ("here is how", "let me show you", "what we learned", "became standard", "check out", "our approach")):
            payoff_promise = 13.0  # Qualified, humble promise (ideal target)
        elif "how" in lower or "why" in lower or "architecture" in lower:
            payoff_promise = 12.0
        else:
            payoff_promise = 5.0   # Vague / missing payoff

        return HookSpectrumScore(
            specificity=specificity,
            emotional_trigger=emotional_trigger,
            accessibility=accessibility,
            payoff_promise=payoff_promise,
        )

    def evaluate_rules(self, text: str) -> RuleCompliance:
        lower = text.strip().lower()

        # Rule 1: Lead with context, not conflict
        has_context_starter = any(lower.startswith(cs) for cs in self.CONTEXT_STARTERS)
        has_aggressive_conflict = bool(_AGGRESSIVE_CONFLICT_RE.search(lower))
        lead_with_context = (has_context_starter or not has_aggressive_conflict) and not lower.startswith("stop ")

        # Rule 2: Neutral language
        has_emotional = any(re.search(rf"\b{word}\b", lower) for word in self.EMOTIONAL_TRIGGERS)
        use_neutral = not has_emotional

        # Rule 3: State the obvious (confirm known reality, no surprise ambush)
        no_sensational_surprise = not any(w in lower for w in ("what everyone gets wrong", "you won't believe", "shocking truth"))
        state_obvious = no_sensational_surprise

        # Rule 4: Bury specificity (no percentages or benchmark numbers dumped in first sentence)
        no_raw_benchmark_dump = not bool(_SENSATIONAL_METRIC_RE.search(lower))
        bury_spec = no_raw_benchmark_dump

        # Rule 5: No time pressure (no FOMO or artificial urgency)
        no_time_pressure = not any(re.search(rf"\b{urg}\b", lower) for urg in self.URGENCY_TRIGGERS)

        return RuleCompliance(
            lead_with_context_not_conflict=lead_with_context,
            use_neutral_language=use_neutral,
            state_the_obvious=state_obvious,
            bury_specificity=bury_spec,
            no_time_pressure=no_time_pressure,
        )

    def detect_skills(self, text: str) -> SkillSignals:
        lower = text.strip().lower()

        # Skill 1: Audience filtering (unexplained jargon)
        jargon_matches = sum(1 for j in self.INSIDER_JARGON if j in lower)
        audience_filtering = jargon_matches >= 1

        # Skill 2: Trust-first opening (credentials or humble framing)
        trust_first = any(m in lower for m in self.TRUST_FIRST_MARKERS) or bool(
            re.search(r"\b(years|months|production|deployments|in practice)\b", lower)
        )

        # Skill 3: Anti-clickbait signaling (qualified claims, humble boundaries)
        anti_clickbait = any(q in lower for q in self.QUALIFYING_MARKERS) or "not a " in lower

        # Skill 4: Slow burn setup (multi-clause, setup framing)
        slow_burn = any(p in lower for p in ("here is how", "why", "let me show you")) or ";" in text or "—" in text or " - " in text or "." in text[:-1]

        # Skill 5: Insider language (peer assumption, no 101 definitions)
        insider = jargon_matches >= 1 or any(
            p in lower for p in ("you know how", "standard approach", "subagent", "invariants", "mcp")
        )

        return SkillSignals(
            audience_filtering=audience_filtering,
            trust_first_opening=trust_first,
            anti_clickbait_signaling=anti_clickbait,
            slow_burn_setup=slow_burn,
            insider_language=insider,
        )

    def check_preflight(
        self,
        text: str,
        platform: ContextPlatform,
        body_summary: Optional[str] = None,
    ) -> PreFlightChecklist:
        lower = text.strip().lower()

        # Depth match: if hook mentions technical mechanisms, body should not contradict
        content_depth_match = True
        if body_summary:
            body_lower = body_summary.lower()
            jargon_in_hook = [j for j in self.INSIDER_JARGON if j in lower]
            if jargon_in_hook and not any(j in body_lower for j in jargon_in_hook):
                content_depth_match = False

        # Jargon justification: jargon must fit real concepts, not buzzword fluff
        jargon_justified = sum(1 for j in self.INSIDER_JARGON if j in lower) <= 5

        # Slow burn tolerance: platform or length allows time for unhurried delivery
        slow_burn_tolerated = platform.prefers_weak_hook()

        # Anti-clickbait alignment: hook does not overpromise compared to sober delivery
        anti_clickbait_aligned = not any(
            h in lower for h in ("secret", "10x", "never again", "fix forever")
        )

        return PreFlightChecklist(
            content_depth_match=content_depth_match,
            jargon_justification=jargon_justified,
            slow_burn_tolerance=slow_burn_tolerated,
            anti_clickbait_alignment=anti_clickbait_aligned,
        )
