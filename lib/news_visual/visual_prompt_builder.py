"""Prompt builder for vivid, intuitive conceptual AI illustrations in Practical AI Agent Engineering."""
from __future__ import annotations

import re


class VisualPromptBuilder:
    """Constructs disciplined, claim-aware prompts producing vivid, intuitive visual metaphors."""

    STYLE_PREFIX: str = "Conceptual illustration of "

    SAFETY_NEGATIVE_CONSTRAINTS: str = (
        "Pure cinematic visual art only. Absolutely no text, no words, no letters, "
        "no labels, no bullet points, no flowcharts, no infographic posters, no user interface."
    )

    METAPHOR_MAP: dict[str, dict[str, str]] = {
        "context_memory": {
            "loss": (
                "an AI robot with fading memories, glowing digital particles, minimalist visual metaphor, dark background"
            ),
            "storage": (
                "an AI glowing digital brain crystalizing into a durable steel storage vault, glowing cybernetic circuits, neon cyan and gold particles, dark sci-fi background, cinematic concept art, high contrast"
            ),
        },
        "agent_tool_use": {
            "loss": (
                "an AI robot struggling with disconnected floating broken digital puzzle blocks and severed laser beams in dark space, dramatic lighting"
            ),
            "storage": (
                "glowing mechanical golden gears and luminous fiber-optic connectors slotting perfectly together in mid-air, emitting brilliant energy, futuristic engineering concept"
            ),
        },
        "debugging_reliability": {
            "loss": (
                "a glowing digital crystal monolith fractured by pulsing red stress cracks in a dark void, dramatic shadow, moody lighting"
            ),
            "storage": (
                "a brilliant focused laser beam of pure emerald light repairing and sealing cracks in a luminous digital prism, glowing particles swirling in harmony"
            ),
        },
    }

    @classmethod
    def build_prompt(cls, topic_family: str, visual_intent: str, narration_excerpt: str = "") -> str:
        """Combine style, intuitive visual metaphor, and clean negative constraints."""
        fam_key = topic_family.lower().strip()
        intent_lower = visual_intent.lower()

        is_storage_or_fix = any(k in intent_lower for k in ("storage", "persistence", "durable", "remedy", "fix", "verify", "recovery", "mechanism"))
        sub_key = "storage" if is_storage_or_fix else "loss"

        if fam_key in cls.METAPHOR_MAP:
            metaphor = cls.METAPHOR_MAP[fam_key].get(sub_key, cls.METAPHOR_MAP[fam_key]["loss"])
            return f"{cls.STYLE_PREFIX}{metaphor}. {cls.SAFETY_NEGATIVE_CONSTRAINTS}"

        # Clean text fallback
        clean_intent = re.sub(r"\s+", " ", visual_intent).strip()
        clean_intent = re.sub(r"^(conceptual\s+illustration\s+(depicting|showing|of)?\s*)", "", clean_intent, flags=re.IGNORECASE).strip()
        clean_intent = re.sub(r"^(developer\s+problem(\s+hook)?:\s*)", "", clean_intent, flags=re.IGNORECASE).strip()
        clean_intent = re.sub(r"^(technical\s+diagram\s+(illustrating|showing|depicting)?:\s*)", "", clean_intent, flags=re.IGNORECASE).strip()

        return f"{cls.STYLE_PREFIX}{clean_intent}, glowing futuristic technology, dark cinematic lighting, 8k render. {cls.SAFETY_NEGATIVE_CONSTRAINTS}"
