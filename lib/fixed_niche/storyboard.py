"""Storyboard director, claim-to-scene proof map, and technical SVG generator for Practical AI Agent Engineering."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from lib.fixed_niche.svg_pipeline_builder import generate_pipeline_svg

logger = logging.getLogger(__name__)


class MeaningfulVisualError(ValueError):
    """Raised when a proof-bearing beat is missing a concrete explanatory graphic."""
    pass


@dataclass
class ProofBeat:
    beat_id: str
    script_section_id: str
    start_s: float
    end_s: float
    claim_ids: List[str]
    proof_kind: str
    visual_asset_ids: List[str]
    requires_real_demo: bool
    is_illustration: bool
    expected_screen_state: str


@dataclass
class VideoProofMap:
    version: str
    niche_id: str
    policy_sha256: str
    topic_id: str
    viewer_question: str
    beats: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "niche_id": self.niche_id,
            "policy_sha256": self.policy_sha256,
            "topic_id": self.topic_id,
            "viewer_question": self.viewer_question,
            "beats": self.beats,
        }


class FixedNicheStoryboardDirector:
    """Generates 65–75s 6-beat storyboard and technical diagram artwork."""

    def __init__(self, policy_sha256: Optional[str] = None):
        if policy_sha256 is None:
            from lib.fixed_niche.policy import load_locked_policy
            policy_sha256 = load_locked_policy().policy_sha256
        self.policy_sha256 = policy_sha256

    def generate_technical_svg(
        self,
        asset_id: str,
        topic_family: str,
        title: str,
        beat_num: int,
        total_beats: int = 6,
        is_vertical: bool = True,
        duration: float = 11.0,
        narration: str = "",
        word_timestamps: Optional[List[Dict[str, Any]]] = None,
        beat_start_s: float = 0.0,
        progressive: bool = True,
    ) -> str:
        """Generate high-contrast, informative vector geometry tailored to the engineering concept and screen state."""
        return generate_pipeline_svg(
            asset_id=asset_id,
            topic_family=topic_family,
            title=title,
            beat_num=beat_num,
            total_beats=total_beats,
            is_vertical=is_vertical,
            duration=duration,
            narration=narration,
            word_timestamps=word_timestamps,
            beat_start_s=beat_start_s,
            progressive=progressive,
        )

    def compose_dynamic_narration(
        self,
        topic: Dict[str, Any],
        claims: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Compose 6-beat evidence-driven narration grounded in topic claims and brief.

        Calibrated to ~125–130 words total for a 65–75 second shorts delivery duration.
        """
        family = topic.get("topic_family", "context_memory")
        title = topic.get("title", "AI Agent Engineering Explainer")

        # Claims extraction
        statements = [c.get("statement", "") for c in claims if isinstance(c, dict) and c.get("statement")]
        stmt_0 = statements[0] if len(statements) > 0 else ""
        stmt_1 = statements[1] if len(statements) > 1 else ""
        stmt_2 = statements[2] if len(statements) > 2 else ""

        # Beat 1: Hook (0-3s stop-the-scroll quantifiable claim)
        hook = topic.get("hook")
        q = topic.get("viewer_question")
        if hook and len(hook.split()) >= 6:
            b1 = hook if hook.endswith((".", "!")) else f"{hook}."
        elif q and len(q.split()) >= 6:
            b1 = q if q.endswith("?") else f"{q}?"
        elif title:
            clean_title = title.rstrip(".").strip()
            b1 = f"Coding agents encounter recurring failures with {clean_title}. Here is why multi-turn loops break, and the production fix."
        elif family == "agent_tool_use":
            b1 = "A single schema mismatch silently crashes autonomous tool calls. Here is what breaks inside the Model Context Protocol, and the defensive fix."
        elif family == "debugging_reliability":
            b1 = "Automated coding agent pull requests pass isolated unit tests, yet silently break continuous integration builds. Here is the architectural breakdown."
        else:
            b1 = "Autonomous coding agents silently lose memory across process restarts. Here is why prompts reset back to zero, and the repository fix."

        # Beat 2: Developer Impact / Symptom
        symptom = topic.get("symptom") or (stmt_0 if len(stmt_0.split()) >= 4 else "")
        if symptom:
            clean_sym = symptom.rstrip(".")
            b2 = f"In active development workflows, {clean_sym}. The failure derails multi-turn agent execution before code is delivered."
        elif family == "agent_tool_use":
            b2 = "A single type mismatch between the tool schema and the runtime payload causes immediate tool execution failure."
        elif family == "debugging_reliability":
            b2 = "In continuous integration environments, automated coding agent patches satisfy isolated unit assertions, yet silently introduce breaking regressions across downstream test suites."
        else:
            b2 = "You provide detailed constraints in chat, yet the next agent session resets back to zero."

        # Beat 3: Root Cause / Mechanism
        mech = topic.get("root_cause") or topic.get("mechanism") or (stmt_1 if len(stmt_1.split()) >= 4 else "")
        if mech:
            clean_mech = mech.rstrip(".")
            b3 = f"The root architectural cause is {clean_mech}. Autonomous models maintain zero persistent context across process restarts unless boundaries are explicitly declared."
        elif family == "agent_tool_use":
            b3 = "The underlying mechanism is strict validation in client libraries. Autonomous agents frequently emit stringified arguments or hallucinated keys instead of structured dictionaries conforming to the tool definition."
        elif family == "debugging_reliability":
            b3 = "The root architectural mechanism is test blindness. Targeted tests executed in isolation miss shared runtime state, environment variables, and inter-package dependency cycles that fail during full regression builds."
        else:
            b3 = "The root cause is ephemeral session memory. Large language models maintain zero persistent state across process restarts unless repository instructions are explicitly injected into the agent system prompt on every invocation."

        # Beat 4: Verified Remedy / Architecture Fix
        rem = topic.get("remedy") or topic.get("fix") or (stmt_2 if len(stmt_2.split()) >= 4 else "")
        if rem:
            clean_rem = rem.rstrip(".")
            b4 = f"The verified engineering remedy is {clean_rem}. Enforce declarative configuration boundaries before executing code mutations."
        elif family == "agent_tool_use":
            b4 = "The verified remedy is schema defense. Enforce input schema validation before invoking the server, and provide automatic schema coercion filters that sanitize agent payloads before dispatch."
        elif family == "debugging_reliability":
            b4 = "The disciplined engineering remedy is reproduction before repair. Require agents to author hermetic reproduction tests verifying the failure under clean baseline conditions before patching."
        else:
            b4 = "The engineering remedy is declarative configuration. Define an immutable AGENTS markdown contract at the repository root, and enforce automated preflight checks that load these boundaries before executing any code modifications."

        # Beat 5: Local Verification / Demo Checklist
        v_step = topic.get("verification_step") or topic.get("demo_command")
        if v_step and len(v_step.split()) >= 3:
            clean_step = v_step.rstrip(".")
            b5 = f"Verify this remedy locally by running {clean_step}, asserting that reproduction tests pass cleanly under isolated sandbox conditions."
        elif family == "agent_tool_use":
            b5 = "Verify this remedy locally by executing mock MCP tool calls with malformed payloads, asserting that repair filters recover valid arguments and schema errors drop to zero."
        elif family == "debugging_reliability":
            b5 = "Verify this fix locally by running the reproduction test against clean baseline code, confirming that the patch cleanly resolves regressions and assertions deterministically."
        else:
            b5 = "Verify this remedy locally by asserting that newly spawned agent sub-processes explicitly acknowledge boundary rules and pass clean contract tests before any git commit is permitted."

        # Beat 6: Takeaway & Call to Action (CTA)
        cta_suffix = "Follow @OpenMontage for daily AI agent engineering patterns, and star the repo for the complete defensive blueprint."
        takeaway = topic.get("key_takeaway") or topic.get("thesis")
        if takeaway and len(takeaway.split()) >= 4:
            clean_ta = takeaway.rstrip(".")
            b6 = f"Always enforce {clean_ta} in code and CI. {cta_suffix}"
        elif family == "agent_tool_use":
            b6 = f"Enforce strict schema validation and payload coercion in production. {cta_suffix}"
        elif family == "debugging_reliability":
            b6 = f"Always author hermetic reproduction tests before merging automated patches. {cta_suffix}"
        else:
            b6 = f"Always enforce declarative AGENTS contracts in code and CI. {cta_suffix}"

        return {
            "b1": b1, "b2": b2, "b3": b3, "b4": b4, "b5": b5, "b6": b6
        }

    def generate_storyboard(
        self,
        topic: Dict[str, Any],
        claims: List[Dict[str, Any]],
        project_dir: Path,
        target_duration: float = 72.0,
        *,
        write_svg_to_disk: bool = True,
    ) -> Dict[str, Any]:
        """Generate a 6-beat, 65-75s visual plan and video proof map."""
        if not (65.0 <= target_duration <= 75.0):
            raise ValueError(
                f"target_duration {target_duration}s is invalid; must be between 65.0 and 75.0 seconds as defined by policy."
            )

        if not claims:
            raise ValueError("Cannot generate storyboard: claims list is empty; proof map requires verified claims.")
        claim_ids = [c["claim_id"] for c in claims if isinstance(c, dict) and c.get("claim_id")]
        if not claim_ids:
            raise ValueError("Cannot generate storyboard: supplied claims contain no valid claim_id.")

        project_dir = Path(project_dir)
        visuals_dir = project_dir / "assets" / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        cid = topic.get("candidate_id") or topic.get("id") or "cand_01"
        family = topic.get("topic_family", "context_memory")
        title = topic.get("title", "AI Agent Engineering Explainer")
        question = topic.get("viewer_question") or f"Why does this fail: {title}?"

        c1 = claim_ids[0]
        c2 = claim_ids[1] if len(claim_ids) > 1 else c1
        c3 = claim_ids[2] if len(claim_ids) > 2 else c2
        extra_claim_ids = claim_ids[3:]

        # Compose evidence-driven narration grounded in topic claims and brief
        narration_beats = self.compose_dynamic_narration(topic, claims)
        b1_narration = narration_beats["b1"]
        b2_narration = narration_beats["b2"]
        b3_narration = narration_beats["b3"]
        b4_narration = narration_beats["b4"]
        b5_narration = narration_beats["b5"]
        b6_narration = narration_beats["b6"]

        # Determine number of beats: 6 beats cover up to 72.0s without exceeding the 12.0s hold limit.
        # Durations > 72.0s (up to 75.0s) add a 7th beat so every scene hold is <= 12.0s.
        num_beats = 7 if target_duration > 72.0 else 6
        dur_step = target_duration / num_beats
        timestamps = [round(i * dur_step, 2) for i in range(num_beats + 1)]
        timestamps[-1] = round(target_duration, 2)

        # Validate that actual beat intervals never exceed 12.0s
        for i in range(num_beats):
            interval = round(timestamps[i + 1] - timestamps[i], 2)
            if interval > 12.0:
                raise ValueError(
                    f"Beat {i+1} duration ({interval}s) exceeds maximum allowed scene hold of 12.0s for target_duration {target_duration}s."
                )

        import os
        ai_visual_enabled = os.environ.get("AI_VISUAL_ENABLED", "0") in ("1", "true", "True")
        b1_is_ai = ai_visual_enabled
        b3_is_ai = ai_visual_enabled

        beats_spec = [
            {
                "beat_id": "B01",
                "script_section_id": "S01",
                "start_s": timestamps[0],
                "end_s": timestamps[1],
                "story_function": "problem_hook",
                "narration": b1_narration,
                "claim_ids": [c1],
                "visual_kind": "illustration" if b1_is_ai else "svg_diagram",
                "evidence_class": "illustration" if b1_is_ai else "conceptual_diagram",
                "render_strategy": "ai_illustration_eligible" if b1_is_ai else "deterministic_svg",
                "is_proof_bearing": not b1_is_ai,
                "asset_id": f"art_{family}_b01_hook" if b1_is_ai else f"{family}_b01_hook",
                "expected_screen_state": "Screen split: Active session vs blank new session",
                "visual_intent": f"Conceptual illustration depicting developer problem hook: {b1_narration[:80]}",
                "fallback_policy": "typographic_card" if b1_is_ai else "use_builtin_verified_icon_diagram",
            },
            {
                "beat_id": "B02",
                "script_section_id": "S02",
                "start_s": timestamps[1],
                "end_s": timestamps[2],
                "story_function": "developer_impact",
                "narration": b2_narration,
                "claim_ids": [c1],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b02_impact",
                "expected_screen_state": "Developer workflow: requirement input lost across boundary",
                "visual_intent": f"Technical diagram illustrating developer workflow impact: {b2_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
            },
            {
                "beat_id": "B03",
                "script_section_id": "S03",
                "start_s": timestamps[2],
                "end_s": timestamps[3],
                "story_function": "architectural_mechanism",
                "narration": b3_narration,
                "claim_ids": [c2],
                "visual_kind": "illustration" if b3_is_ai else "svg_diagram",
                "evidence_class": "illustration" if b3_is_ai else "conceptual_diagram",
                "render_strategy": "ai_illustration_eligible" if b3_is_ai else "deterministic_svg",
                "is_proof_bearing": not b3_is_ai,
                "asset_id": f"art_{family}_b03_concept" if b3_is_ai else f"{family}_b03_mechanism",
                "expected_screen_state": "Technical lifecycle diagram showing ephemeral context vs durable files",
                "visual_intent": f"Conceptual illustration showing ephemeral session context: {b3_narration[:80]}",
                "fallback_policy": "typographic_card" if b3_is_ai else "use_builtin_verified_icon_diagram",
            },
            {
                "beat_id": "B04",
                "script_section_id": "S04",
                "start_s": timestamps[3],
                "end_s": timestamps[4],
                "story_function": "verified_fix",
                "narration": b4_narration,
                "claim_ids": list(dict.fromkeys([c2, c3, *extra_claim_ids])),
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b04_remedy",
                "expected_screen_state": "Concrete repair diagram: configuration and read step",
                "visual_intent": f"Engineering blueprint showing declarative remedy: {b4_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
            },
            {
                "beat_id": "B05",
                "script_section_id": "S05",
                "start_s": timestamps[4],
                "end_s": timestamps[5],
                "story_function": "verification_checklist",
                "narration": b5_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b05_verify",
                "expected_screen_state": "Verification checklist: pass/fail criteria",
                "visual_intent": f"Terminal trace and verification checklist: {b5_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
            },
        ]

        if num_beats == 7:
            b6_words = b6_narration.split()
            mid = max(1, len(b6_words) // 2)
            b6a_narration = " ".join(b6_words[:mid])
            b6b_narration = " ".join(b6_words[mid:])
            beats_spec.append({
                "beat_id": "B06",
                "script_section_id": "S06",
                "start_s": timestamps[5],
                "end_s": timestamps[6],
                "story_function": "contract_assertion",
                "narration": b6a_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b06_assertion",
                "expected_screen_state": "CI validation pipeline: hermetic contract assertion status",
                "visual_intent": f"Engineering blueprint showing contract assertion verification in CI: {b6a_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
            })
            beats_spec.append({
                "beat_id": "B07",
                "script_section_id": "S07",
                "start_s": timestamps[6],
                "end_s": timestamps[7],
                "story_function": "payoff_and_cta",
                "narration": b6b_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b07_payoff",
                "expected_screen_state": "Summary payoff card with repository star badge and follow call to action",
                "visual_intent": f"Call to action card reinforcing defensive verification principle: {b6b_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
            })
        else:
            beats_spec.append({
                "beat_id": "B06",
                "script_section_id": "S06",
                "start_s": timestamps[5],
                "end_s": timestamps[6],
                "story_function": "payoff_and_cta",
                "narration": b6_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b06_payoff",
                "expected_screen_state": "Summary payoff card with repository star badge and follow call to action",
                "visual_intent": f"Call to action card reinforcing defensive verification principle: {b6_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
            })

        for beat in beats_spec:
            beat["topic_family"] = family
            beat["title"] = title

        # Generate SVGs on disk if requested
        if write_svg_to_disk:
            for i, beat in enumerate(beats_spec):
                asset_id = beat["asset_id"]
                beat_start_s = float(beat.get("start_s", 0.0))
                beat_end_s = float(beat.get("end_s", beat_start_s + 11.0))
                beat_dur = max(1.0, beat_end_s - beat_start_s)
                narration = beat.get("narration", "")
                svg_content = self.generate_technical_svg(
                    asset_id=asset_id,
                    topic_family=family,
                    title=title,
                    beat_num=i + 1,
                    total_beats=len(beats_spec),
                    duration=beat_dur,
                    narration=narration,
                    beat_start_s=beat_start_s,
                    progressive=True,
                )
                svg_file = visuals_dir / f"{asset_id}.svg"
                svg_file.write_text(svg_content, encoding="utf-8")

        # 1. news_visual_plan.json
        visual_plan = {
            "version": "1.0",
            "project_id": cid,
            "beats": beats_spec,
        }
        visual_plan_path = artifacts_dir / "news_visual_plan.json"
        visual_plan_path.write_text(json.dumps(visual_plan, indent=2), encoding="utf-8")

        # 2. video_proof_map.json sidecar
        proof_map_beats = []
        for beat in beats_spec:
            proof_map_beats.append({
                "beat_id": beat["beat_id"],
                "script_section_id": beat["script_section_id"],
                "start_s": beat["start_s"],
                "end_s": beat["end_s"],
                "claim_ids": beat["claim_ids"],
                "proof_kind": beat["evidence_class"],
                "is_proof_bearing": beat.get("is_proof_bearing", False),
                "visual_asset_ids": [f"{beat['asset_id']}.svg"],
                "requires_real_demo": False,
                "is_illustration": True,
                "expected_screen_state": beat["expected_screen_state"],
            })

        proof_map = VideoProofMap(
            version="1.0",
            niche_id="us-ai-agent-engineering",
            policy_sha256=self.policy_sha256,
            topic_id=cid,
            viewer_question=question,
            beats=proof_map_beats,
        )
        proof_map_path = artifacts_dir / "video_proof_map.json"
        proof_map_path.write_text(json.dumps(proof_map.to_dict(), indent=2), encoding="utf-8")

        return {
            "visual_plan": visual_plan,
            "proof_map": proof_map.to_dict(),
            "visual_plan_path": visual_plan_path,
            "proof_map_path": proof_map_path,
            "total_duration": target_duration,
        }

    def validate_frame_sample(self, frame_path: Path, min_variance: float = 10.0) -> Tuple[bool, str]:
        """Verify that a sampled rendered frame is nonblank, non-corrupt, and has visual contrast."""
        frame_path = Path(frame_path)
        if not frame_path.is_file():
            return False, f"Frame sample file not found: {frame_path}"

        size = frame_path.stat().st_size
        if size < 500:
            return False, f"Sampled frame is blank or corrupt (size={size} bytes < 500)"

        try:
            from PIL import Image, ImageStat
            with Image.open(frame_path) as img:
                variance = ImageStat.Stat(img.convert("L")).stddev[0] ** 2
        except Exception as exc:
            return False, f"Sampled frame is corrupt: {exc}"

        if variance < min_variance:
            return False, f"Sampled frame is blank or uniform (variance={variance:.2f} < {min_variance})"

        return True, "Valid nonblank frame"

    def validate_beat_asset(self, beat: Dict[str, Any], project_dir: Path) -> Tuple[bool, str]:
        """Validate beat asset requirements and reject unverified terminal captures."""
        vkind = beat.get("visual_kind")
        if vkind == "terminal_screenshot":
            has_demo = beat.get("has_demo_provenance") or (project_dir / "artifacts" / "demo_results.json").is_file()
            if not has_demo:
                return False, "Terminal screenshot requires verified demo provenance"

        return True, "Asset valid"
