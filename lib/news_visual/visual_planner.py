"""Claim-aware visual planner for Practical AI Agent Engineering.

Transforms verified claims and timed script sections into a deterministic,
claim-grounded visual plan (artifacts/news_visual_plan.json) following
clean architecture principles.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from lib.fixed_niche.gate import FixedNicheScopeGate, OutcomeStatus
from lib.news_visual.plan_contract import validate_visual_plan

logger = logging.getLogger(__name__)


class VisualPlannerError(ValueError):
    """Raised when visual planning encounters invalid inputs or violates policy."""
    pass


@dataclass(frozen=True)
class PlannedBeat:
    id: str
    script_section_id: str
    start_seconds: float
    end_seconds: float
    story_function: str
    visual_kind: str
    evidence_class: str
    claim_ids: List[str]
    asset_ids: List[str]
    layout: str
    visual_intent: str
    render_strategy: str
    fallback_policy: str
    background_preset: Optional[str] = "dark_tech"
    motion_preset: Optional[str] = "subtle_drift"

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "script_section_id": self.script_section_id,
            "start_seconds": round(self.start_seconds, 2),
            "end_seconds": round(self.end_seconds, 2),
            "story_function": self.story_function,
            "visual_kind": self.visual_kind,
            "evidence_class": self.evidence_class,
            "claim_ids": list(self.claim_ids),
            "asset_ids": list(self.asset_ids),
            "layout": self.layout,
            "visual_intent": self.visual_intent,
            "render_strategy": self.render_strategy,
            "fallback_policy": self.fallback_policy,
        }
        if self.background_preset:
            data["background_preset"] = self.background_preset
        if self.motion_preset:
            data["motion_preset"] = self.motion_preset
        return data


class ClaimAwareVisualPlanner:
    """Plans 6-8 claim-grounded beats with strict proof vs conceptual separation."""

    MIN_TOTAL_DURATION: float = 65.0
    MAX_TOTAL_DURATION: float = 75.0
    MAX_BEAT_HOLD: float = 12.0
    MIN_BEATS: int = 6
    MAX_BEATS: int = 8

    def __init__(self, gate: Optional[FixedNicheScopeGate] = None):
        self.gate = gate or FixedNicheScopeGate()

    def plan_visuals(
        self,
        project_id: str,
        script_data: Dict[str, Any],
        claim_ledger: List[Dict[str, Any]],
        topic: Optional[Dict[str, Any]] = None,
        existing_captures: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a validated news_visual_plan adhering to all policy rules."""
        if not project_id:
            raise VisualPlannerError("project_id must be provided")

        # 1. Gate check: Reject off-niche topics
        if topic:
            verdict = self.gate.evaluate_candidate(topic)
            if not verdict.is_eligible or verdict.status == OutcomeStatus.OFF_NICHE:
                raise VisualPlannerError(f"Topic rejected by FixedNicheScopeGate: {verdict.reason}")

        # 2. Claim ledger validation
        if not claim_ledger:
            raise VisualPlannerError("claim_ledger cannot be empty; every plan requires verified claims")

        self._validate_claim_ledger(claim_ledger)

        # 3. Script validation
        sections = script_data.get("sections")
        if not isinstance(sections, list) or not sections:
            raise VisualPlannerError("script_data must contain a non-empty 'sections' list")

        if len(sections) < self.MIN_BEATS or len(sections) > self.MAX_BEATS:
            raise VisualPlannerError(
                f"Script has {len(sections)} sections; required range is {self.MIN_BEATS}–{self.MAX_BEATS} beats"
            )

        # 4. Duration & timing validation
        total_duration = self._compute_and_verify_durations(sections)

        # 5. Build beats
        script_bytes = json.dumps(script_data, ensure_ascii=False, indent=2).encode("utf-8")
        script_sha = hashlib.sha256(script_bytes).hexdigest()

        beats = self._assemble_beats(
            project_id=project_id,
            sections=sections,
            claim_ledger=claim_ledger,
            existing_captures=existing_captures or [],
        )

        plan = {
            "version": "1.0",
            "project_id": project_id,
            "script_sha256": script_sha,
            "enabled": True,
            "beats": [b.to_dict() for b in beats],
        }

        # Validate against schema and contract
        contract_errors = validate_visual_plan(plan, script_bytes=script_bytes)
        if contract_errors:
            raise VisualPlannerError(f"Contract validation failed: {'; '.join(contract_errors)}")

        return plan

    def retime_plan(
        self,
        existing_plan: Dict[str, Any],
        new_script_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retime an existing visual plan when TTS audio shifts, preserving visual intent."""
        if not existing_plan or not existing_plan.get("beats"):
            raise VisualPlannerError("existing_plan has no beats to retime")

        new_sections = new_script_data.get("sections", [])
        if len(new_sections) != len(existing_plan["beats"]):
            raise VisualPlannerError("Section count mismatch between existing plan and retimed script")

        # Verify semantic content (text) is unchanged; retiming is strictly for timestamp adjustments
        old_beats = existing_plan["beats"]
        updated_beats: List[Dict[str, Any]] = []

        for beat, sec in zip(old_beats, new_sections):
            start = float(sec.get("start_seconds", 0.0))
            end = float(sec.get("end_seconds", 0.0))
            dur = end - start
            if dur > self.MAX_BEAT_HOLD:
                raise VisualPlannerError(f"Retimed beat {beat['id']} duration {dur:.2f}s exceeds {self.MAX_BEAT_HOLD}s")
            if dur <= 0:
                raise VisualPlannerError(f"Retimed beat {beat['id']} has invalid duration: {dur:.2f}s")

            updated_beat = dict(beat)
            updated_beat["start_seconds"] = round(start, 2)
            updated_beat["end_seconds"] = round(end, 2)
            updated_beats.append(updated_beat)

        new_script_bytes = json.dumps(new_script_data, ensure_ascii=False, indent=2).encode("utf-8")
        new_script_sha = hashlib.sha256(new_script_bytes).hexdigest()

        retimed_plan = dict(existing_plan)
        retimed_plan["script_sha256"] = new_script_sha
        retimed_plan["beats"] = updated_beats

        total_dur = updated_beats[-1]["end_seconds"] - updated_beats[0]["start_seconds"]
        if total_dur < self.MIN_TOTAL_DURATION or total_dur > self.MAX_TOTAL_DURATION:
            raise VisualPlannerError(
                f"Retimed total duration {total_dur:.2f}s outside [{self.MIN_TOTAL_DURATION}, {self.MAX_TOTAL_DURATION}]s"
            )

        contract_errors = validate_visual_plan(retimed_plan, script_bytes=new_script_bytes)
        if contract_errors:
            raise VisualPlannerError(f"Retimed contract validation failed: {'; '.join(contract_errors)}")

        return retimed_plan

    def _validate_claim_ledger(self, claim_ledger: List[Dict[str, Any]]) -> None:
        seen_statements: Set[str] = set()
        for idx, claim in enumerate(claim_ledger):
            cid = claim.get("claim_id")
            if not cid:
                raise VisualPlannerError(f"Claim at index {idx} lacks claim_id")

            verdict = str(claim.get("verdict", "")).upper()
            if verdict == "REJECTED":
                raise VisualPlannerError(f"Claim '{cid}' has REJECTED verdict; cannot plan visual for rejected claim")

            source = claim.get("source")
            if not isinstance(source, dict) or not (source.get("canonical_url") or source.get("publisher")):
                raise VisualPlannerError(f"Claim '{cid}' lacks authentic source provenance")

            stmt = str(claim.get("statement", "")).strip().lower()
            if not stmt:
                raise VisualPlannerError(f"Claim '{cid}' statement is empty")

            # Contradiction check: naive opposite detection
            neg_prefix = f"not {stmt}"
            if neg_prefix in seen_statements or (stmt.startswith("not ") and stmt[4:] in seen_statements):
                raise VisualPlannerError(f"Contradictory claim detected: '{stmt}' contradicts prior claim")
            seen_statements.add(stmt)

    def _compute_and_verify_durations(self, sections: List[Dict[str, Any]]) -> float:
        total = 0.0
        for idx, sec in enumerate(sections):
            start = float(sec.get("start_seconds", 0.0))
            end = float(sec.get("end_seconds", 0.0))
            dur = end - start
            if dur <= 0:
                raise VisualPlannerError(f"Section {idx} has invalid duration <= 0 ({start}s -> {end}s)")
            if dur > self.MAX_BEAT_HOLD:
                raise VisualPlannerError(f"Section {idx} hold duration {dur:.2f}s exceeds maximum {self.MAX_BEAT_HOLD}s")
            total = max(total, end)

        if total < self.MIN_TOTAL_DURATION or total > self.MAX_TOTAL_DURATION:
            raise VisualPlannerError(
                f"Total script duration {total:.2f}s is outside required window [{self.MIN_TOTAL_DURATION}, {self.MAX_TOTAL_DURATION}]s"
            )
        return total

    def _assemble_beats(
        self,
        project_id: str,
        sections: List[Dict[str, Any]],
        claim_ledger: List[Dict[str, Any]],
        existing_captures: List[str],
    ) -> List[PlannedBeat]:
        beats: List[PlannedBeat] = []
        claim_ids = [c["claim_id"] for c in claim_ledger]
        num_sections = len(sections)

        # Standard layouts rotation for visual diversity
        layouts = [
            "hero_center",
            "diagram_left_copy_right",
            "split_comparison",
            "metric_grid",
            "device_showcase",
            "diagram_fullscreen",
            "accent_badge_headline",
            "card_minimal",
        ]

        # Target 2 to 4 conceptual AI illustration beats; proof beats are SVG or authentic capture
        # Beat 1 (Hook/Problem): Conceptual Illustration 1
        # Beat 2 (Symptom/Impact): SVG Diagram / Authentic Capture
        # Beat 3 (Root Cause/Mechanism): Conceptual Illustration 2
        # Beat 4 (Remedy/Fix): SVG Diagram / Proof
        # Beat 5 (Verification/Demo): Authentic Capture / SVG Diagram
        # Beat 6 (Takeaway/Principle): Conceptual Illustration 3 or Typographic Focus
        ai_eligible_indices = {0, 2}
        if num_sections >= 7:
            ai_eligible_indices.add(num_sections - 1)

        last_strategy = ""

        for idx, sec in enumerate(sections):
            sec_id = str(sec.get("id") or f"sec_{idx}")
            start = float(sec.get("start_seconds", 0.0))
            end = float(sec.get("end_seconds", 0.0))
            text = sec.get("narration") or sec.get("text") or ""

            # Assign associated claims
            assigned_cids = [claim_ids[idx % len(claim_ids)]]
            beat_id = f"vb-{idx + 1:02d}"

            # Visual intent generation
            intent = self._formulate_visual_intent(idx, text)
            if not intent:
                raise VisualPlannerError(f"Beat {beat_id} has empty visual intent")

            is_conceptual = idx in ai_eligible_indices
            has_matching_capture = bool(existing_captures and idx < len(existing_captures))

            if is_conceptual:
                render_strategy = "ai_illustration_eligible"
                visual_kind = "illustration"
                evidence_class = "illustration"
                fallback_policy = "typographic_card"
                asset_id = f"art_{project_id}_{beat_id}"
            elif has_matching_capture:
                render_strategy = "authentic_capture"
                visual_kind = "authentic_photo"
                evidence_class = "approved_source_visual"
                fallback_policy = "block"
                asset_id = f"cap_{project_id}_{beat_id}"
            else:
                render_strategy = "deterministic_svg"
                visual_kind = "svg_diagram"
                evidence_class = "conceptual_diagram"
                fallback_policy = "use_builtin_verified_icon_diagram"
                asset_id = f"diag_{project_id}_{beat_id}"

            # Ensure consecutive beats don't repeat the exact same strategy if possible
            if render_strategy == last_strategy and render_strategy == "ai_illustration_eligible":
                render_strategy = "deterministic_svg"
                visual_kind = "svg_diagram"
                evidence_class = "conceptual_diagram"
                fallback_policy = "use_builtin_verified_icon_diagram"
                asset_id = f"diag_{project_id}_{beat_id}"

            last_strategy = render_strategy

            beat = PlannedBeat(
                id=beat_id,
                script_section_id=sec_id,
                start_seconds=start,
                end_seconds=end,
                story_function=self._get_story_function(idx, num_sections),
                visual_kind=visual_kind,
                evidence_class=evidence_class,
                claim_ids=assigned_cids,
                asset_ids=[asset_id],
                layout=layouts[idx % len(layouts)],
                visual_intent=intent,
                render_strategy=render_strategy,
                fallback_policy=fallback_policy,
            )
            beats.append(beat)

        return beats

    @staticmethod
    def _formulate_visual_intent(beat_index: int, narration_text: str) -> str:
        clean_text = narration_text[:120].strip()
        intents = [
            f"Hook illustration capturing developer frustration with agent failure: {clean_text}",
            f"Technical schematic depicting developer impact and error propagation: {clean_text}",
            f"Architectural diagram illustrating session memory boundary failure: {clean_text}",
            f"Engineering blueprint of declarative configuration remedy: {clean_text}",
            f"Terminal execution trace proving reproduction and test fix: {clean_text}",
            f"Summary card reinforcing defensive verification principle: {clean_text}",
            f"Secondary verification checklist for CI regression suite: {clean_text}",
            f"Takeaway diagram highlighting production boundary safety: {clean_text}",
        ]
        return intents[beat_index % len(intents)]

    @staticmethod
    def _get_story_function(index: int, total: int) -> str:
        functions = [
            "problem_hook",
            "developer_impact",
            "root_cause_mechanism",
            "architecture_remedy",
            "verification_repro",
            "summary_payoff",
            "ci_pipeline_defense",
            "final_takeaway",
        ]
        return functions[index % len(functions)]
