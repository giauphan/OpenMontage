"""Clean Architecture Ports (typing.Protocol) for Animated Agent Diagram.

Inward Dependency Rule:
Use cases and domain workflows depend on abstract Protocol ports,
decoupling high-level orchestrators from concrete rendering, compilation,
and verification adapters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from lib.visual_style.spec import (
    DiagramAnimationPlan,
    DiagramEvent,
    DiagramGraph,
)


@runtime_checkable
class DiagramRendererPort(Protocol):
    """Port for rendering graph structures into markup."""

    def __call__(
        self,
        graph: DiagramGraph,
        title: str = "",
    ) -> str:
        """Render the given DiagramGraph into an inline SVG DOM string."""
        ...


@runtime_checkable
class TimelineCompilerPort(Protocol):
    """Port for compiling animation events into executable timeline scripts."""

    def __call__(
        self,
        plan: DiagramAnimationPlan,
    ) -> str:
        """Compile diagram animation plan into a deterministic GSAP timeline JavaScript string."""
        ...


@runtime_checkable
class ProofVerifierPort(Protocol):
    """Port for authentic source byte verification and proof coverage."""

    def verify_authentic_source_bytes(
        self,
        source_record: Dict[str, Any],
        project_dir: Optional[Path] = None,
        allow_unverified_bytes: bool = False,
    ) -> Tuple[bool, str]:
        """Verify that a source evidence entry originates from genuine primary source capture."""
        ...

    def verify_proof_coverage(
        self,
        beats: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        approved_claims: Dict[str, Any],
    ) -> List[str]:
        """Verify that every claim referenced in beats and events exists in approved claims."""
        ...


@runtime_checkable
class PlanValidatorPort(Protocol):
    """Port for validating diagram plans against JSON schema and referential integrity."""

    def __call__(
        self,
        data: Dict[str, Any],
        *,
        strict_hashes: bool = False,
    ) -> List[str]:
        """Validate diagram plan dictionary against schema and referential invariants, returning errors."""
        ...


@runtime_checkable
class DiagramDirectorPort(Protocol):
    """Port for orchestrating diagram animation planning."""

    def plan_diagram_animation(
        self,
        project_id: str,
        topic: Dict[str, Any],
        claims: List[Dict[str, Any]],
        target_duration: float = 72.0,
        script_sha256: str = "0" * 64,
        source_claim_ledger_sha256: str = "0" * 64,
        source_visual_plan_sha256: str = "0" * 64,
    ) -> DiagramAnimationPlan:
        """Generate a complete DiagramAnimationPlan sidecar."""
        ...


@runtime_checkable
class VisualQaPort(Protocol):
    """Port for evaluating animation activity and contract adherence."""

    def __call__(self, plan: DiagramAnimationPlan) -> Dict[str, Any]:
        """Evaluate plan activity, beat distribution, and contract adherence."""
        ...
