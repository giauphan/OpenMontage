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


def _is_rhetorical_question(text: str) -> bool:
    """Detect weak rhetorical questions that destroy hook retention."""
    clean = text.strip()
    if clean.endswith("?"):
        return True
    first_word = clean.split()[0].lower() if clean.split() else ""
    return first_word in (
        "why", "how", "what", "when", "where", "which", "who", "whom", "whose",
        "can", "could", "would", "should", "will", "is", "are", "do", "does", "did",
        "have", "has", "had",
    )


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


def build_svg_storyboard_beat(
    beat_id: str,
    section_id: str,
    start_s: float,
    end_s: float,
    story_function: str,
    narration: str,
    claim_ids: list[str],
    asset_id: str,
    screen_state: str,
    visual_intent: str,
    *,
    is_illustration: bool = False,
    family: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Construct a validated storyboard beat specification dictionary."""
    visual_kind = "illustration" if is_illustration else "svg_diagram"
    evidence_class = "illustration" if is_illustration else "conceptual_diagram"
    render_strategy = "ai_illustration_eligible" if is_illustration else "deterministic_svg"
    fallback_policy = "typographic_card" if is_illustration else "use_builtin_verified_icon_diagram"

    return {
        "beat_id": beat_id,
        "script_section_id": section_id,
        "start_s": start_s,
        "end_s": end_s,
        "story_function": story_function,
        "narration": narration,
        "claim_ids": claim_ids,
        "visual_kind": visual_kind,
        "evidence_class": evidence_class,
        "render_strategy": render_strategy,
        "is_proof_bearing": not is_illustration,
        "asset_id": asset_id,
        "expected_screen_state": screen_state,
        "visual_intent": visual_intent,
        "fallback_policy": fallback_policy,
        "topic_family": family,
        "title": title,
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

    @staticmethod
    def _compose_b1(family: str, title: str, clean_hook: str) -> str:
        if clean_hook and len(clean_hook.split()) >= 6 and not _is_rhetorical_question(clean_hook):
            return clean_hook if clean_hook.endswith((".", "!")) else f"{clean_hook}."
        family_hooks = {
            "agent_tool_use": "A single schema mismatch can silently crash an autonomous tool call. Here is what breaks inside the Model Context Protocol, and the defensive fix.",
            "debugging_reliability": "Automated coding agent pull requests often pass local unit tests, yet silently break continuous integration builds. Here is the architectural breakdown and the fix.",
            "context_memory": "Autonomous coding agents lose critical working memory the second a process restarts. Here is why prompts reset back to zero, and the repository fix.",
            "agent_evaluation": "Single-run benchmark scores frequently mask real agent failures on production codebases. Here is why deterministic evaluation matrices are mandatory.",
            "agent_architecture": "Untyped subagent handoffs silently corrupt state across parallel agent workflows. Here is the immutable message passing fix.",
        }
        if family in family_hooks:
            return family_hooks[family]
        if title:
            clean_title = title.rstrip(".").strip()
            return f"Coding agents encounter recurring catastrophic failures with {clean_title}. Here is why multi-turn loops break, and the production fix."
        return "Autonomous coding agents silently lose critical memory across process restarts. Here is why prompts reset back to zero, and the repository fix."

    @staticmethod
    def _compose_b2(family: str, symptom: str, stmt_0: str) -> str:
        sym = symptom or (stmt_0 if len(stmt_0.split()) >= 4 else "")
        if sym:
            return f"In active development workflows, {sym.rstrip('.')}. The failure derails multi-turn agent execution before code is delivered."
        family_symptoms = {
            "agent_tool_use": "A single type mismatch between the tool schema and the runtime payload causes immediate tool execution failure.",
            "debugging_reliability": "In continuous integration environments, automated coding agent patches satisfy isolated unit assertions, yet silently introduce breaking regressions across downstream test suites.",
        }
        return family_symptoms.get(family, "You provide detailed constraints in chat, yet the next agent session resets back to zero.")

    @staticmethod
    def _compose_b3(family: str, mech: str) -> str:
        if mech:
            return f"The root architectural cause is {mech.rstrip('.')}. Autonomous models maintain zero persistent context across process restarts unless boundaries are explicitly declared."
        family_mechs = {
            "agent_tool_use": "The underlying mechanism is strict validation in client libraries. Autonomous agents frequently emit stringified arguments or hallucinated keys instead of structured dictionaries conforming to the tool definition.",
            "debugging_reliability": "The root architectural mechanism is test blindness. Targeted tests executed in isolation miss shared runtime state, environment variables, and inter-package dependency cycles that fail during full regression builds.",
        }
        return family_mechs.get(family, "The root cause is ephemeral session memory. Large language models maintain zero persistent state across process restarts unless repository instructions are explicitly injected into the agent system prompt on every invocation.")

    @staticmethod
    def _compose_b4(family: str, rem: str) -> str:
        if rem:
            return f"The verified engineering remedy is {rem.rstrip('.')}. Enforce declarative configuration boundaries before executing code mutations."
        family_rems = {
            "agent_tool_use": "The verified remedy is schema defense. Enforce input schema validation before invoking the server, and provide automatic schema coercion filters that sanitize agent payloads before dispatch.",
            "debugging_reliability": "The disciplined engineering remedy is reproduction before repair. Require agents to author hermetic reproduction tests verifying the failure under clean baseline conditions before patching.",
        }
        return family_rems.get(family, "The engineering remedy is declarative configuration. Define an immutable AGENTS markdown contract at the repository root, and enforce automated preflight checks that load these boundaries before executing any code modifications.")

    @staticmethod
    def _compose_b5(family: str, v_step: str) -> str:
        if v_step and len(v_step.split()) >= 3:
            return f"Verify this remedy locally by running {v_step.rstrip('.')}, asserting that reproduction tests pass cleanly under isolated sandbox conditions."
        family_vsteps = {
            "agent_tool_use": "Verify this remedy locally by executing mock MCP tool calls with malformed payloads, asserting that repair filters recover valid arguments and schema errors drop to zero.",
            "debugging_reliability": "Verify this fix locally by running the reproduction test against clean baseline code, confirming that the patch cleanly resolves regressions and assertions deterministically.",
        }
        return family_vsteps.get(family, "Verify this remedy locally by asserting that newly spawned agent sub-processes explicitly acknowledge boundary rules and pass clean contract tests before any git commit is permitted.")

    @staticmethod
    def _compose_b6(family: str, takeaway: str) -> str:
        cta_suffix = "Follow me for daily AI agent engineering patterns, and star the repo for the complete defensive blueprint."
        if takeaway and len(takeaway.split()) >= 4:
            return f"Always enforce {takeaway.rstrip('.')} in code and CI. {cta_suffix}"
        family_takeaways = {
            "agent_tool_use": f"Enforce strict schema validation and payload coercion in production. {cta_suffix}",
            "debugging_reliability": f"Always author hermetic reproduction tests before merging automated patches. {cta_suffix}",
        }
        return family_takeaways.get(family, f"Always enforce declarative AGENTS contracts in code and CI. {cta_suffix}")

    def compose_dynamic_narration(
        self,
        topic: Dict[str, Any],
        claims: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Compose 6-beat evidence-driven narration grounded in topic claims and brief."""
        family = topic.get("topic_family", "context_memory")
        title = topic.get("title", "AI Agent Engineering Explainer")

        statements = [c.get("statement", "") for c in claims if isinstance(c, dict) and c.get("statement")]
        stmt_0 = statements[0] if len(statements) > 0 else ""
        stmt_1 = statements[1] if len(statements) > 1 else ""
        stmt_2 = statements[2] if len(statements) > 2 else ""

        hook = topic.get("hook")
        clean_hook = hook.strip() if hook and isinstance(hook, str) else ""

        b1 = self._compose_b1(family, title, clean_hook)
        b2 = self._compose_b2(family, topic.get("symptom"), stmt_0)
        b3 = self._compose_b3(family, topic.get("root_cause") or topic.get("mechanism") or (stmt_1 if len(stmt_1.split()) >= 4 else ""))
        b4 = self._compose_b4(family, topic.get("remedy") or topic.get("fix") or (stmt_2 if len(stmt_2.split()) >= 4 else ""))
        b5 = self._compose_b5(family, topic.get("verification_step") or topic.get("demo_command"))
        b6 = self._compose_b6(family, topic.get("key_takeaway") or topic.get("thesis"))

        return {"b1": b1, "b2": b2, "b3": b3, "b4": b4, "b5": b5, "b6": b6}

    @staticmethod
    def _calculate_timestamps(target_duration: float) -> tuple[int, list[float]]:
        num_beats = 7 if target_duration > 72.0 else 6
        dur_step = target_duration / num_beats
        timestamps = [round(i * dur_step, 2) for i in range(num_beats + 1)]
        timestamps[-1] = round(target_duration, 2)
        for i in range(num_beats):
            interval = round(timestamps[i + 1] - timestamps[i], 2)
            if interval > 12.0:
                raise ValueError(
                    f"Beat {i+1} duration ({interval}s) exceeds maximum allowed scene hold of 12.0s for target_duration {target_duration}s."
                )
        return num_beats, timestamps

    @staticmethod
    def _build_closing_beats(
        timestamps: list[float],
        num_beats: int,
        b6_narration: str,
        claim_id: str,
        family: str,
        title: str,
    ) -> list[dict[str, Any]]:
        """Build beat 6 (and 7 if applicable) closing beat specifications."""
        if num_beats == 7:
            b6_words = b6_narration.split()
            mid = max(1, len(b6_words) // 2)
            n_first = " ".join(b6_words[:mid])
            n_second = " ".join(b6_words[mid:])
            return [
                build_svg_storyboard_beat(
                    "B06", "S06", timestamps[5], timestamps[6], "contract_assertion",
                    n_first, [claim_id], f"{family}_b06_assertion",
                    "CI validation pipeline: hermetic contract assertion status",
                    f"Engineering blueprint showing contract assertion verification in CI: {n_first[:80]}",
                    is_illustration=False, family=family, title=title,
                ),
                build_svg_storyboard_beat(
                    "B07", "S07", timestamps[6], timestamps[7], "payoff_and_cta",
                    n_second, [claim_id], f"{family}_b07_payoff",
                    "Summary payoff card with repository star badge and follow call to action",
                    f"Call to action card reinforcing defensive verification principle: {n_second[:80]}",
                    is_illustration=False, family=family, title=title,
                ),
            ]
        return [
            build_svg_storyboard_beat(
                "B06", "S06", timestamps[5], timestamps[6], "payoff_and_cta",
                b6_narration, [claim_id], f"{family}_b06_payoff",
                "Summary payoff card with repository star badge and follow call to action",
                f"Call to action card reinforcing defensive verification principle: {b6_narration[:80]}",
                is_illustration=False, family=family, title=title,
            )
        ]

    @staticmethod
    def _build_beats_spec(
        timestamps: list[float],
        num_beats: int,
        narration_beats: dict[str, str],
        claim_ids: list[str],
        family: str,
        title: str,
    ) -> list[dict[str, Any]]:
        c1 = claim_ids[0]
        c2 = claim_ids[1] if len(claim_ids) > 1 else c1
        c3 = claim_ids[2] if len(claim_ids) > 2 else c2
        extra_claim_ids = claim_ids[3:]

        b1_n, b2_n, b3_n = narration_beats["b1"], narration_beats["b2"], narration_beats["b3"]
        b4_n, b5_n, b6_n = narration_beats["b4"], narration_beats["b5"], narration_beats["b6"]

        import os
        ai_visual_enabled = os.environ.get("AI_VISUAL_ENABLED", "0") in ("1", "true", "True")
        b1_asset = f"art_{family}_b01_hook" if ai_visual_enabled else f"{family}_b01_hook"
        b3_asset = f"art_{family}_b03_concept" if ai_visual_enabled else f"{family}_b03_mechanism"

        beats_spec = [
            build_svg_storyboard_beat(
                "B01", "S01", timestamps[0], timestamps[1], "problem_hook",
                b1_n, [c1], b1_asset,
                "Screen split: Active session vs blank new session",
                f"Conceptual illustration depicting developer problem hook: {b1_n[:80]}",
                is_illustration=ai_visual_enabled, family=family, title=title,
            ),
            build_svg_storyboard_beat(
                "B02", "S02", timestamps[1], timestamps[2], "developer_impact",
                b2_n, [c1], f"{family}_b02_impact",
                "Developer workflow: requirement input lost across boundary",
                f"Technical diagram illustrating developer workflow impact: {b2_n[:80]}",
                is_illustration=False, family=family, title=title,
            ),
            build_svg_storyboard_beat(
                "B03", "S03", timestamps[2], timestamps[3], "architectural_mechanism",
                b3_n, [c2], b3_asset,
                "Technical lifecycle diagram showing ephemeral context vs durable files",
                f"Conceptual illustration showing ephemeral session context: {b3_n[:80]}",
                is_illustration=ai_visual_enabled, family=family, title=title,
            ),
            build_svg_storyboard_beat(
                "B04", "S04", timestamps[3], timestamps[4], "verified_fix",
                b4_n, list(dict.fromkeys([c2, c3, *extra_claim_ids])), f"{family}_b04_remedy",
                "Concrete repair diagram: configuration and read step",
                f"Engineering blueprint showing declarative remedy: {b4_n[:80]}",
                is_illustration=False, family=family, title=title,
            ),
            build_svg_storyboard_beat(
                "B05", "S05", timestamps[4], timestamps[5], "verification_checklist",
                b5_n, [c3], f"{family}_b05_verify",
                "Verification checklist: pass/fail criteria",
                f"Terminal trace and verification checklist: {b5_n[:80]}",
                is_illustration=False, family=family, title=title,
            ),
        ]
        closing = FixedNicheStoryboardDirector._build_closing_beats(
            timestamps, num_beats, b6_n, c3, family, title
        )
        beats_spec.extend(closing)
        return beats_spec

    def _write_storyboard_svgs(
        self,
        beats_spec: list[dict[str, Any]],
        family: str,
        title: str,
        visuals_dir: Path,
    ) -> None:
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

    @staticmethod
    def _validate_storyboard_inputs(target_duration: float, claims: List[Dict[str, Any]]) -> List[str]:
        if not (65.0 <= target_duration <= 75.0):
            raise ValueError(
                f"target_duration {target_duration}s is invalid; must be between 65.0 and 75.0 seconds as defined by policy."
            )
        if not claims:
            raise ValueError("Cannot generate storyboard: claims list is empty; proof map requires verified claims.")
        claim_ids = [c["claim_id"] for c in claims if isinstance(c, dict) and c.get("claim_id")]
        if not claim_ids:
            raise ValueError("Cannot generate storyboard: supplied claims contain no valid claim_id.")
        return claim_ids

    def _write_storyboard_artifacts(
        self,
        artifacts_dir: Path,
        cid: str,
        question: str,
        beats_spec: List[Dict[str, Any]],
        target_duration: float,
    ) -> Dict[str, Any]:
        visual_plan = {
            "version": "1.0",
            "project_id": cid,
            "beats": beats_spec,
        }
        visual_plan_path = artifacts_dir / "news_visual_plan.json"
        visual_plan_path.write_text(json.dumps(visual_plan, indent=2), encoding="utf-8")

        proof_map_beats = [
            {
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
            }
            for beat in beats_spec
        ]

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
        claim_ids = self._validate_storyboard_inputs(target_duration, claims)

        project_dir = Path(project_dir)
        visuals_dir = project_dir / "assets" / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        cid = topic.get("candidate_id") or topic.get("id") or "cand_01"
        family = topic.get("topic_family", "context_memory")
        title = topic.get("title", "AI Agent Engineering Explainer")
        question = topic.get("viewer_question") or f"Why does this fail: {title}?"

        narration_beats = self.compose_dynamic_narration(topic, claims)
        num_beats, timestamps = self._calculate_timestamps(target_duration)
        beats_spec = self._build_beats_spec(timestamps, num_beats, narration_beats, claim_ids, family, title)

        if write_svg_to_disk:
            self._write_storyboard_svgs(beats_spec, family, title, visuals_dir)

        return self._write_storyboard_artifacts(
            artifacts_dir=artifacts_dir,
            cid=cid,
            question=question,
            beats_spec=beats_spec,
            target_duration=target_duration,
        )

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
