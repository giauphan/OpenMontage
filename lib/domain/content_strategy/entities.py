from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Tuple

from lib.domain.content_strategy.exceptions import InvalidHookError


class ContextPlatform(str, Enum):
    """Publishing context and distribution channel."""
    LINKEDIN = "linkedin"
    TECHNICAL_DEEP_DIVE = "technical_deep_dive"
    ENTERPRISE_B2B = "enterprise_b2b"
    ACADEMIC_RESEARCH = "academic_research"
    COMMUNITY_UPDATE = "community_update"
    SHORT_FORM_VIRAL = "short_form_viral"
    ENGINEERING_CHANNEL = "engineering_channel"

    def prefers_weak_hook(self) -> bool:
        """True if the platform's professional audience values high trust over clickbait."""
        return self in {
            ContextPlatform.LINKEDIN,
            ContextPlatform.TECHNICAL_DEEP_DIVE,
            ContextPlatform.ENTERPRISE_B2B,
            ContextPlatform.ACADEMIC_RESEARCH,
            ContextPlatform.COMMUNITY_UPDATE,
            ContextPlatform.ENGINEERING_CHANNEL,
        }


class HookClassification(str, Enum):
    """Categorization along the hook spectrum."""
    HIGH_TRUST_WEAK_HOOK = "high_trust_weak_hook"      # Target spectrum: 30-50
    BALANCED_HOOK = "balanced_hook"                    # Target spectrum: 51-70
    VIRAL_CLICKBAIT_HOOK = "viral_clickbait_hook"      # Target spectrum: 71-100
    INEFFECTIVE_WEAK_HOOK = "ineffective_weak_hook"    # Target spectrum: 0-29


@dataclass(frozen=True)
class RuleCompliance:
    """Evaluates adherence to the 5 Core Weak Hook Rules."""
    lead_with_context_not_conflict: bool  # Rule 1: Setup/background instead of aggressive conflict
    use_neutral_language: bool           # Rule 2: Absence of fear/pain/shock triggers
    state_the_obvious: bool               # Rule 3: Confirms known facts rather than sensational surprises
    bury_specificity: bool                # Rule 4: High-level concept here, details deferred to body
    no_time_pressure: bool                # Rule 5: Zero FOMO, urgency, or countdowns

    @property
    def total_rules_passed(self) -> int:
        return sum(
            1
            for passed in (
                self.lead_with_context_not_conflict,
                self.use_neutral_language,
                self.state_the_obvious,
                self.bury_specificity,
                self.no_time_pressure,
            )
            if passed
        )

    @property
    def is_fully_compliant(self) -> bool:
        return self.total_rules_passed >= 4


@dataclass(frozen=True)
class SkillSignals:
    """Detects active techniques from the 5 Weak Hook Skills."""
    audience_filtering: bool       # Skill 1: Niche jargon, filters out casual scrollers
    trust_first_opening: bool      # Skill 2: Credential or humble framing over shock
    anti_clickbait_signaling: bool # Skill 3: Qualified claims, acknowledges limitations
    slow_burn_setup: bool          # Skill 4: Extended 10-15s setup, delayed punchline
    insider_language: bool         # Skill 5: Peer-to-peer assumption of domain knowledge

    @property
    def total_skills_detected(self) -> int:
        return sum(
            1
            for active in (
                self.audience_filtering,
                self.trust_first_opening,
                self.anti_clickbait_signaling,
                self.slow_burn_setup,
                self.insider_language,
            )
            if active
        )


@dataclass(frozen=True)
class HookSpectrumScore:
    """Quantifies hook strength on a 0-100 spectrum."""
    specificity: float          # 0-25: High-quality weak hook targets 11-15 (deferred)
    emotional_trigger: float    # 0-25: High-quality weak hook targets 0-10 (neutral)
    accessibility: float        # 0-25: High-quality weak hook targets 0-5 (high jargon barrier)
    payoff_promise: float       # 0-25: High-quality weak hook targets 11-15 (qualified)
    total_score: float = field(init=False)

    def __post_init__(self) -> None:
        total = self.specificity + self.emotional_trigger + self.accessibility + self.payoff_promise
        bounded = max(0.0, min(100.0, round(total, 1)))
        object.__setattr__(self, "total_score", bounded)

    @property
    def is_target_weak_hook(self) -> bool:
        """High-trust weak hook spectrum target is strictly between 30 and 50."""
        return 30.0 <= self.total_score <= 50.0

    @property
    def classification(self) -> HookClassification:
        if self.total_score < 30.0:
            return HookClassification.INEFFECTIVE_WEAK_HOOK
        if self.total_score <= 50.0:
            return HookClassification.HIGH_TRUST_WEAK_HOOK
        if self.total_score <= 70.0:
            return HookClassification.BALANCED_HOOK
        return HookClassification.VIRAL_CLICKBAIT_HOOK


@dataclass(frozen=True)
class PreFlightChecklist:
    """Tier 3 pre-production quality gate."""
    content_depth_match: bool       # Video body matches technical depth hinted in hook
    jargon_justification: bool      # Jargon serves semantic clarity, not empty buzzwords
    slow_burn_tolerance: bool       # Target format has time cushion for unhurried pacing
    anti_clickbait_alignment: bool  # Video actually delivers on qualified promises

    @property
    def all_passed(self) -> bool:
        return (
            self.content_depth_match
            and self.jargon_justification
            and self.slow_burn_tolerance
            and self.anti_clickbait_alignment
        )


@dataclass(frozen=True)
class WeakHookEvaluation:
    """Aggregate result from the 3-Tier Pre-Production Validation Framework."""
    hook_text: str
    platform: ContextPlatform
    classification: HookClassification
    spectrum: HookSpectrumScore
    rules: RuleCompliance
    skills: SkillSignals
    preflight: PreFlightChecklist
    is_approved: bool
    verdict: str
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    recommendations: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.hook_text or not self.hook_text.strip():
            raise InvalidHookError("Hook text cannot be empty or whitespace.")
