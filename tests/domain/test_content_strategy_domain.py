from __future__ import annotations

import pytest

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


def test_context_platform_preferences():
    assert ContextPlatform.LINKEDIN.prefers_weak_hook() is True
    assert ContextPlatform.TECHNICAL_DEEP_DIVE.prefers_weak_hook() is True
    assert ContextPlatform.ENTERPRISE_B2B.prefers_weak_hook() is True
    assert ContextPlatform.ACADEMIC_RESEARCH.prefers_weak_hook() is True
    assert ContextPlatform.COMMUNITY_UPDATE.prefers_weak_hook() is True
    assert ContextPlatform.ENGINEERING_CHANNEL.prefers_weak_hook() is True
    assert ContextPlatform.SHORT_FORM_VIRAL.prefers_weak_hook() is False


def test_hook_spectrum_score_calculation_and_classification():
    # Target sweet spot: 30-50
    target_score = HookSpectrumScore(
        specificity=13.0,
        emotional_trigger=4.0,
        accessibility=3.0,
        payoff_promise=12.0,
    )
    assert target_score.total_score == 32.0
    assert target_score.is_target_weak_hook is True
    assert target_score.classification == HookClassification.HIGH_TRUST_WEAK_HOOK

    # Ineffective weak hook (< 30)
    ineffective_score = HookSpectrumScore(
        specificity=5.0,
        emotional_trigger=2.0,
        accessibility=2.0,
        payoff_promise=5.0,
    )
    assert ineffective_score.total_score == 14.0
    assert ineffective_score.is_target_weak_hook is False
    assert ineffective_score.classification == HookClassification.INEFFECTIVE_WEAK_HOOK

    # Balanced hook (51-75)
    balanced_score = HookSpectrumScore(
        specificity=18.0,
        emotional_trigger=14.0,
        accessibility=15.0,
        payoff_promise=15.0,
    )
    assert balanced_score.total_score == 62.0
    assert balanced_score.is_target_weak_hook is False
    assert balanced_score.classification == HookClassification.BALANCED_HOOK

    # Viral clickbait hook (> 75)
    clickbait_score = HookSpectrumScore(
        specificity=20.0,
        emotional_trigger=25.0,
        accessibility=20.0,
        payoff_promise=22.0,
    )
    assert clickbait_score.total_score == 87.0
    assert clickbait_score.is_target_weak_hook is False
    assert clickbait_score.classification == HookClassification.VIRAL_CLICKBAIT_HOOK


def test_rule_compliance_properties():
    full_compliance = RuleCompliance(
        lead_with_context_not_conflict=True,
        use_neutral_language=True,
        state_the_obvious=True,
        bury_specificity=True,
        no_time_pressure=True,
    )
    assert full_compliance.total_rules_passed == 5
    assert full_compliance.is_fully_compliant is True

    partial_compliance = RuleCompliance(
        lead_with_context_not_conflict=True,
        use_neutral_language=True,
        state_the_obvious=True,
        bury_specificity=True,
        no_time_pressure=False,
    )
    assert partial_compliance.total_rules_passed == 4
    assert partial_compliance.is_fully_compliant is True

    failing_compliance = RuleCompliance(
        lead_with_context_not_conflict=False,
        use_neutral_language=False,
        state_the_obvious=True,
        bury_specificity=False,
        no_time_pressure=True,
    )
    assert failing_compliance.total_rules_passed == 2
    assert failing_compliance.is_fully_compliant is False


def test_skill_signals_counter():
    skills = SkillSignals(
        audience_filtering=True,
        trust_first_opening=True,
        anti_clickbait_signaling=True,
        slow_burn_setup=False,
        insider_language=True,
    )
    assert skills.total_skills_detected == 4


def test_preflight_checklist():
    passed_checklist = PreFlightChecklist(
        content_depth_match=True,
        jargon_justification=True,
        slow_burn_tolerance=True,
        anti_clickbait_alignment=True,
    )
    assert passed_checklist.all_passed is True

    failed_checklist = PreFlightChecklist(
        content_depth_match=True,
        jargon_justification=True,
        slow_burn_tolerance=False,
        anti_clickbait_alignment=True,
    )
    assert failed_checklist.all_passed is False


def test_weak_hook_evaluation_validation():
    with pytest.raises(InvalidHookError):
        WeakHookEvaluation(
            hook_text="   ",
            platform=ContextPlatform.LINKEDIN,
            classification=HookClassification.HIGH_TRUST_WEAK_HOOK,
            spectrum=HookSpectrumScore(12, 5, 4, 12),
            rules=RuleCompliance(True, True, True, True, True),
            skills=SkillSignals(True, True, True, True, True),
            preflight=PreFlightChecklist(True, True, True, True),
            is_approved=True,
            verdict="APPROVED_HIGH_TRUST",
        )
