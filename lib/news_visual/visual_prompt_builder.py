"""Prompt builder for conceptual AI illustrations in Practical AI Agent Engineering."""
from __future__ import annotations

import re


class VisualPromptBuilder:
    """Constructs disciplined, claim-aware prompts for non-proof conceptual beats."""

    STYLE_PREFIX: str = "Conceptual illustration of "

    SAFETY_NEGATIVE_CONSTRAINTS: str = (
        "Abstract metaphorical artwork only. No screenshots, no user interface, "
        "no terminal output, no readable code or text, no logos, no charts or benchmarks."
    )

    @classmethod
    def build_prompt(cls, topic_family: str, visual_intent: str, narration_excerpt: str = "") -> str:
        """Combine style, concept intent, and declarative theme into a clean image prompt."""
        # Clean text
        clean_intent = re.sub(r"\s+", " ", visual_intent).strip()
        clean_intent = re.sub(r"^(conceptual\s+illustration\s+(depicting|showing|of)?\s*)", "", clean_intent, flags=re.IGNORECASE).strip()
        clean_intent = re.sub(r"^(developer\s+problem(\s+hook)?:\s*)", "", clean_intent, flags=re.IGNORECASE).strip()
        clean_intent = re.sub(r"^(technical\s+diagram\s+(illustrating|showing|depicting)?:\s*)", "", clean_intent, flags=re.IGNORECASE).strip()

        family_context = {
            "context_memory": "active working memory and persistent repository storage",
            "agent_tool_use": "structured tool interfaces, schema boundary contracts, and execution pipelines",
            "debugging_reliability": "test regression boundaries, isolated verification cycles, and defect reproduction",
            "agent_evaluation": "rigorous reliability assertions and evaluation matrix checkpoints",
            "agent_architecture": "multi-agent orchestration flows, declarative handoff boundaries, and state transitions",
        }.get(topic_family.lower(), "software engineering architecture and verification boundaries")

        return f"{cls.STYLE_PREFIX}{clean_intent}, {family_context}. {cls.SAFETY_NEGATIVE_CONSTRAINTS}"
