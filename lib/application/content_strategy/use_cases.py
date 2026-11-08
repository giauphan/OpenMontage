from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from lib.application.content_strategy.ports import HookEvaluatorPort, HookGeneratorPort
from lib.domain.content_strategy.entities import (
    ContextPlatform,
    HookClassification,
    HookSpectrumScore,
    PreFlightChecklist,
    RuleCompliance,
    SkillSignals,
    WeakHookEvaluation,
)
from lib.domain.content_strategy.exceptions import InvalidHookError


class EvaluateWeakHookUseCase:
    """Orchestrates 3-tier validation for high-trust weak hooks under Clean Architecture."""

    def __init__(self, evaluator: HookEvaluatorPort) -> None:
        self._evaluator = evaluator

    def execute(
        self,
        hook_text: str,
        platform: ContextPlatform = ContextPlatform.ENGINEERING_CHANNEL,
        body_summary: Optional[str] = None,
        enforce_target_spectrum: bool = True,
    ) -> WeakHookEvaluation:
        clean_text = hook_text.strip() if hook_text else ""
        if not clean_text:
            raise InvalidHookError("Cannot evaluate an empty or whitespace hook.")

        # Tier 1: Platform & Context Check
        platform_prefers_weak = platform.prefers_weak_hook()

        # Tier 2: 0-100 Hook Strength Spectrum
        spectrum = self._evaluator.evaluate_spectrum(clean_text)
        rules = self._evaluator.evaluate_rules(clean_text)
        skills = self._evaluator.detect_skills(clean_text)

        # Tier 3: Pre-flight Production Gate
        preflight = self._evaluator.check_preflight(clean_text, platform, body_summary)

        reasons: List[str] = []
        recommendations: List[str] = []

        # Evaluate Approval
        is_target = spectrum.is_target_weak_hook
        classification = spectrum.classification

        if not platform_prefers_weak:
            reasons.append(
                f"Platform '{platform.value}' typically rewards scroll-stopping viral hooks. "
                "Ensure slow-burn retention is intentional."
            )

        if classification == HookClassification.HIGH_TRUST_WEAK_HOOK:
            reasons.append("Optimal high-trust weak hook: filters casual viewers and signals technical authority.")
        elif classification == HookClassification.VIRAL_CLICKBAIT_HOOK:
            reasons.append("High scroll-stopping power with elevated clickbait risk (Score > 75).")
            recommendations.append("Tone down emotional triggers, remove artificial urgency, and lead with context.")
        elif classification == HookClassification.INEFFECTIVE_WEAK_HOOK:
            reasons.append("Ineffective weak hook (Score < 30): lacks audience filtering jargon or clear peer context.")
            recommendations.append("Incorporate insider technical jargon or credential/humble framing to signal authority.")
        else:
            reasons.append("Balanced hook (Score 51-75): moderate engagement with partial filtering.")

        if not rules.is_fully_compliant:
            if not rules.lead_with_context_not_conflict:
                recommendations.append("Rule 1: Open with technical background or setup rather than direct conflict.")
            if not rules.use_neutral_language:
                recommendations.append("Rule 2: Strip sensational or alarmist adjectives in favor of neutral engineering terms.")
            if not rules.state_the_obvious:
                recommendations.append("Rule 3: Frame opening around known operational reality rather than shock reveals.")
            if not rules.bury_specificity:
                recommendations.append("Rule 4: Keep the opening premise high-level and defer exact benchmarks to the body.")
            if not rules.no_time_pressure:
                recommendations.append("Rule 5: Eliminate artificial FOMO, 'now', or urgent imperative commands.")

        if skills.total_skills_detected < 2:
            recommendations.append(
                "Skill boost: Strengthen audience filtering via unprompted domain jargon or trust-first peer framing."
            )

        if not preflight.all_passed:
            if not preflight.content_depth_match:
                recommendations.append("Ensure the upcoming video body delivers the technical depth implied by the hook.")
            if not preflight.anti_clickbait_alignment:
                recommendations.append("Qualify claims to avoid bait-and-switch perception.")

        # Approval logic
        if enforce_target_spectrum:
            is_approved = is_target and rules.is_fully_compliant and preflight.all_passed
        else:
            is_approved = classification in (
                HookClassification.HIGH_TRUST_WEAK_HOOK,
                HookClassification.BALANCED_HOOK,
            ) and preflight.all_passed

        verdict = "APPROVED_HIGH_TRUST" if is_approved else "NEEDS_REVISION"

        return WeakHookEvaluation(
            hook_text=clean_text,
            platform=platform,
            classification=classification,
            spectrum=spectrum,
            rules=rules,
            skills=skills,
            preflight=preflight,
            is_approved=is_approved,
            verdict=verdict,
            reasons=tuple(reasons),
            recommendations=tuple(recommendations),
        )


class GenerateWeakHookUseCase:
    """Generates and filters weak hook variations, returning evaluated high-trust candidates."""

    def __init__(self, generator: HookGeneratorPort, evaluator: HookEvaluatorPort) -> None:
        self._generator = generator
        self._eval_use_case = EvaluateWeakHookUseCase(evaluator)

    def execute(
        self,
        topic: str,
        platform: ContextPlatform = ContextPlatform.ENGINEERING_CHANNEL,
        context_notes: Optional[str] = None,
        count: int = 3,
    ) -> Sequence[WeakHookEvaluation]:
        raw_candidates = self._generator.generate_variations(
            topic=topic,
            platform=platform,
            context_notes=context_notes,
            count=count,
        )

        evaluations: List[WeakHookEvaluation] = []
        for cand in raw_candidates:
            eval_res = self._eval_use_case.execute(
                hook_text=cand,
                platform=platform,
                body_summary=context_notes,
                enforce_target_spectrum=False,
            )
            evaluations.append(eval_res)

        # Sort so that high-trust target hooks (30-50 score) and fully compliant hooks appear first
        evaluations.sort(
            key=lambda e: (
                1 if e.classification == HookClassification.HIGH_TRUST_WEAK_HOOK else 0,
                e.rules.total_rules_passed,
                e.skills.total_skills_detected,
                -abs(e.spectrum.total_score - 40.0),  # Closest to 40 center of target spectrum
            ),
            reverse=True,
        )
        return tuple(evaluations)
