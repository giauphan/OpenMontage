"""Storyboard director and sidecar generator for Animated Agent Diagram visual style.

Converts verified engineering topics and claims into a validated DiagramAnimationPlan sidecar.
Enforces:
1. Editorial rhythm: 8–10 beats (min 6), each <=12.0s, covering 65.0–75.0s.
2. Meaningful visual progression: every beat triggers relevant child SVG events.
3. Persistent diagram continuity: core graph remains visible across beats.

Target module size: < 450 lines.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.visual_style.layouts import build_preset_graph, get_layout_preset
from lib.visual_style.normalization import normalize_beats, MAX_BEAT_HOLD_SECONDS
from lib.visual_style.spec import (
    DiagramAnimationPlan,
    DiagramEvent,
    DiagramGraph,
    EventType,
    TimedVisualBeat,
)
from lib.visual_style.validation import validate_diagram_plan_data

logger = logging.getLogger(__name__)


class AnimatedDiagramDirector:
    """Orchestrates generation of the animated technical diagram storyboard and sidecar."""

    def __init__(self, policy_sha256: Optional[str] = None):
        if policy_sha256 is None:
            try:
                from lib.fixed_niche.policy import load_locked_policy
                policy_sha256 = load_locked_policy().policy_sha256
            except Exception:
                policy_sha256 = "0" * 64
        self.policy_sha256 = policy_sha256

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
        """Create a complete, validated DiagramAnimationPlan for an engineering topic."""
        family = str(topic.get("layout_preset") or topic.get("topic_family", "context_memory"))
        title = str(topic.get("title", "AI Agent Engineering"))
        viewer_q = str(topic.get("viewer_question", title))

        # Ensure target duration is within bounds
        duration = max(65.0, min(75.0, float(target_duration)))

        # 1. Instantiate the persistent technical diagram graph
        graph = build_preset_graph(family, title)
        node_ids = [n.id for n in graph.nodes]
        edge_ids = [e.id for e in graph.edges]

        # Extract available claim IDs
        claim_ids = [str(c["claim_id"]) for c in claims if isinstance(c, dict) and c.get("claim_id")]
        if not claim_ids:
            claim_ids = ["C001"]

        # 2. Design 8 contiguous beats for ideal 65–75s narrative pacing (each <= 10.5s)
        num_beats = 8
        beat_dur = round(duration / num_beats, 3)
        beats: List[TimedVisualBeat] = []
        cur_t = 0.0

        intents = [
            f"Hook: {viewer_q[:80]}",
            "Establish the current system and its main parts",
            "Introduce the central mechanism",
            "Trace how the mechanism changes the flow",
            "Show a concrete use case or consequence",
            "Compare it with the nearest alternative",
            "Connect the parts into one clear mental model",
            "Final payoff: one memorable takeaway",
        ]

        for b_idx in range(num_beats):
            end_t = duration if b_idx == num_beats - 1 else round(cur_t + beat_dur, 3)
            # Cycle through claims to cover all claims across beats
            b_claims = [claim_ids[b_idx % len(claim_ids)]]
            if len(claim_ids) > 1 and b_idx == 0:
                b_claims = list(claim_ids[:2])

            beat = TimedVisualBeat(
                id=f"B{b_idx+1:02d}",
                section_id=f"S{b_idx+1:02d}",
                start_seconds=cur_t,
                end_seconds=end_t,
                claim_ids=b_claims,
                visual_intent=intents[b_idx],
                asset_ids=[f"diagram_state_{b_idx+1:02d}"],
                story_function=f"stage_{b_idx+1}",
                visual_kind="svg_diagram",
                evidence_class="conceptual_diagram",
            )
            beats.append(beat)
            cur_t = end_t

        # 3. Create deterministic animation events synced to beats
        events: List[DiagramEvent] = []
        ev_id = 1

        def add_event(at_s: float, dur_s: float, ev_type: EventType, target: str, beat: TimedVisualBeat):
            nonlocal ev_id
            events.append(
                DiagramEvent(
                    id=f"ev_{ev_id:03d}",
                    at_seconds=round(at_s, 3),
                    duration_seconds=round(dur_s, 3),
                    type=ev_type,
                    target=target,
                    beat_id=beat.id,
                    claim_ids=list(beat.claim_ids),
                )
            )
            ev_id += 1

        # Beat 1 (0 to ~9s): Reveal core agent and starting node
        b0 = beats[0]
        if len(node_ids) >= 1:
            add_event(b0.start_seconds + 0.2, 0.6, EventType.REVEAL_NODE, node_ids[0], b0)
        if len(node_ids) >= 2:
            add_event(b0.start_seconds + 2.5, 0.6, EventType.REVEAL_NODE, node_ids[1], b0)
        if len(edge_ids) >= 1:
            add_event(b0.start_seconds + 4.0, 0.8, EventType.DRAW_EDGE, edge_ids[0], b0)

        # Beat 2 (~9 to ~18s): Trace to secondary store or boundary
        b1 = beats[1]
        if len(node_ids) >= 3:
            add_event(b1.start_seconds + 0.5, 0.6, EventType.REVEAL_NODE, node_ids[2], b1)
        if len(edge_ids) >= 2:
            add_event(b1.start_seconds + 2.0, 0.8, EventType.DRAW_EDGE, edge_ids[1], b1)
        if len(node_ids) >= 2:
            add_event(b1.start_seconds + 4.5, 0.5, EventType.HIGHLIGHT_NODE, node_ids[1], b1)

        # Beat 3 (~18 to ~27s): Introduce decision / failure point
        b2 = beats[2]
        if len(node_ids) >= 4:
            add_event(b2.start_seconds + 0.5, 0.6, EventType.REVEAL_NODE, node_ids[3], b2)
        if len(edge_ids) >= 3:
            add_event(b2.start_seconds + 2.2, 0.8, EventType.DRAW_EDGE, edge_ids[2], b2)
        if len(node_ids) >= 1:
            add_event(b2.start_seconds + 5.0, 0.5, EventType.HIGHLIGHT_NODE, node_ids[0], b2)

        # Beat 4 (~27 to ~36s): Emphasize warning / failure mechanism
        b3 = beats[3]
        if len(node_ids) >= 4:
            add_event(b3.start_seconds + 0.5, 0.6, EventType.CIRCLE_NODE, node_ids[3], b3)
        if len(edge_ids) >= 3:
            add_event(b3.start_seconds + 3.0, 0.5, EventType.FLOW_TOKEN, edge_ids[2], b3)

        # Beat 5 (~36 to ~45s): Reveal remedy / durable structure
        b4 = beats[4]
        if len(node_ids) >= 5:
            add_event(b4.start_seconds + 0.5, 0.6, EventType.REVEAL_NODE, node_ids[4], b4)
        if len(edge_ids) >= 4:
            add_event(b4.start_seconds + 2.2, 0.8, EventType.DRAW_EDGE, edge_ids[3], b4)
        if len(node_ids) >= 4:
            add_event(b4.start_seconds + 5.0, 0.5, EventType.DIM_NODE, node_ids[3], b4)

        # Beat 6 (~45 to ~54s): Reveal verified solution node
        b5 = beats[5]
        target_node = node_ids[5] if len(node_ids) >= 6 else node_ids[-1]
        add_event(b5.start_seconds + 0.5, 0.6, EventType.REVEAL_NODE, target_node, b5)
        if len(edge_ids) >= 5:
            add_event(b5.start_seconds + 2.0, 0.8, EventType.DRAW_EDGE, edge_ids[4], b5)
        if len(node_ids) >= 5:
            add_event(b5.start_seconds + 4.5, 0.5, EventType.HIGHLIGHT_NODE, node_ids[4], b5)

        # Beat 7 (~54 to ~63s): Full system comparison / verification
        b6 = beats[6]
        add_event(b6.start_seconds + 0.5, 0.5, EventType.SHOW_COMPARISON, target_node, b6)
        if len(node_ids) >= 2:
            add_event(b6.start_seconds + 3.0, 0.5, EventType.HIGHLIGHT_NODE, node_ids[1], b6)

        # Beat 8 (~63 to 72s): Final payoff and glowing confirmation
        b7 = beats[7]
        add_event(b7.start_seconds + 0.5, 0.7, EventType.CIRCLE_NODE, target_node, b7)
        add_event(b7.start_seconds + 2.5, 0.5, EventType.HIGHLIGHT_NODE, target_node, b7)

        plan = DiagramAnimationPlan(
            version="1.0",
            style="animated_agent_diagram_v1",
            project_id=project_id,
            template_id=f"chalkboard_{get_layout_preset(family)}",
            duration_seconds=duration,
            script_sha256=script_sha256,
            source_visual_plan_sha256=source_visual_plan_sha256,
            source_claim_ledger_sha256=source_claim_ledger_sha256,
            policy_sha256=self.policy_sha256,
            graph=graph,
            beats=beats,
            events=events,
        )

        # Validate generated plan before returning
        errs = validate_diagram_plan_data(plan.to_dict())
        if errs:
            raise ValueError(f"Generated diagram plan failed validation: {errs}")

        return plan

    def write_sidecar(self, plan: DiagramAnimationPlan, project_dir: Path) -> Path:
        """Write artifacts/diagram_animation_plan.json into the project workspace."""
        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path = artifacts_dir / "diagram_animation_plan.json"
        sidecar_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
        logger.info(f"Wrote diagram animation plan sidecar to {sidecar_path}")
        return sidecar_path
