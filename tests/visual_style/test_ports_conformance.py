"""Test conformance of adapters and services to Clean Architecture Ports (typing.Protocol)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import pytest

from lib.visual_style.ports import (
    DiagramDirectorPort,
    DiagramRendererPort,
    PlanValidatorPort,
    TimelineCompilerPort,
    VisualQaPort,
)
from lib.visual_style.diagram_director import AnimatedDiagramDirector
from lib.visual_style.svg_renderer import render_inline_svg_dom
from lib.visual_style.gsap_compiler import compile_gsap_timeline_script
from lib.visual_style.validation import validate_diagram_plan_data
from lib.visual_style.qa import evaluate_plan_qa


def test_renderer_conforms_to_port():
    """render_inline_svg_dom callable must conform to DiagramRendererPort."""
    assert callable(render_inline_svg_dom)
    renderer: DiagramRendererPort = render_inline_svg_dom
    assert isinstance(renderer, DiagramRendererPort)
    from lib.visual_style.spec import DiagramGraph
    out = renderer(DiagramGraph(nodes=[], edges=[]), title="Test")
    assert isinstance(out, str)


def test_compiler_conforms_to_port():
    """compile_gsap_timeline_script callable must conform to TimelineCompilerPort."""
    assert callable(compile_gsap_timeline_script)
    compiler: TimelineCompilerPort = compile_gsap_timeline_script
    assert isinstance(compiler, TimelineCompilerPort)


def test_validator_conforms_to_port():
    """validate_diagram_plan_data callable must conform to PlanValidatorPort."""
    assert callable(validate_diagram_plan_data)
    validator: PlanValidatorPort = validate_diagram_plan_data
    assert isinstance(validator, PlanValidatorPort)
    errs = validator({})
    assert isinstance(errs, list)


def test_director_conforms_to_port():
    """AnimatedDiagramDirector instance must conform to DiagramDirectorPort."""
    director = AnimatedDiagramDirector()
    assert isinstance(director, DiagramDirectorPort)


def test_qa_conforms_to_port():
    """evaluate_plan_qa callable must conform to VisualQaPort."""
    assert callable(evaluate_plan_qa)
    assert isinstance(evaluate_plan_qa, VisualQaPort)


def test_daily_news_gateway_conforms_to_candidate_consumer_port():
    """DailyNewsGatewayClient instance must conform to CandidateConsumerPort."""
    from lib.fixed_niche.candidate_helpers import CandidateConsumerPort
    from tools.news.daily_news_gateway import DailyNewsGatewayClient

    client = DailyNewsGatewayClient()
    assert isinstance(client, CandidateConsumerPort)

