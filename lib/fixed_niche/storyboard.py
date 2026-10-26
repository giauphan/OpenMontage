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
        """Generate high-contrast, informative vector geometry tailored to the engineering concept and screen state."""
        fam = topic_family.lower()
        fam_label = (
            fam.replace("_", " ")
            .upper()
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        safe_title = (
            title[:65]
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        if beat_num == 1:
            accent, badge = "#ef4444", f"{fam_label} // FAILURE HOOK"
            body = (
                f'  <rect x="60" y="110" width="840" height="270" rx="16" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                f'  <circle cx="110" cy="156" r="10" fill="#ef4444"/>\n'
                f'  <rect x="130" y="140" width="160" height="32" rx="6" fill="#7f1d1d"/><text x="210" y="162" fill="#fca5a5" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">FAILURE SYMPTOM</text>\n'
                f'  <text x="90" y="210" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">{safe_title}</text>\n'
                f'  <text x="90" y="245" fill="#94a3b8" font-family="sans-serif" font-size="15">Autonomous coding agent halts unexpectedly in active developer workspace.</text>\n'
                f'  <rect x="90" y="280" width="780" height="65" rx="8" fill="#1e293b"/><text x="120" y="318" fill="#ef4444" font-family="monospace" font-size="14">✕ CRITICAL: Execution deadlock at session boundary</text>\n'
            )
        elif beat_num == 2:
            accent, badge = "#f59e0b", f"{fam_label} // DEVELOPER IMPACT"
            body = (
                f'  <rect x="60" y="115" width="240" height="230" rx="14" fill="#0f172a" stroke="#64748b" stroke-width="2"/>\n'
                f'  <text x="180" y="155" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">1. User Instructions</text>\n'
                f'  <text x="180" y="190" fill="#94a3b8" font-family="sans-serif" font-size="13" text-anchor="middle">Repository Constraints</text>\n'
                f'  <text x="180" y="220" fill="#38bdf8" font-family="monospace" font-size="12" text-anchor="middle">Architectural Rules</text>\n'
                f'  <path d="M 310 230 L 370 230" stroke="#f59e0b" stroke-width="3"/><polygon points="370,224 382,230 370,236" fill="#f59e0b"/>\n'
                f'  <rect x="390" y="115" width="240" height="230" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                f'  <text x="510" y="155" fill="#ef4444" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">2. Reasoning Storm</text>\n'
                f'  <text x="510" y="190" fill="#fca5a5" font-family="sans-serif" font-size="13" text-anchor="middle">Lost context / Flaky tool</text>\n'
                f'  <text x="510" y="220" fill="#ef4444" font-family="monospace" font-size="12" text-anchor="middle">Context Degradation</text>\n'
                f'  <path d="M 640 230 L 700 230" stroke="#ef4444" stroke-width="3"/><polygon points="700,224 712,230 700,236" fill="#ef4444"/>\n'
                f'  <rect x="720" y="115" width="180" height="230" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                f'  <text x="810" y="155" fill="#ef4444" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">3. Deadlock</text>\n'
                f'  <circle cx="810" cy="235" r="20" fill="#ef4444"/><text x="810" y="243" fill="#ffffff" font-family="sans-serif" font-size="18" font-weight="bold" text-anchor="middle">✕</text>\n'
            )
        elif beat_num == 3:
            accent = "#38bdf8"
            badge = f"{fam_label} // ARCHITECTURAL MECHANISM"
            if fam == "context_memory":
                body = (
                    f'  <rect x="60" y="115" width="360" height="250" rx="14" fill="#0f172a" stroke="#64748b" stroke-width="2"/>\n'
                    f'  <text x="90" y="150" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">SESSION A (ACTIVE CONTEXT)</text>\n'
                    f'  <rect x="90" y="175" width="300" height="35" rx="6" fill="#1e293b"/>\n'
                    f'  <text x="110" y="198" fill="#94a3b8" font-family="sans-serif" font-size="13">• Project Requirements Loaded</text>\n'
                    f'  <rect x="90" y="220" width="300" height="35" rx="6" fill="#1e293b"/>\n'
                    f'  <text x="110" y="243" fill="#94a3b8" font-family="sans-serif" font-size="13">• In-Memory Session State</text>\n'
                    f'  <path d="M 435 240 L 515 240" stroke="#ef4444" stroke-width="4" stroke-dasharray="8 6"/>\n'
                    f'  <polygon points="515,232 531,240 515,248" fill="#ef4444"/><text x="475" y="225" fill="#ef4444" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">SESSION RESET</text>\n'
                    f'  <rect x="535" y="115" width="365" height="250" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                    f'  <text x="560" y="150" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">SESSION B (NEW CHAT)</text>\n'
                    f'  <rect x="560" y="175" width="310" height="35" rx="6" fill="#1e293b"/><text x="580" y="198" fill="#ef4444" font-family="sans-serif" font-size="13">✕ Ephemeral Context: Forgotten</text>\n'
                    f'  <rect x="560" y="220" width="310" height="60" rx="6" fill="#1e293b"/>\n'
                    f'  <text x="580" y="245" fill="#94a3b8" font-family="sans-serif" font-size="12">Prompt instructions do not survive across process restarts.</text>\n'
                )
            elif fam == "agent_tool_use":
                body = (
                    f'  <rect x="60" y="115" width="390" height="260" rx="14" fill="#0f172a" stroke="#64748b" stroke-width="2"/>\n'
                    f'  <text x="90" y="145" fill="#f8fafc" font-family="sans-serif" font-size="17" font-weight="bold">MCP Tool Definition</text>\n'
                    f'  <text x="90" y="180" fill="#38bdf8" font-family="monospace" font-size="13">"properties": &#123; "command": &#123;"type": "string"&#125; &#125;</text>\n'
                    f'  <path d="M 465 245 L 505 245" stroke="#f59e0b" stroke-width="3"/><polygon points="505,239 517,245 505,251" fill="#f59e0b"/>\n'
                    f'  <rect x="520" y="115" width="380" height="260" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                    f'  <text x="550" y="145" fill="#f8fafc" font-family="sans-serif" font-size="17" font-weight="bold">Agent Tool Payload</text>\n'
                    f'  <text x="550" y="180" fill="#ef4444" font-family="monospace" font-size="13">&#123; "cmd": "pytest tests/" &#125;</text>\n'
                    f'  <text x="550" y="220" fill="#fca5a5" font-family="sans-serif" font-size="13">✕ Schema Mismatch: Missing command</text>\n'
                )
            else:
                body = (
                    f'  <rect x="80" y="125" width="360" height="240" rx="12" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>\n'
                    f'  <text x="260" y="165" fill="#38bdf8" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">1. Local Execution</text>\n'
                    f'  <circle cx="260" cy="240" r="16" fill="#22c55e"/><text x="260" y="246" fill="#0f172a" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">✓</text>\n'
                    f'  <line x1="450" y1="240" x2="510" y2="240" stroke="#64748b" stroke-width="3"/>\n'
                    f'  <rect x="520" y="125" width="360" height="240" rx="12" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>\n'
                    f'  <text x="700" y="165" fill="#ef4444" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">2. CI Environment</text>\n'
                    f'  <circle cx="700" cy="240" r="16" fill="#ef4444"/><text x="700" y="246" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">✕</text>\n'
                )
        elif beat_num == 4:
            accent = "#22c55e"
            badge = f"{fam_label} // VERIFIED REMEDY"
            if fam == "context_memory":
                body = (
                    f'  <rect x="60" y="115" width="840" height="260" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>\n'
                    f'  <circle cx="80" cy="155" r="10" fill="#22c55e"/><path d="M 76 155 L 79 158 L 85 152" stroke="#ffffff" stroke-width="2" fill="none"/>\n'
                    f'  <rect x="100" y="140" width="240" height="30" rx="6" fill="#14532d"/><text x="220" y="160" fill="#86efac" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">DURABLE REPOSITORY CONFIG</text>\n'
                    f'  <text x="90" y="205" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Store Instructions in Tracked Repo Files</text>\n'
                    f'  <rect x="90" y="225" width="780" height="110" rx="8" fill="#1e293b"/>\n'
                    f'  <text x="110" y="255" fill="#38bdf8" font-family="monospace" font-size="13"># AGENTS.md — Preflight Hook for Spawning Agents</text>\n'
                    f'  <text x="110" y="280" fill="#22c55e" font-family="monospace" font-size="13">1. Mandatory: Read AGENTS.md before taking any action</text>\n'
                    f'  <text x="110" y="305" fill="#e2e8f0" font-family="monospace" font-size="13">2. Verify repository boundary with git status</text>\n'
                )
            elif fam == "agent_tool_use":
                body = (
                    f'  <rect x="60" y="115" width="840" height="260" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>\n'
                    f'  <circle cx="80" cy="155" r="10" fill="#22c55e"/><path d="M 76 155 L 79 158 L 85 152" stroke="#ffffff" stroke-width="2" fill="none"/>\n'
                    f'  <rect x="100" y="140" width="240" height="30" rx="6" fill="#14532d"/><text x="220" y="160" fill="#86efac" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">SCHEMA REPAIR ADAPTER</text>\n'
                    f'  <text x="90" y="205" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Automatic Parameter Mapping &amp; Sanitization</text>\n'
                    f'  <rect x="90" y="225" width="780" height="110" rx="8" fill="#1e293b"/>\n'
                    f'  <text x="110" y="255" fill="#38bdf8" font-family="monospace" font-size="13">def adapt_tool_inputs(payload: dict, schema: dict) -&gt; dict:</text>\n'
                    f'  <text x="130" y="280" fill="#22c55e" font-family="monospace" font-size="13">if "cmd" in payload and "command" not in payload: payload["command"] = payload.pop("cmd")</text>\n'
                )
            else:
                body = (
                    f'  <rect x="60" y="115" width="840" height="260" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>\n'
                    f'  <circle cx="80" cy="155" r="10" fill="#22c55e"/><path d="M 76 155 L 79 158 L 85 152" stroke="#ffffff" stroke-width="2" fill="none"/>\n'
                    f'  <rect x="100" y="140" width="260" height="30" rx="6" fill="#14532d"/><text x="230" y="160" fill="#86efac" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">OFFLINE REPRODUCTION HARNESS</text>\n'
                    f'  <text x="90" y="205" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Reproduce Failures Deterministically Before Patching</text>\n'
                    f'  <rect x="90" y="225" width="780" height="110" rx="8" fill="#1e293b"/>\n'
                    f'  <text x="110" y="255" fill="#38bdf8" font-family="monospace" font-size="13">def test_reproduce_failure_with_mock_environment():</text>\n'
                    f'  <text x="130" y="280" fill="#22c55e" font-family="monospace" font-size="13">with pytest.raises(ExpectedFailureError): execute_pipeline_under_test(mock_inputs)</text>\n'
                )
        elif beat_num == 5:
            accent = "#22c55e"
            badge = f"{fam_label} // VERIFICATION CHECKLIST"
            body = (
                f'  <rect x="60" y="110" width="840" height="280" rx="16" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>\n'
                f'  <rect x="90" y="135" width="220" height="28" rx="6" fill="#14532d"/><text x="200" y="154" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PASS / FAIL AUDIT CRITERIA</text>\n'
                f'  <circle cx="110" cy="195" r="13" fill="#22c55e"/><text x="110" y="201" fill="#0f172a" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">✓</text>\n'
                f'  <text x="135" y="200" fill="#f8fafc" font-family="sans-serif" font-size="15" font-weight="bold">1. Isolated Reproduction Harness Executed</text>\n'
                f'  <circle cx="110" cy="250" r="13" fill="#22c55e"/><text x="110" y="256" fill="#0f172a" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">✓</text>\n'
                f'  <text x="135" y="255" fill="#f8fafc" font-family="sans-serif" font-size="15" font-weight="bold">2. Schema Boundary Validation Passed</text>\n'
                f'  <circle cx="110" cy="305" r="13" fill="#22c55e"/><text x="110" y="311" fill="#0f172a" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">✓</text>\n'
                f'  <text x="135" y="310" fill="#f8fafc" font-family="sans-serif" font-size="15" font-weight="bold">3. Zero Silent Regressions Across Clean Restarts</text>\n'
            )
        else:
            accent = "#38bdf8"
            badge = f"{fam_label} // SUMMARY PAYOFF &amp; SCOPE"
            body = (
                f'  <rect x="60" y="110" width="840" height="280" rx="16" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>\n'
                f'  <circle cx="80" cy="150" r="10" fill="#38bdf8"/><path d="M 76 150 L 79 153 L 85 147" stroke="#0f172a" stroke-width="2" fill="none"/>\n'
                f'  <text x="105" y="155" fill="#38bdf8" font-family="sans-serif" font-size="19" font-weight="bold">ENGINEERING SUMMARY</text>\n'
                f'  <rect x="90" y="170" width="460" height="90" rx="10" fill="#1e293b"/>\n'
                f'  <text x="110" y="200" fill="#f8fafc" font-family="sans-serif" font-size="14" font-weight="bold">Core Production Principle:</text>\n'
                f'  <text x="110" y="225" fill="#94a3b8" font-family="sans-serif" font-size="12">Never trust conversational context or unverified assertions.</text>\n'
                f'  <rect x="570" y="170" width="300" height="90" rx="10" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>\n'
                f'  <text x="590" y="200" fill="#f59e0b" font-family="sans-serif" font-size="12" font-weight="bold">SCOPE &amp; VERSION CAVEAT</text>\n'
                f'  <text x="590" y="225" fill="#e2e8f0" font-family="sans-serif" font-size="12">Applies to Claude Code, Codex, and MCP tools</text>\n'
                f'  <rect x="90" y="280" width="780" height="70" rx="10" fill="#1e293b"/>\n'
                f'  <text x="110" y="315" fill="#22c55e" font-family="sans-serif" font-size="14" font-weight="bold">Always enforce verification boundaries in code and CI.</text>\n'
            )

        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">\n'
            f'  <rect width="960" height="540" fill="#0b1120"/>\n'
            f'  <rect x="40" y="30" width="340" height="36" rx="8" fill="#1e293b" stroke="{accent}" stroke-width="1.5"/>\n'
            f'  <text x="210" y="53" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{badge}</text>\n'
            f'{body}'
            f'  <rect x="60" y="420" width="840" height="60" rx="12" fill="#1e293b" stroke="#334155" stroke-width="1"/>\n'
            f'  <text x="480" y="455" fill="#e2e8f0" font-family="sans-serif" font-size="15" text-anchor="middle">Stage {beat_num} of 6 — Practical AI Agent Engineering</text>\n'
            f'</svg>'
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

        # Beat 1: Hook
        q = topic.get("viewer_question")
        if q and len(q.split()) >= 6:
            b1 = q if q.endswith("?") else f"{q}?"
        elif title:
            b1 = f"Why do autonomous coding agents encounter recurring failures with {title.rstrip('.')}?"
        elif family == "agent_tool_use":
            b1 = "Why do tool calls fail when an AI coding agent executes Model Context Protocol functions?"
        elif family == "debugging_reliability":
            b1 = "Why do AI agent pull requests pass generated tests but break continuous integration builds?"
        else:
            b1 = "Why does your AI coding agent forget repository guidelines between sessions?"

        # Beat 2: Developer Impact / Symptom
        symptom = topic.get("symptom") or (stmt_0 if len(stmt_0.split()) >= 4 else "")
        if symptom:
            clean_sym = symptom.rstrip(".")
            b2 = f"In active development workflows, {clean_sym}. The failure derails multi-turn agent execution before code is delivered."
        elif family == "agent_tool_use":
            b2 = "A single type mismatch between the tool schema and the runtime payload causes immediate tool execution failure."
        elif family == "debugging_reliability":
            b2 = "In modern continuous integration environments, automated agents generate localized code patches that satisfy isolated unit assertions, yet silently introduce breaking regressions across downstream test suites and production build pipelines."
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
            b3 = "The underlying architectural mechanism is context contamination and test blindness. Unit tests executed in isolation fail to catch system environment variables, asynchronous timing races, and inter-package dependency cycles that manifest during full end-to-end continuous integration builds."
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
            b4 = "The disciplined engineering remedy is reproduction before remediation. Mandate that autonomous agents author a hermetic reproduction test verifying the failure under clean baseline conditions before any repair patch is drafted."
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
            b5 = "Verify this fix by executing the reproduction test against a clean main branch baseline, confirming that the failure reproduces deterministically and that the subsequent patch cleanly resolves all test assertions in isolation."
        else:
            b5 = "Verify this remedy locally by asserting that newly spawned agent sub-processes explicitly acknowledge boundary rules and pass clean contract tests before any git commit is permitted."

        # Beat 6: Takeaway & Version Scope
        takeaway = topic.get("key_takeaway") or topic.get("thesis")
        if takeaway and len(takeaway.split()) >= 4:
            clean_ta = takeaway.rstrip(".")
            b6 = f"Always enforce {clean_ta} in code and CI, rather than trusting conversational memory."
        elif family == "agent_tool_use":
            b6 = "Strict schema adherence and defensive payload coercion are mandatory for resilient agent tool integration across production environments."
        elif family == "debugging_reliability":
            b6 = "Always require verified reproduction tests and clean contract assertions before trusting automated agent bug repairs, ensuring that CI builds remain green and stable across production releases."
        else:
            b6 = "Always enforce deterministic state persistence across sessions in code and CI, rather than assuming conversational memory survives."

        return {
            "b1": b1, "b2": b2, "b3": b3, "b4": b4, "b5": b5, "b6": b6
        }

    def generate_storyboard(
        self,
        topic: Dict[str, Any],
        claims: List[Dict[str, Any]],
        project_dir: Path,
        target_duration: float = 72.0,
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

        # 6-beat recipe from VIDEO_PLAYBOOK.md calibrated so no scene holds > 12s
        dur_step = round(target_duration / 6.0, 2)
        t0 = 0.0
        t1 = round(dur_step, 2)
        t2 = round(dur_step * 2, 2)
        t3 = round(dur_step * 3, 2)
        t4 = round(dur_step * 4, 2)
        t5 = round(dur_step * 5, 2)
        t6 = round(target_duration, 2)

        import os
        ai_visual_enabled = os.environ.get("AI_VISUAL_ENABLED", "0") in ("1", "true", "True")
        b1_is_ai = ai_visual_enabled
        b3_is_ai = ai_visual_enabled

        beats_spec = [
            {
                "beat_id": "B01",
                "script_section_id": "S01",
                "start_s": t0,
                "end_s": t1,
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
                "start_s": t1,
                "end_s": t2,
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
                "start_s": t2,
                "end_s": t3,
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
                "start_s": t3,
                "end_s": t4,
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
                "start_s": t4,
                "end_s": t5,
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
            {
                "beat_id": "B06",
                "script_section_id": "S06",
                "start_s": t5,
                "end_s": t6,
                "story_function": "payoff_and_caveat",
                "narration": b6_narration,
                "claim_ids": [c3],
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "render_strategy": "deterministic_svg",
                "is_proof_bearing": True,
                "asset_id": f"{family}_b06_payoff",
                "expected_screen_state": "Summary payoff card with version qualifier",
                "visual_intent": f"Summary card reinforcing defensive verification principle: {b6_narration[:80]}",
                "fallback_policy": "use_builtin_verified_icon_diagram",
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
