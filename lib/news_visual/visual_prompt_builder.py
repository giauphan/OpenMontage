"""Prompt builder for conceptual AI illustrations in Practical AI Agent Engineering."""
from __future__ import annotations

import re


class VisualPromptBuilder:
    """Constructs disciplined, claim-aware prompts for non-proof conceptual beats."""

    STYLE_PREFIX: str = (
        "High-contrast conceptual engineering artwork, technical dark theme (#0b1120 background) "
        "with subtle cyan and amber structural accents. Clean geometric diagrams and visual metaphors: "
    )

    SAFETY_NEGATIVE_CONSTRAINTS: str = (
        "; strictly no UI screenshots, no fake code logs, no fake terminal prompts, "
        "no invented benchmark graphs, no brand logos, no readable fake text, no stock photos."
    )

    @classmethod
    def build_prompt(cls, topic_family: str, visual_intent: str, narration_excerpt: str = "") -> str:
        """Combine style, concept intent, and negative constraints into a safe prompt."""
        # Clean text
        clean_intent = re.sub(r"\s+", " ", visual_intent).strip()
        clean_excerpt = re.sub(r"\s+", " ", narration_excerpt[:100]).strip()

        family_context = {
            "context_memory": "metaphor of session boundary, active working memory vs persistent repository storage",
            "agent_tool_use": "abstract representation of structured tool interfaces, schema boundary contracts, and execution pipelines",
            "debugging_reliability": "conceptual visualization of test regression boundaries, isolated verification cycles, and defect reproduction",
            "agent_evaluation": "symbolic representation of rigorous reliability assertions and evaluation matrix checkpoints",
            "agent_architecture": "clean multi-agent orchestration flows, declarative handoff boundaries, and state transitions",
        }.get(topic_family.lower(), "abstract software engineering architecture and verification boundaries")

        base_prompt = f"{cls.STYLE_PREFIX}{clean_intent}. Visual theme: {family_context}"
        if clean_excerpt:
            base_prompt += f" (Context: {clean_excerpt})"
        base_prompt += cls.SAFETY_NEGATIVE_CONSTRAINTS
        return base_prompt
