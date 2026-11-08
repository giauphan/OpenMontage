from __future__ import annotations

from typing import List, Optional, Sequence
import pytest

from lib.application.content_strategy.ports import HookEvaluatorPort, HookGeneratorPort
from lib.application.content_strategy.use_cases import (
    EvaluateWeakHookUseCase,
    GenerateWeakHookUseCase,
)
from lib.domain.content_strategy.entities import (
    ContextPlatform,
    HookClassification,
    HookSpectrumScore,
    PreFlightChecklist,
    RuleCompliance,
    SkillSignals,
)
from lib.domain.content_strategy.exceptions import InvalidHookError


class FakeHookEvaluator(HookEvaluatorPort):
    def __init__(
        self,
        spectrum: Optional[HookSpectrumScore] = None,
        rules: Optional[RuleCompliance] = None,
        skills: Optional[SkillSignals] = None,
        preflight: Optional[PreFlightChecklist] = None,
    ) -> None:
        self.spectrum = spectrum or HookSpectrumScore(12.0, 4.0, 4.0, 12.0)
        self.rules = rules or RuleCompliance(True, True, True, True, True)
        self.skills = skills or SkillSignals(True, True, True, True, True)
        self.preflight = preflight or PreFlightChecklist(True, True, True, True)

    def evaluate_spectrum(self, text: str) -> HookSpectrumScore:
        return self.spectrum

    def evaluate_rules(self, text: str) -> RuleCompliance:
        return self.rules

    def detect_skills(self, text: str) -> SkillSignals:
        return self.skills

    def check_preflight(
        self,
        text: str,
        platform: ContextPlatform,
        body_summary: Optional[str] = None,
    ) -> PreFlightChecklist:
        return self.preflight


class FakeHookGenerator(HookGeneratorPort):
    def __init__(self, sample_hooks: Sequence[str]) -> None:
        self.sample_hooks = list(sample_hooks)

    def generate_variations(
        self,
        topic: str,
        platform: ContextPlatform,
        context_notes: Optional[str] = None,
        count: int = 3,
    ) -> Sequence[str]:
        return self.sample_hooks[:count]


def test_evaluate_weak_hook_empty_text_raises_error():
    evaluator = FakeHookEvaluator()
    use_case = EvaluateWeakHookUseCase(evaluator)

    with pytest.raises(InvalidHookError):
        use_case.execute("")

    with pytest.raises(InvalidHookError):
        use_case.execute("   \n\t  ")


def test_evaluate_weak_hook_approved_high_trust():
    evaluator = FakeHookEvaluator(
        spectrum=HookSpectrumScore(13.0, 4.0, 3.0, 12.0),  # total: 32.0 (target weak hook)
        rules=RuleCompliance(True, True, True, True, True),
        skills=SkillSignals(True, True, True, True, True),
        preflight=PreFlightChecklist(True, True, True, True),
    )
    use_case = EvaluateWeakHookUseCase(evaluator)

    res = use_case.execute(
        hook_text="In the last 6 months, vector databases became standard for agent memory.",
        platform=ContextPlatform.TECHNICAL_DEEP_DIVE,
    )

    assert res.is_approved is True
    assert res.verdict == "APPROVED_HIGH_TRUST"
    assert res.classification == HookClassification.HIGH_TRUST_WEAK_HOOK
    assert any("Optimal high-trust weak hook" in r for r in res.reasons)


def test_evaluate_weak_hook_needs_revision_when_rules_fail():
    evaluator = FakeHookEvaluator(
        spectrum=HookSpectrumScore(13.0, 4.0, 3.0, 12.0),
        rules=RuleCompliance(
            lead_with_context_not_conflict=False,
            use_neutral_language=False,
            state_the_obvious=False,
            bury_specificity=True,
            no_time_pressure=True,
        ),
        skills=SkillSignals(True, False, False, False, True),
        preflight=PreFlightChecklist(True, True, True, True),
    )
    use_case = EvaluateWeakHookUseCase(evaluator)

    res = use_case.execute(
        hook_text="Your vector database is silently breaking your agent right now!",
        platform=ContextPlatform.LINKEDIN,
        enforce_target_spectrum=True,
    )

    assert res.is_approved is False
    assert res.verdict == "NEEDS_REVISION"
    assert any("Rule 1" in rec for rec in res.recommendations)
    assert any("Rule 2" in rec for rec in res.recommendations)


def test_generate_weak_hook_ranks_by_trust_score():
    class DynamicFakeEvaluator(FakeHookEvaluator):
        def evaluate_spectrum(self, text: str) -> HookSpectrumScore:
            if "ideal" in text:
                return HookSpectrumScore(13.0, 4.0, 3.0, 12.0)  # 32 (Target weak hook)
            elif "clickbait" in text:
                return HookSpectrumScore(25.0, 25.0, 20.0, 20.0)  # 90 (Clickbait)
            return HookSpectrumScore(6.0, 2.0, 2.0, 5.0)  # 15 (Ineffective)

    evaluator = DynamicFakeEvaluator()
    generator = FakeHookGenerator([
        "ineffective hook text",
        "clickbait shocking reveal now",
        "ideal technical context hook",
    ])
    use_case = GenerateWeakHookUseCase(generator, evaluator)

    results = use_case.execute("agent memory", platform=ContextPlatform.ENGINEERING_CHANNEL)
    assert len(results) == 3
    # First ranked must be the high trust target hook
    assert results[0].classification == HookClassification.HIGH_TRUST_WEAK_HOOK
    assert "ideal" in results[0].hook_text
