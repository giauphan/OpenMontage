from __future__ import annotations

from typing import Optional, Protocol, Sequence

from lib.domain.content_strategy.entities import (
    ContextPlatform,
    HookClassification,
    HookSpectrumScore,
    PreFlightChecklist,
    RuleCompliance,
    SkillSignals,
    WeakHookEvaluation,
)


class HookEvaluatorPort(Protocol):
    """Outbound port for evaluating hook text against weak hook quality standards."""

    def evaluate_spectrum(self, text: str) -> HookSpectrumScore:
        """Calculate the 0-100 Hook Strength Spectrum score."""
        ...

    def evaluate_rules(self, text: str) -> RuleCompliance:
        """Check compliance against the 5 Core Weak Hook Rules."""
        ...

    def detect_skills(self, text: str) -> SkillSignals:
        """Identify presence of the 5 Weak Hook Skills."""
        ...

    def check_preflight(
        self,
        text: str,
        platform: ContextPlatform,
        body_summary: Optional[str] = None,
    ) -> PreFlightChecklist:
        """Verify Tier 3 pre-flight production requirements."""
        ...


class HookGeneratorPort(Protocol):
    """Outbound port for synthesizing weak hook variations for engineering and deep-dive contexts."""

    def generate_variations(
        self,
        topic: str,
        platform: ContextPlatform,
        context_notes: Optional[str] = None,
        count: int = 3,
    ) -> Sequence[str]:
        """Generate high-trust weak hook candidates for the given topic and platform."""
        ...
