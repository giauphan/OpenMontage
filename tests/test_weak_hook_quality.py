from __future__ import annotations

import pytest

from lib.adapters.content_strategy import (
    DeterministicHookEvaluator,
    TemplateWeakHookGenerator,
)
from lib.application.content_strategy import (
    EvaluateWeakHookUseCase,
    GenerateWeakHookUseCase,
)
from lib.domain.content_strategy import (
    ContextPlatform,
    HookClassification,
)


@pytest.fixture
def evaluator() -> DeterministicHookEvaluator:
    return DeterministicHookEvaluator()


@pytest.fixture
def generator() -> TemplateWeakHookGenerator:
    return TemplateWeakHookGenerator()


@pytest.fixture
def use_case(evaluator: DeterministicHookEvaluator) -> EvaluateWeakHookUseCase:
    return EvaluateWeakHookUseCase(evaluator)


def test_positive_weak_hook_rule_1_context_not_conflict(use_case: EvaluateWeakHookUseCase):
    """Rule 1: Lead with context/background instead of aggressive conflict."""
    hook = "In the last 6 months, vector databases became standard for agent memory architecture."
    res = use_case.execute(hook, platform=ContextPlatform.TECHNICAL_DEEP_DIVE)

    assert res.rules.lead_with_context_not_conflict is True
    assert res.rules.use_neutral_language is True
    assert res.rules.is_fully_compliant is True
    assert res.spectrum.is_target_weak_hook is True
    assert res.classification == HookClassification.HIGH_TRUST_WEAK_HOOK
    assert res.is_approved is True


def test_positive_weak_hook_rule_2_neutral_language(use_case: EvaluateWeakHookUseCase):
    """Rule 2: Use neutral language without sensational emotional triggers."""
    hook = "Here is how hybrid search works in autonomous agent memory pipelines."
    res = use_case.execute(hook, platform=ContextPlatform.LINKEDIN)

    assert res.rules.use_neutral_language is True
    assert res.spectrum.emotional_trigger <= 10.0
    assert res.classification == HookClassification.HIGH_TRUST_WEAK_HOOK
    assert res.is_approved is True


def test_positive_weak_hook_rule_3_state_the_obvious(use_case: EvaluateWeakHookUseCase):
    """Rule 3: State the obvious; confirm what audience knows instead of surprise ambush."""
    hook = "AI agents need better memory systems across session restarts. Here is our architectural approach."
    res = use_case.execute(hook, platform=ContextPlatform.ENGINEERING_CHANNEL)

    assert res.rules.state_the_obvious is True
    assert res.classification == HookClassification.HIGH_TRUST_WEAK_HOOK
    assert res.is_approved is True


def test_positive_weak_hook_rule_4_bury_specificity(use_case: EvaluateWeakHookUseCase):
    """Rule 4: Keep hook conceptual, saving exact benchmarks and percentages for the body."""
    hook = "Let me show you an interesting approach to agent memory and session persistence."
    res = use_case.execute(hook, platform=ContextPlatform.ACADEMIC_RESEARCH)

    assert res.rules.bury_specificity is True
    assert res.spectrum.specificity >= 11.0
    assert res.is_approved is True


def test_positive_weak_hook_rule_5_no_time_pressure(use_case: EvaluateWeakHookUseCase):
    """Rule 5: No FOMO, urgency, or countdown pressure."""
    hook = "When you have time to audit your architecture, check out this memory pattern."
    res = use_case.execute(hook, platform=ContextPlatform.COMMUNITY_UPDATE)

    assert res.rules.no_time_pressure is True
    assert res.spectrum.emotional_trigger <= 10.0
    assert res.is_approved is True


def test_positive_weak_hook_skills_filter_and_trust(use_case: EvaluateWeakHookUseCase):
    """Skills: Audience filtering (jargon), trust-first opening, anti-clickbait qualification."""
    hook = (
        "After 3 years building production RAG systems, here is what we learned about context collapse. "
        "Not a silver bullet, but this might help if you're struggling with session persistence."
    )
    res = use_case.execute(hook, platform=ContextPlatform.LINKEDIN)

    assert res.skills.audience_filtering is True
    assert res.skills.trust_first_opening is True
    assert res.skills.anti_clickbait_signaling is True
    assert res.skills.total_skills_detected >= 3
    assert res.classification == HookClassification.HIGH_TRUST_WEAK_HOOK
    assert res.is_approved is True


def test_user_canonical_example_vector_search_context_collapse(use_case: EvaluateWeakHookUseCase):
    """Test user's specific canonical example:
    'Pure vector search silently breaks autonomous agent memory during context collapse.'
    """
    hook = "Pure vector search silently breaks autonomous agent memory during context collapse."
    res = use_case.execute(hook, platform=ContextPlatform.TECHNICAL_DEEP_DIVE)

    # Contains insider jargon ('vector search', 'context collapse', 'autonomous agent memory')
    assert res.skills.audience_filtering is True
    assert res.skills.insider_language is True
    # Low accessibility = high technical barrier for casual viewers
    assert res.spectrum.accessibility <= 5.0
    # No urgent countdowns or FOMO
    assert res.rules.no_time_pressure is True
    # Fits into high-trust weak hook spectrum
    assert res.classification == HookClassification.HIGH_TRUST_WEAK_HOOK


def test_negative_clickbait_hook_rejected(use_case: EvaluateWeakHookUseCase):
    """Clickbait hook with high urgency, fear, and sensationalism is blocked from weak hook status."""
    clickbait_hook = (
        "Your vector database is silently breaking your agent! "
        "Stop using pure vector search before your next deploy! Shocking 10x disaster!"
    )
    res = use_case.execute(clickbait_hook, platform=ContextPlatform.LINKEDIN, enforce_target_spectrum=True)

    assert res.classification == HookClassification.VIRAL_CLICKBAIT_HOOK
    assert res.spectrum.total_score > 70.0
    assert res.rules.is_fully_compliant is False
    assert res.rules.lead_with_context_not_conflict is False
    assert res.rules.use_neutral_language is False
    assert res.rules.no_time_pressure is False
    assert res.is_approved is False
    assert res.verdict == "NEEDS_REVISION"
    assert any("Rule 1" in rec for rec in res.recommendations)
    assert any("Rule 5" in rec for rec in res.recommendations)


def test_negative_overblown_benchmark_specificity(use_case: EvaluateWeakHookUseCase):
    """Premature benchmark dump violates Rule 4 (Bury Specificity)."""
    hook = "Robot's 3-layer recall engine cuts hallucinations by 60% after 3 turns! Secret revealed!"
    res = use_case.execute(hook, platform=ContextPlatform.TECHNICAL_DEEP_DIVE)

    assert res.rules.bury_specificity is False
    assert res.rules.use_neutral_language is False
    assert res.classification != HookClassification.HIGH_TRUST_WEAK_HOOK
    assert res.is_approved is False


def test_template_generator_and_orchestration(
    generator: TemplateWeakHookGenerator,
    evaluator: DeterministicHookEvaluator,
):
    """Test generating high-trust weak hook variations and ranking them."""
    gen_use_case = GenerateWeakHookUseCase(generator, evaluator)
    evals = gen_use_case.execute(
        topic="Model Context Protocol schema validation",
        platform=ContextPlatform.ENGINEERING_CHANNEL,
        count=4,
    )

    assert len(evals) == 4
    for ev in evals:
        # Every generated variation should conform to neutral rules and avoid clickbait
        assert ev.classification != HookClassification.VIRAL_CLICKBAIT_HOOK
        assert ev.rules.no_time_pressure is True
        assert ev.rules.use_neutral_language is True
