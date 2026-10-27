"""Domain specification and typed entities for Animated Agent Diagram visual style.

Clean Architecture: Pure domain models, decoupled from UI, network, and storage frameworks.
Target module size: < 450 lines.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeKind(str, Enum):
    CONCEPT = "concept"
    TOOL = "tool"
    STORE = "store"
    DECISION = "decision"
    DEVELOPER = "developer"
    AGENT = "agent"
    WARNING = "warning"
    RESULT = "result"


class EventType(str, Enum):
    REVEAL_NODE = "reveal_node"
    HIDE_NODE = "hide_node"
    DRAW_EDGE = "draw_edge"
    HIGHLIGHT_NODE = "highlight_node"
    DIM_NODE = "dim_node"
    CIRCLE_NODE = "circle_node"
    FLOW_TOKEN = "flow_token"
    UPDATE_LABEL_STATE = "update_label_state"
    SHOW_COMPARISON = "show_comparison"
    PROGRESS_REVEAL = "progress_reveal"
    PAN_GRAPH = "pan_graph"
    FOCUS_GROUP = "focus_group"


@dataclass(frozen=True)
class TimedVisualBeat:
    """Unified timed beat entity shared between Daily News and Fixed Niche pipelines."""
    id: str
    section_id: str
    start_seconds: float
    end_seconds: float
    claim_ids: List[str]
    visual_intent: str
    asset_ids: List[str] = field(default_factory=list)
    story_function: str = "scene"
    visual_kind: str = "svg_diagram"
    evidence_class: str = "conceptual_diagram"

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 4)

    def to_sidecar_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "section_id": self.section_id,
            "start_seconds": round(self.start_seconds, 4),
            "end_seconds": round(self.end_seconds, 4),
            "claim_ids": list(self.claim_ids),
            "visual_intent": self.visual_intent,
        }

    def to_dict(self) -> Dict[str, Any]:
        return self.to_sidecar_dict()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimedVisualBeat:
        return cls(
            id=str(data.get("id") or data.get("beat_id") or ""),
            section_id=str(data.get("section_id") or data.get("script_section_id") or ""),
            start_seconds=float(data.get("start_seconds") if data.get("start_seconds") is not None else data.get("start_s", 0.0)),
            end_seconds=float(data.get("end_seconds") if data.get("end_seconds") is not None else data.get("end_s", 0.0)),
            claim_ids=[str(c) for c in data.get("claim_ids", [])],
            visual_intent=str(data.get("visual_intent") or data.get("expected_screen_state") or ""),
            asset_ids=[str(a) for a in (data.get("asset_ids") or ([data["asset_id"]] if data.get("asset_id") else []))],
            story_function=str(data.get("story_function", "scene")),
            visual_kind=str(data.get("visual_kind", "svg_diagram")),
            evidence_class=str(data.get("evidence_class", "conceptual_diagram")),
        )


@dataclass(frozen=True)
class DiagramNode:
    """A semantic node in the technical diagram scene graph."""
    id: str
    label: str
    kind: NodeKind
    x: float
    y: float
    width: float = 0.32
    height: float = 0.08
    group_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "kind": self.kind.value if isinstance(self.kind, NodeKind) else str(self.kind),
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
        }
        if self.group_id:
            d["group_id"] = self.group_id
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiagramNode:
        return cls(
            id=str(data["id"]),
            label=str(data["label"]),
            kind=NodeKind(data["kind"]),
            x=float(data["x"]),
            y=float(data["y"]),
            width=float(data.get("width", 0.32)),
            height=float(data.get("height", 0.08)),
            group_id=str(data["group_id"]) if data.get("group_id") else None,
        )


@dataclass(frozen=True)
class DiagramEdge:
    """A directed edge connecting two semantic diagram nodes."""
    id: str
    source: str
    target: str
    label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "target": self.target,
        }
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiagramEdge:
        return cls(
            id=str(data["id"]),
            source=str(data["source"]),
            target=str(data["target"]),
            label=str(data["label"]) if data.get("label") else None,
        )


@dataclass(frozen=True)
class DiagramEvent:
    """A deterministic visual event executed at an absolute timestamp."""
    id: str
    at_seconds: float
    duration_seconds: float
    type: EventType
    target: str
    beat_id: str
    claim_ids: List[str]
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "at_seconds": round(self.at_seconds, 4),
            "duration_seconds": round(self.duration_seconds, 4),
            "type": self.type.value if isinstance(self.type, EventType) else str(self.type),
            "target": self.target,
            "beat_id": self.beat_id,
            "claim_ids": list(self.claim_ids),
        }
        if self.payload:
            d["payload"] = dict(self.payload)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiagramEvent:
        return cls(
            id=str(data["id"]),
            at_seconds=float(data["at_seconds"]),
            duration_seconds=float(data.get("duration_seconds", 0.5)),
            type=EventType(data["type"]),
            target=str(data["target"]),
            beat_id=str(data["beat_id"]),
            claim_ids=[str(c) for c in data.get("claim_ids", [])],
            payload=dict(data.get("payload", {})),
        )


@dataclass
class DiagramGraph:
    """The persistent graph structure holding all nodes and edges."""
    nodes: List[DiagramNode] = field(default_factory=list)
    edges: List[DiagramEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiagramGraph:
        return cls(
            nodes=[DiagramNode.from_dict(n) for n in data.get("nodes", [])],
            edges=[DiagramEdge.from_dict(e) for e in data.get("edges", [])],
        )


@dataclass
class DiagramAnimationPlan:
    """Canonical Diagram Animation Plan sidecar (version 1.0)."""
    version: str = "1.0"
    style: str = "animated_agent_diagram_v1"
    project_id: str = ""
    duration_seconds: float = 72.0
    script_sha256: str = "0" * 64
    source_visual_plan_sha256: str = "0" * 64
    source_claim_ledger_sha256: str = "0" * 64
    policy_sha256: str = "0" * 64
    graph: DiagramGraph = field(default_factory=DiagramGraph)
    beats: List[TimedVisualBeat] = field(default_factory=list)
    events: List[DiagramEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "style": self.style,
            "project_id": self.project_id,
            "duration_seconds": round(self.duration_seconds, 4),
            "script_sha256": self.script_sha256,
            "source_visual_plan_sha256": self.source_visual_plan_sha256,
            "source_claim_ledger_sha256": self.source_claim_ledger_sha256,
            "policy_sha256": self.policy_sha256,
            "graph": self.graph.to_dict(),
            "beats": [b.to_dict() for b in self.beats],
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DiagramAnimationPlan:
        return cls(
            version=str(data.get("version", "1.0")),
            style=str(data.get("style", "animated_agent_diagram_v1")),
            project_id=str(data.get("project_id", "")),
            duration_seconds=float(data.get("duration_seconds", 72.0)),
            script_sha256=str(data.get("script_sha256", "0" * 64)),
            source_visual_plan_sha256=str(data.get("source_visual_plan_sha256", "0" * 64)),
            source_claim_ledger_sha256=str(data.get("source_claim_ledger_sha256", "0" * 64)),
            policy_sha256=str(data.get("policy_sha256", "0" * 64)),
            graph=DiagramGraph.from_dict(data.get("graph", {})),
            beats=[TimedVisualBeat.from_dict(b) for b in data.get("beats", [])],
            events=[DiagramEvent.from_dict(e) for e in data.get("events", [])],
        )
