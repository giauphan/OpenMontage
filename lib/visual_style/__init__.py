"""Animated Agent Diagram Visual Style Module.

Clean Architecture facade re-exporting domain specifications, normalizers,
renderers, compilers, directors, and QA validators.
"""
from __future__ import annotations

from lib.visual_style.spec import (
    DiagramAnimationPlan,
    DiagramEdge,
    DiagramEvent,
    DiagramGraph,
    DiagramNode,
    EventType,
    NodeKind,
    TimedVisualBeat,
)
from lib.visual_style.normalization import (
    MAX_BEAT_HOLD_SECONDS,
    MIN_TOTAL_DURATION,
    MAX_TOTAL_DURATION,
    PlanNormalizationError,
    normalize_beats,
    split_long_beats_to_fit_ceiling,
)
from lib.visual_style.validation import (
    DiagramContractError,
    DiagramSecurityError,
    load_diagram_schema,
    validate_diagram_plan_data,
    validate_security_string,
)
from lib.visual_style.layouts import (
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    build_preset_graph,
    get_layout_preset,
    node_to_pixels,
)
from lib.visual_style.svg_renderer import (
    render_inline_svg_dom,
    calculate_edge_geometry,
    get_target_port_offset,
    build_edge_path_d,
    intersect_box,
    cubic_bezier_length,
)
from lib.visual_style.gsap_compiler import (
    compile_gsap_timeline_script,
)
from lib.visual_style.diagram_director import (
    AnimatedDiagramDirector,
)
from lib.visual_style.proof_binding import (
    compute_sha256_bytes,
    compute_sha256_file,
    verify_authentic_source_bytes,
    verify_proof_coverage,
    build_immutable_proof_bundle,
)
from lib.visual_style.qa import (
    evaluate_plan_qa,
    validate_frame_nonblank,
)
from lib.visual_style.ports import (
    DiagramDirectorPort,
    DiagramRendererPort,
    PlanValidatorPort,
    ProofVerifierPort,
    TimelineCompilerPort,
    VisualQaPort,
)

__all__ = [
    "DiagramAnimationPlan",
    "DiagramEdge",
    "DiagramEvent",
    "DiagramGraph",
    "DiagramNode",
    "EventType",
    "NodeKind",
    "TimedVisualBeat",
    "MAX_BEAT_HOLD_SECONDS",
    "MIN_TOTAL_DURATION",
    "MAX_TOTAL_DURATION",
    "PlanNormalizationError",
    "normalize_beats",
    "split_long_beats_to_fit_ceiling",
    "DiagramContractError",
    "DiagramSecurityError",
    "load_diagram_schema",
    "validate_diagram_plan_data",
    "validate_security_string",
    "VIEWPORT_WIDTH",
    "VIEWPORT_HEIGHT",
    "build_preset_graph",
    "get_layout_preset",
    "node_to_pixels",
    "render_inline_svg_dom",
    "calculate_edge_geometry",
    "get_target_port_offset",
    "build_edge_path_d",
    "intersect_box",
    "cubic_bezier_length",
    "compile_gsap_timeline_script",
    "AnimatedDiagramDirector",
    "compute_sha256_bytes",
    "compute_sha256_file",
    "verify_authentic_source_bytes",
    "verify_proof_coverage",
    "build_immutable_proof_bundle",
    "evaluate_plan_qa",
    "validate_frame_nonblank",
    "DiagramDirectorPort",
    "DiagramRendererPort",
    "PlanValidatorPort",
    "ProofVerifierPort",
    "TimelineCompilerPort",
    "VisualQaPort",
]
