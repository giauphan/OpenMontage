"""Storyboard director, claim-to-scene proof map, and technical SVG generator for Practical AI Agent Engineering."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

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
    ) -> str:
        """Generate high-contrast, informative vector geometry tailored to the engineering concept."""
        # 960x540 base canvas
        if topic_family == "context_memory":
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">\n'
                f'  <rect width="960" height="540" fill="#0b1120"/>\n'
                f'  <!-- Header / Topic Badge -->\n'
                f'  <rect x="40" y="30" width="260" height="36" rx="8" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>\n'
                f'  <text x="170" y="53" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">CONTEXT LIFECYCLE</text>\n'
                f'  <!-- Session A Box -->\n'
                f'  <rect x="60" y="120" width="360" height="260" rx="16" fill="#0f172a" stroke="#64748b" stroke-width="2"/>\n'
                f'  <text x="90" y="160" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">SESSION A (ACTIVE CONTEXT)</text>\n'
                f'  <rect x="90" y="190" width="300" height="40" rx="8" fill="#1e293b"/>\n'
                f'  <text x="110" y="215" fill="#94a3b8" font-family="sans-serif" font-size="14">• Project Requirements Loaded</text>\n'
                f'  <rect x="90" y="245" width="300" height="40" rx="8" fill="#1e293b"/>\n'
                f'  <text x="110" y="270" fill="#94a3b8" font-family="sans-serif" font-size="14">• Active Working Memory (8k tokens)</text>\n'
                f'  <rect x="90" y="300" width="300" height="40" rx="8" fill="#1e293b"/>\n'
                f'  <text x="110" y="325" fill="#38bdf8" font-family="sans-serif" font-size="14">• Current Task Goals</text>\n'
                f'  <!-- Session Boundary / Loss Arrow -->\n'
                f'  <path d="M 440 250 L 520 250" stroke="#ef4444" stroke-width="4" stroke-dasharray="8 6"/>\n'
                f'  <polygon points="520,242 536,250 520,258" fill="#ef4444"/>\n'
                f'  <text x="480" y="235" fill="#ef4444" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">SESSION RESET</text>\n'
                f'  <text x="480" y="280" fill="#fca5a5" font-family="sans-serif" font-size="12" text-anchor="middle">(Context Lost)</text>\n'
                f'  <!-- Session B Box -->\n'
                f'  <rect x="540" y="120" width="360" height="260" rx="16" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                f'  <text x="570" y="160" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">SESSION B (NEW CHAT)</text>\n'
                f'  <rect x="570" y="190" width="300" height="40" rx="8" fill="#1e293b"/>\n'
                f'  <text x="590" y="215" fill="#ef4444" font-family="sans-serif" font-size="14">✕ Ephemeral Context: Forgotten</text>\n'
                f'  <rect x="570" y="245" width="300" height="80" rx="8" fill="#1e293b" stroke="#22c55e" stroke-width="2"/>\n'
                f'  <text x="590" y="275" fill="#22c55e" font-family="sans-serif" font-size="14" font-weight="bold">✓ Solution: Durable Repo Config</text>\n'
                f'  <text x="590" y="305" fill="#94a3b8" font-family="sans-serif" font-size="12">Explicitly read from AGENTS.md</text>\n'
                f'  <!-- Bottom Callout -->\n'
                f'  <rect x="60" y="420" width="840" height="60" rx="12" fill="#1e293b" stroke="#334155" stroke-width="1"/>\n'
                f'  <text x="480" y="455" fill="#e2e8f0" font-family="sans-serif" font-size="16" text-anchor="middle">'
                f'Verify with: <tspan fill="#38bdf8" font-family="monospace">git status &amp;&amp; cat AGENTS.md</tspan></text>\n'
                f'</svg>'
            )
        elif topic_family == "agent_tool_use":
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">\n'
                f'  <rect width="960" height="540" fill="#0b1120"/>\n'
                f'  <rect x="40" y="30" width="260" height="36" rx="8" fill="#1e293b" stroke="#a855f7" stroke-width="1.5"/>\n'
                f'  <text x="170" y="53" fill="#a855f7" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">TOOL SCHEMA VALIDATION</text>\n'
                f'  <rect x="60" y="110" width="390" height="280" rx="14" fill="#0f172a" stroke="#64748b" stroke-width="2"/>\n'
                f'  <text x="90" y="145" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">MCP Tool Definition</text>\n'
                f'  <text x="90" y="180" fill="#38bdf8" font-family="monospace" font-size="13">"properties": &#123;</text>\n'
                f'  <text x="110" y="210" fill="#94a3b8" font-family="monospace" font-size="13">"command": &#123; "type": "string" &#125;,</text>\n'
                f'  <text x="110" y="240" fill="#94a3b8" font-family="monospace" font-size="13">"timeout": &#123; "type": "integer" &#125;</text>\n'
                f'  <text x="90" y="270" fill="#38bdf8" font-family="monospace" font-size="13">&#125;, "required": ["command"]</text>\n'
                f'  <!-- Arrow to client call -->\n'
                f'  <path d="M 465 250 L 505 250" stroke="#f59e0b" stroke-width="3"/>\n'
                f'  <polygon points="505,244 517,250 505,256" fill="#f59e0b"/>\n'
                f'  <!-- Payload box -->\n'
                f'  <rect x="520" y="110" width="380" height="280" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                f'  <text x="550" y="145" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Agent Tool Payload</text>\n'
                f'  <text x="550" y="180" fill="#ef4444" font-family="monospace" font-size="13">&#123; "cmd": "pytest tests/" &#125;</text>\n'
                f'  <text x="550" y="220" fill="#fca5a5" font-family="sans-serif" font-size="14">✕ Schema Error: Missing required property: command</text>\n'
                f'  <rect x="550" y="270" width="320" height="80" rx="8" fill="#1e293b" stroke="#22c55e" stroke-width="1.5"/>\n'
                f'  <text x="570" y="300" fill="#22c55e" font-family="sans-serif" font-size="14" font-weight="bold">✓ Repair Strategy:</text>\n'
                f'  <text x="570" y="328" fill="#94a3b8" font-family="monospace" font-size="12">payload["command"] = payload.pop("cmd")</text>\n'
                f'</svg>'
            )
        else:
            # Generic engineering schematic with boxes, causal flow, check marks
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">\n'
                f'  <rect width="960" height="540" fill="#0b1120"/>\n'
                f'  <rect x="40" y="30" width="320" height="36" rx="8" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>\n'
                f'  <text x="200" y="53" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">AGENT VERIFICATION PIPELINE</text>\n'
                f'  <!-- Node 1: Request -->\n'
                f'  <rect x="80" y="150" width="220" height="180" rx="12" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>\n'
                f'  <text x="190" y="195" fill="#38bdf8" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">1. Local Patch</text>\n'
                f'  <text x="190" y="235" fill="#94a3b8" font-family="sans-serif" font-size="13" text-anchor="middle">Agent Unit Tests Pass</text>\n'
                f'  <circle cx="190" cy="275" r="18" fill="#22c55e"/>\n'
                f'  <text x="190" y="281" fill="#0f172a" font-family="sans-serif" font-size="18" font-weight="bold" text-anchor="middle">✓</text>\n'
                f'  <!-- Causal Arrow -->\n'
                f'  <line x1="300" y1="240" x2="360" y2="240" stroke="#64748b" stroke-width="3"/>\n'
                f'  <!-- Node 2: CI Boundary -->\n'
                f'  <rect x="370" y="150" width="220" height="180" rx="12" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                f'  <text x="480" y="195" fill="#ef4444" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">2. CI Execution</text>\n'
                f'  <text x="480" y="235" fill="#fca5a5" font-family="sans-serif" font-size="13" text-anchor="middle">Hidden Mock Drift</text>\n'
                f'  <circle cx="480" cy="275" r="18" fill="#ef4444"/>\n'
                f'  <text x="480" y="281" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold" text-anchor="middle">✕</text>\n'
                f'  <!-- Causal Arrow -->\n'
                f'  <line x1="590" y1="240" x2="650" y2="240" stroke="#64748b" stroke-width="3"/>\n'
                f'  <!-- Node 3: Durable Verification -->\n'
                f'  <rect x="660" y="150" width="220" height="180" rx="12" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>\n'
                f'  <text x="770" y="195" fill="#22c55e" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">3. Verified Fix</text>\n'
                f'  <text x="770" y="235" fill="#94a3b8" font-family="sans-serif" font-size="13" text-anchor="middle">Deterministic Harness</text>\n'
                f'  <circle cx="770" cy="275" r="18" fill="#22c55e"/>\n'
                f'  <text x="770" y="281" fill="#0f172a" font-family="sans-serif" font-size="18" font-weight="bold" text-anchor="middle">✓</text>\n'
                f'  <!-- Bottom diagnostic note -->\n'
                f'  <rect x="80" y="380" width="800" height="60" rx="10" fill="#1e293b"/>\n'
                f'  <text x="480" y="415" fill="#cbd5e1" font-family="sans-serif" font-size="14" text-anchor="middle">'
                f'Stage {beat_num}: Isolating failure mode to prevent silent regression.</text>\n'
                f'</svg>'
            )

    def generate_storyboard(
        self,
        topic: Dict[str, Any],
        claims: List[Dict[str, Any]],
        project_dir: Path,
        target_duration: float = 72.0,
    ) -> Dict[str, Any]:
        """Generate a 6-beat, 65-75s visual plan and video proof map."""
        project_dir = Path(project_dir)
        visuals_dir = project_dir / "assets" / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        cid = topic.get("candidate_id") or topic.get("id") or "cand_01"
        family = topic.get("topic_family", "context_memory")
        title = topic.get("title", "AI Agent Engineering Explainer")
        question = topic.get("viewer_question") or f"Why does this fail: {title}?"

        claim_ids = [c.get("claim_id", f"C00{i+1}") for i, c in enumerate(claims)]
        c1 = claim_ids[0] if len(claim_ids) > 0 else "C001"
        c2 = claim_ids[1] if len(claim_ids) > 1 else c1
        c3 = claim_ids[2] if len(claim_ids) > 2 else c2

        # Per-family dynamic narration templates
        if family == "context_memory":
            b1_narration = f"Why does your AI coding agent forget project rules between sessions?"
            b2_narration = "You give it strict repository instructions, but on the next run, it starts from zero."
            b3_narration = "Here is why: conversation context lives in ephemeral memory, while durable repo instructions require explicit load hooks."
            b4_narration = "The remedy is simple: define an immutable AGENTS.md guide and enforce mandatory session preflight."
            b5_narration = "Verify it locally by checking that every newly spawned agent quotes the repository boundary before writing code."
            b6_narration = "Always verify state persistence across restarts rather than assuming conversational memory survives."
        elif family == "agent_tool_use":
            b1_narration = f"Why do tool calls fail when an AI coding agent executes MCP functions?"
            b2_narration = "A single mismatch between tool JSON schema and runtime payload causes immediate failure."
            b3_narration = "The root cause is strict schema validation: agents often output string arguments instead of structured JSON objects."
            b4_narration = "The verified fix: validate tool input against the JSON schema and provide automatic schema repair filters."
            b5_narration = "Verify the remedy by executing mock MCP tool calls and checking that schema mismatch errors drop to zero."
            b6_narration = "Strict schema adherence and sandbox isolation are mandatory for reliable agent tool execution."
        elif family == "debugging_reliability":
            b1_narration = f"Why do AI agent pull requests pass generated tests but break continuous integration?"
            b2_narration = "Agents write code that passes mock assertions while introducing regression defects into the main suite."
            b3_narration = "The underlying mechanism is test pollution: isolated unit tests miss environment flags and multi-file dependencies."
            b4_narration = "The fix is automated regression verification: require reproducing failures before applying patches."
            b5_narration = "Verify the fix by running full contract test suites in clean, isolated sandbox environments."
            b6_narration = "Always require repro tests with verified assertions before trusting automated agent bug repairs."
        else:
            b1_narration = f"How do engineers identify and fix failures in {title}?"
            b2_narration = f"In production environments, unhandled failure modes can deadlock agent reasoning loops."
            b3_narration = f"Understanding the architectural mechanism prevents subtle failures from propagating downstream."
            b4_narration = f"Applying disciplined engineering patterns ensures deterministic behavior across execution environments."
            b5_narration = "Verify the implementation with automated reproduction tests and strict boundary assertions."
            b6_narration = "Autonomous agent systems require rigorous validation before deployment to production repositories."

        # 6-beat recipe from VIDEO_PLAYBOOK.md
        beats_spec = [
            {
                "beat_id": "B01",
                "script_section_id": "S01",
                "start_s": 0.0,
                "end_s": 3.0,
                "story_function": "problem_hook",
                "narration": b1_narration,
                "claim_ids": [c1],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b01_hook",
                "expected_screen_state": "Screen split: Active session vs blank new session",
            },
            {
                "beat_id": "B02",
                "script_section_id": "S02",
                "start_s": 3.0,
                "end_s": 10.0,
                "story_function": "developer_impact",
                "narration": b2_narration,
                "claim_ids": [c1],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b02_impact",
                "expected_screen_state": "Developer workflow: requirement input lost across boundary",
            },
            {
                "beat_id": "B03",
                "script_section_id": "S03",
                "start_s": 10.0,
                "end_s": 25.0,
                "story_function": "architectural_mechanism",
                "narration": b3_narration,
                "claim_ids": [c2],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b03_mechanism",
                "expected_screen_state": "Technical lifecycle diagram showing ephemeral context vs durable files",
            },
            {
                "beat_id": "B04",
                "script_section_id": "S04",
                "start_s": 25.0,
                "end_s": 42.0,
                "story_function": "verified_fix",
                "narration": b4_narration,
                "claim_ids": [c2, c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b04_remedy",
                "expected_screen_state": "Concrete repair diagram: configuration and read step",
            },
            {
                "beat_id": "B05",
                "script_section_id": "S05",
                "start_s": 42.0,
                "end_s": 58.0,
                "story_function": "verification_checklist",
                "narration": b5_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b05_verify",
                "expected_screen_state": "Verification checklist: pass/fail criteria",
            },
            {
                "beat_id": "B06",
                "script_section_id": "S06",
                "start_s": 58.0,
                "end_s": target_duration,
                "story_function": "payoff_and_caveat",
                "narration": b6_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b06_payoff",
                "expected_screen_state": "Summary payoff card with version qualifier",
            },
        ]

        # Generate SVGs on disk
        for i, beat in enumerate(beats_spec):
            asset_id = beat["asset_id"]
            svg_content = self.generate_technical_svg(
                asset_id=asset_id,
                topic_family=family,
                title=title,
                beat_num=i + 1,
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
