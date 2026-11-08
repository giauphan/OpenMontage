from __future__ import annotations

from typing import List, Optional, Sequence

from lib.application.content_strategy.ports import HookGeneratorPort
from lib.domain.content_strategy.entities import ContextPlatform


class TemplateWeakHookGenerator(HookGeneratorPort):
    """Generates high-trust weak hook variations based on the 5 Rules and 5 Skills."""

    def generate_variations(
        self,
        topic: str,
        platform: ContextPlatform = ContextPlatform.ENGINEERING_CHANNEL,
        context_notes: Optional[str] = None,
        count: int = 3,
    ) -> Sequence[str]:
        clean_topic = topic.strip().rstrip(".") if topic else "autonomous agent systems"

        variations: List[str] = [
            # Pattern 1: Context-First + Neutral Language (Rule 1 & Rule 2)
            f"In recent production deployments, {clean_topic} became standard. Here is how underlying architectures handle edge cases.",
            # Pattern 2: Trust-First + Humble Framing (Skill 2 & Skill 3)
            f"After building production agent pipelines, here is what we learned the hard way about {clean_topic}.",
            # Pattern 3: State the Obvious + Insider Jargon (Rule 3 & Skill 1 & Skill 5)
            f"Coding agents require reliable session invariants. Here is an interesting approach to {clean_topic} without context collapse.",
            # Pattern 4: Slow Burn Setup (Skill 4 & Rule 4)
            f"Why do multi-turn workflows fail with {clean_topic}? Most teams blame prompt phrasing, but the architectural root cause is untyped handoffs.",
            # Pattern 5: Qualified Anti-Clickbait + No Urgency (Rule 5 & Skill 3)
            f"When you have time to audit your architecture, here is one approach to {clean_topic} that might help prevent silent regressions.",
        ]

        if platform == ContextPlatform.LINKEDIN:
            # Add LinkedIn-specific peer variation
            variations.insert(
                0,
                f"For engineering teams running autonomous coding agents: here is an architectural breakdown of {clean_topic}.",
            )

        return tuple(variations[:count])
