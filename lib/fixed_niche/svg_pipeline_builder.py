"""Vector SVG pipeline diagram generator for Practical AI Agent Engineering.

Draws high-contrast, beautiful architectural flowcharts of the AI Agent Execution Pipeline,
directly synchronizing each beat's visual with the spoken narration and topic family.
Supports progressive voice-ordered step reveals.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from lib.fixed_niche.voice_timing_aligner import (
    compute_step_timings_for_beat,
    generate_progressive_svg_style,
)


FAMILY_CONFIGS: Dict[str, Dict[str, str]] = {
    "context_memory": {
        "hook_sub": "Failure Mode: Ephemeral Memory Drops Requirements Between Sessions",
        "task_desc": '"Add session persistence tests for agent runner"',
        "rule_desc": "Rule: Enforce hermetic verification before git commit",
        "fail_title": "⚡ SESSION RESET: Working Memory Wiped to 0 KB",
        "fail_desc": "Process exits after task turn. LLM retains zero state across restarts.",
        "fail_crit": "✕ CRITICAL: Conversational memory dropped at session boundary",
        "unanchored_title": "New Subprocess Spawns Without Injected Rules",
        "unanchored_desc": "Agent hallucinates non-compliant edits and bypasses test constraints.",
        "impact_title": "Multi-Turn Workflow Disruption",
        "impact_sub": "How session boundary resets derail multi-turn code delivery",
        "mech_title": "Ephemeral Memory vs Persistent Storage",
        "mech_sub": "Why large language models maintain zero state across restarts",
        "remedy_title": "Closed-Loop Contract Injection",
        "remedy_sub": "Deterministic repository injection for autonomous coding agents",
        "contract_name": "AGENTS.md at Repository Root",
        "contract_desc": "Enforces Clean Architecture: Submodules &lt; 450 lines, max 800",
        "check1": "1. Subprocess Acknowledges AGENTS.md",
        "check2": "2. Hermetic Test Suite Passes Cleanly",
        "check3": "3. Zero Silent Regressions Across Clean Restarts",
        "pass_check3": "PASS: Process reset retains all required state",
        "principle_title": "Never Trust Conversational Memory.",
        "principle_desc": "Always enforce deterministic state persistence across sessions in code and CI.",
        "principle_assert": "assert agent_session.persisted_state == GROUND_TRUTH",
    },
    "agent_tool_use": {
        "hook_sub": "Failure Mode: Unvalidated Tool Schemas Cause Silent Execution Divergence",
        "task_desc": '"Invoke tool with dynamic parameters and structured output"',
        "rule_desc": "Rule: Validate tool arguments strictly against schema before dispatch",
        "fail_title": "⚡ SCHEMA CONTRACT BREACH: Malformed Tool Arguments",
        "fail_desc": "Agent produces unvalidated payload exceeding parameter constraints.",
        "fail_crit": "✕ CRITICAL: Execution boundary violated without schema validation",
        "unanchored_title": "Tool Call Dispatched Without Type Check",
        "unanchored_desc": "Subprocess executes arbitrary action without boundary contract.",
        "impact_title": "Tool Interface Contract Failure",
        "impact_sub": "How unchecked parameter passing causes downstream runtime failures",
        "mech_title": "Ad-Hoc Tool Calls vs Typed Schema Boundaries",
        "mech_sub": "Why agent tools require strict boundary validation and error isolation",
        "remedy_title": "Hermetic Tool Contract Enforcement",
        "remedy_sub": "Deterministic schema validation and boundary sandboxing for agent tools",
        "contract_name": "Tool Schema Contract &amp; Validation Gate",
        "contract_desc": "Enforces Typed Interfaces: JSON Schema boundary validation",
        "check1": "1. Tool Schema Validates Incoming Arguments",
        "check2": "2. Sandbox Execution Isolates Side Effects",
        "check3": "3. Error Handler Recovers from Tool Rejection",
        "pass_check3": "PASS: Schema validation rejects malformed payload cleanly",
        "principle_title": "Never Execute Unvalidated Tool Calls.",
        "principle_desc": "Always enforce strict schema validation and sandbox boundaries before execution.",
        "principle_assert": "assert tool_call.matches_schema(TOOL_CONTRACT)",
    },
    "debugging_reliability": {
        "hook_sub": "Failure Mode: Unverified Patches Introduce Silent CI Regressions",
        "task_desc": '"Fix bug in pipeline runner and verify test assertions"',
        "rule_desc": "Rule: All bug fixes must include regression test before commit",
        "fail_title": "⚡ REGRESSION GATE TRIGGERED: Untracked Defect Introduced",
        "fail_desc": "Agent modifies code without running local test suite.",
        "fail_crit": "✕ CRITICAL: Regression introduced due to unverified patch application",
        "unanchored_title": "Patch Applied Without Local Assertion Check",
        "unanchored_desc": "Agent assumes code change works without hermetic execution.",
        "impact_title": "Defect Reproduction &amp; Patch Verification",
        "impact_sub": "How untested agent modifications break production pipelines",
        "mech_title": "Blind Patching vs Hermetic Regression Loops",
        "mech_sub": "Why autonomous agents require reproducible test harnesses",
        "remedy_title": "Test-Driven Verification Guardrails",
        "remedy_sub": "Automated regression isolation and assertion gating before git commit",
        "contract_name": "Hermetic Test Harness &amp; Regression Gate",
        "contract_desc": "Enforces Test Verification: 0 failures before commit approval",
        "check1": "1. Reproduce Defect with Failing Assertion",
        "check2": "2. Verify Fix Passes Isolated Test Suite",
        "check3": "3. Zero Regressions Across Full Test Matrix",
        "pass_check3": "PASS: All regression assertions pass deterministically",
        "principle_title": "Never Commit Without Regression Proof.",
        "principle_desc": "Always isolate bugs with reproducible assertions and verify cleanly before delivery.",
        "principle_assert": "assert verification_suite.all_tests_passed()",
    },
    "agent_evaluation": {
        "hook_sub": "Failure Mode: Unreproducible Benchmarks Mask Real Agent Failure Rates",
        "task_desc": '"Evaluate agent task performance across test suite"',
        "rule_desc": "Rule: Assert statistical validity and deterministic test seeds",
        "fail_title": "⚡ EVALUATION VARIANCE: Inconsistent Run-to-Run Results",
        "fail_desc": "Nondeterministic evaluation harnesses skew agent reliability scores.",
        "fail_crit": "✕ CRITICAL: Benchmarks lack deterministic execution isolation",
        "unanchored_title": "Uncalibrated Evaluation Matrix",
        "unanchored_desc": "Evaluation metrics lack reproducible baseline assertion checks.",
        "impact_title": "Reliability Evaluation Breakdown",
        "impact_sub": "How uncalibrated metrics misrepresent agent autonomy and accuracy",
        "mech_title": "Single-Run Metrics vs Hermetic Evaluation Matrices",
        "mech_sub": "Why agent evaluation requires multi-seed deterministic validation",
        "remedy_title": "Rigorous Evaluation Harness Guardrails",
        "remedy_sub": "Reproducible benchmark matrices with automated statistical verification",
        "contract_name": "Evaluation Protocol &amp; Scorecard Schema",
        "contract_desc": "Enforces Grounded Metrics: Verified test matrices",
        "check1": "1. Reproducible Seed Configuration Validated",
        "check2": "2. Baseline Comparison Assertion Verified",
        "check3": "3. Statistical Bounds Asserted Across Runs",
        "pass_check3": "PASS: Evaluation matrix passes reproducibility criteria",
        "principle_title": "Never Trust Single-Run Agent Metrics.",
        "principle_desc": "Always measure agent performance across deterministic, multi-seed evaluation suites.",
        "principle_assert": "assert evaluation_matrix.passes_reproducibility()",
    },
    "agent_architecture": {
        "hook_sub": "Failure Mode: Loose Multi-Agent Handoffs Cause State Corruption",
        "task_desc": '"Delegate subtask to specialized worker agent"',
        "rule_desc": "Rule: Enforce typed schema handoffs between independent agents",
        "fail_title": "⚡ HANDOFF CONTRACT CORRUPTION: Loss of Intent",
        "fail_desc": "Agent passes ambiguous state across subprocess boundary.",
        "fail_crit": "✕ CRITICAL: Untyped message handoff causes unrecoverable state loss",
        "unanchored_title": "Decoupled Subagent Lacks State Contract",
        "unanchored_desc": "Subagent operates on stale or misinterpreted parent context.",
        "impact_title": "Orchestration Pipeline Disruption",
        "impact_sub": "How untyped state handoffs break distributed agent workflows",
        "mech_title": "Ad-Hoc Handoffs vs Typed State Orchestration",
        "mech_sub": "Why multi-agent systems require explicit, immutable state handoffs",
        "remedy_title": "Declarative State Handoff Architecture",
        "remedy_sub": "Immutable message passing with typed state transitions between agents",
        "contract_name": "Agent Handoff Protocol &amp; State Schema",
        "contract_desc": "Enforces Explicit Boundaries: Immutable state handoffs",
        "check1": "1. Parent Intent Serialized to Typed Schema",
        "check2": "2. Subagent Acknowledges Handoff Contract",
        "check3": "3. Return Payload Verified Against Schema",
        "pass_check3": "PASS: State handoff preserves all required context",
        "principle_title": "Never Pass Untyped State Between Agents.",
        "principle_desc": "Always enforce declarative state contracts and validation at every agent boundary.",
        "principle_assert": "assert handoff_payload.is_valid(HANDOFF_SCHEMA)",
    },
}

STEP_COUNTS: Dict[int, int] = {1: 4, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4, 7: 4}


def _resolve_progressive_style(
    progressive: bool,
    step_timings: Optional[List[float]],
    num_steps: int,
    narration: str,
    duration: float,
    word_timestamps: Optional[List[Dict[str, Any]]],
    beat_start_s: float,
) -> str:
    """Resolve progressive CSS timing animations for SVG reveals."""
    if not progressive:
        return ""
    if step_timings is None or len(step_timings) != num_steps:
        step_timings = compute_step_timings_for_beat(
            narration=narration,
            duration=duration,
            num_steps=num_steps,
            word_timestamps=word_timestamps,
            beat_start_s=beat_start_s,
        )
    return generate_progressive_svg_style(step_timings)


def _build_vertical_beat(
    beat_num: int,
    total_beats: int,
    fam_label: str,
    cfg: Dict[str, str],
) -> tuple[str, str, str]:
    """Build the accent color, header badge, and SVG body elements for a vertical pipeline beat."""
    if beat_num == 1:
        accent, badge = "#ef4444", f"{fam_label} // AI AGENT PIPELINE HOOK"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <rect x="50" y="80" width="460" height="28" rx="6" fill="#7f1d1d" stroke="#ef4444" stroke-width="1.5"/>
    <text x="280" y="99" fill="#fca5a5" font-family="sans-serif" font-size="11" font-weight="bold" text-anchor="middle">⚡ CRITICAL FAILURE // RECURRING BREAKDOWN</text>
    <text x="50" y="135" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">AI Agent Execution Pipeline</text>
    <text x="50" y="160" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['hook_sub']}</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="130" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    <rect x="75" y="200" width="190" height="26" rx="6" fill="#1e293b"/>
    <text x="170" y="218" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 1: DEVELOPER TASK</text>
    <text x="75" y="255" fill="#f8fafc" font-family="sans-serif" font-size="17" font-weight="bold">{cfg['task_desc']}</text>
    <text x="75" y="285" fill="#94a3b8" font-family="monospace" font-size="13">{cfg['rule_desc']}</text>
    <circle cx="880" cy="245" r="14" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
    <text x="880" y="251" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 490 310 L 490 355" stroke="#38bdf8" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,355 490,370 497,355" fill="#38bdf8"/>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="375" width="880" height="175" rx="14" fill="#1e1b4b" stroke="#ef4444" stroke-width="2.5" stroke-dasharray="8 6"/>
    <rect x="75" y="395" width="230" height="26" rx="6" fill="#7f1d1d"/>
    <text x="190" y="413" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 2: FAILURE POINT</text>
    <text x="75" y="450" fill="#ef4444" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['fail_title']}</text>
    <text x="75" y="480" fill="#cbd5e1" font-family="sans-serif" font-size="14">{cfg['fail_desc']}</text>
    <rect x="75" y="500" width="830" height="35" rx="6" fill="#0f172a"/>
    <text x="95" y="523" fill="#ef4444" font-family="monospace" font-size="13">{cfg['fail_crit']}</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 550 L 490 595" stroke="#ef4444" stroke-width="3" stroke-dasharray="6 4" stroke-linecap="round"/>
    <polygon points="483,595 490,610 497,595" fill="#ef4444"/>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="615" width="880" height="150" rx="14" fill="#0f172a" stroke="#f59e0b" stroke-width="2"/>
    <rect x="75" y="635" width="220" height="26" rx="6" fill="#1e293b"/>
    <text x="185" y="653" fill="#f59e0b" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 3: AGENT REASONING</text>
    <text x="75" y="690" fill="#f8fafc" font-family="sans-serif" font-size="17" font-weight="bold">{cfg['unanchored_title']}</text>
    <text x="75" y="720" fill="#fca5a5" font-family="sans-serif" font-size="14">{cfg['unanchored_desc']}</text>
    <circle cx="880" cy="690" r="14" fill="#1e293b" stroke="#f59e0b" stroke-width="2"/>
    <text x="880" y="696" fill="#f59e0b" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">!</text>
  </g>

  <g id="flow-arrow-3" class="flow-arrow" data-step-order="6">
    <path d="M 490 765 L 490 810" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,810 490,825 497,810" fill="#ef4444"/>
  </g>

  <g id="flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="830" width="880" height="135" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
    <rect x="75" y="850" width="200" height="26" rx="6" fill="#7f1d1d"/>
    <text x="175" y="868" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">OUTCOME: DELIVERY DEADLOCK</text>
    <text x="75" y="905" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Multi-Turn Execution Halted Before Delivery</text>
    <text x="75" y="935" fill="#ef4444" font-family="sans-serif" font-size="14">Pull request breaks continuous integration checks.</text>
    <circle cx="880" cy="895" r="14" fill="#ef4444"/>
    <text x="880" y="902" fill="#ffffff" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✕</text>
  </g>
"""
    elif beat_num == 2:
        accent, badge = "#f59e0b", f"{fam_label} // DEVELOPER IMPACT"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['impact_title']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['impact_sub']}</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="180" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    <rect x="75" y="200" width="180" height="26" rx="6" fill="#1e293b"/>
    <text x="165" y="218" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 1: ACTIVE ATTEMPT</text>
    <text x="75" y="255" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['task_desc']}</text>
    <text x="75" y="285" fill="#cbd5e1" font-family="sans-serif" font-size="14">{cfg['rule_desc']}</text>
    <rect x="75" y="305" width="400" height="32" rx="6" fill="#1e293b"/>
    <text x="95" y="326" fill="#22c55e" font-family="monospace" font-size="13">✓ Status: Reasoning Step Completed</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 490 360 L 490 410" stroke="#f59e0b" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,410 490,425 497,410" fill="#f59e0b"/>
    <rect x="290" y="380" width="400" height="40" rx="8" fill="#7f1d1d" stroke="#ef4444" stroke-width="1.5"/>
    <text x="490" y="405" fill="#fca5a5" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{cfg['fail_title']}</text>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="445" width="880" height="200" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
    <rect x="75" y="465" width="220" height="26" rx="6" fill="#7f1d1d"/>
    <text x="185" y="483" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 2: UNANCHORED STATE</text>
    <text x="75" y="520" fill="#ef4444" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['unanchored_title']}</text>
    <text x="75" y="550" fill="#cbd5e1" font-family="sans-serif" font-size="14">{cfg['unanchored_desc']}</text>
    <rect x="75" y="570" width="830" height="50" rx="8" fill="#1e293b"/>
    <text x="95" y="600" fill="#ef4444" font-family="monospace" font-size="13">{cfg['fail_crit']}</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 645 L 490 700" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,700 490,715 497,700" fill="#ef4444"/>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="725" width="880" height="240" rx="14" fill="#1e1b4b" stroke="#ef4444" stroke-width="2"/>
    <rect x="75" y="745" width="210" height="26" rx="6" fill="#7f1d1d"/>
    <text x="180" y="763" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 3: PIPELINE DEADLOCK</text>
    <text x="75" y="800" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Automated CI Regression Gate Blocks Delivery</text>
    <text x="75" y="830" fill="#cbd5e1" font-family="sans-serif" font-size="14">Developer must manually diagnose why agent broke existing boundaries.</text>
    <rect x="75" y="855" width="830" height="85" rx="8" fill="#0f172a"/>
    <text x="95" y="885" fill="#f59e0b" font-family="monospace" font-size="13">Root Cause: {cfg['fail_desc']}</text>
    <text x="95" y="915" fill="#22c55e" font-family="monospace" font-size="13">Required: {cfg['principle_desc']}</text>
  </g>
"""
    elif beat_num == 3:
        accent, badge = "#38bdf8", f"{fam_label} // ARCHITECTURAL MECHANISM"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['mech_title']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['mech_sub']}</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="320" rx="16" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
    <rect x="75" y="200" width="270" height="28" rx="6" fill="#7f1d1d"/>
    <text x="210" y="219" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">VOLATILE LAYER: EPHEMERAL RAM</text>
    <rect x="75" y="245" width="390" height="170" rx="10" fill="#1e293b" stroke="#334155" stroke-width="1.5"/>
    <text x="95" y="280" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Session A (Active Context)</text>
    <text x="95" y="315" fill="#38bdf8" font-family="sans-serif" font-size="13">• System Prompt in RAM</text>
    <text x="95" y="345" fill="#38bdf8" font-family="sans-serif" font-size="13">• Working Memory Active</text>
    <text x="95" y="375" fill="#22c55e" font-family="sans-serif" font-size="13">✓ Rules In Scope</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 480 330 L 535 330" stroke="#ef4444" stroke-width="3" stroke-dasharray="6 4"/>
    <polygon points="535,324 547,330 535,336" fill="#ef4444"/>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="555" y="245" width="350" height="170" rx="10" fill="#1e1b4b" stroke="#ef4444" stroke-width="2"/>
    <text x="575" y="280" fill="#ef4444" font-family="sans-serif" font-size="16" font-weight="bold">Session B (New Process)</text>
    <text x="575" y="315" fill="#fca5a5" font-family="sans-serif" font-size="13">✕ RAM Cleared to 0 KB</text>
    <text x="575" y="345" fill="#fca5a5" font-family="sans-serif" font-size="13">✕ Context Forgotten</text>
    <text x="575" y="375" fill="#ef4444" font-family="sans-serif" font-size="13">✕ Zero State Persisted</text>
    <rect x="75" y="435" width="830" height="45" rx="8" fill="#1e1b4b"/>
    <text x="490" y="463" fill="#fca5a5" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">⚡ LLMs hold zero persistent state between requests without explicit loaders</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 500 L 490 560" stroke="#38bdf8" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,560 490,575 497,560" fill="#38bdf8"/>
    <rect x="330" y="520" width="320" height="32" rx="6" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>
    <text x="490" y="541" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">EXPLICIT INJECTION REQUIRED</text>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="590" width="880" height="375" rx="16" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <rect x="75" y="610" width="290" height="28" rx="6" fill="#14532d"/>
    <text x="220" y="629" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">DURABLE LAYER: GIT REPOSITORY (DISK)</text>
    <text x="75" y="675" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Persistent Tracked Configuration Survives All Restarts</text>
    <text x="75" y="705" fill="#94a3b8" font-family="sans-serif" font-size="14">Repository files provide permanent ground truth across workstations and CI runners.</text>
    <rect x="75" y="730" width="830" height="205" rx="10" fill="#1e293b"/>
    <text x="95" y="765" fill="#38bdf8" font-family="monospace" font-size="14"># Root Configuration Architecture</text>
    <text x="95" y="795" fill="#22c55e" font-family="monospace" font-size="13">├── AGENTS.md            # Declarative execution contract</text>
    <text x="95" y="825" fill="#22c55e" font-family="monospace" font-size="13">├── config/policy.yaml   # Hard module size &amp; test boundaries</text>
    <text x="95" y="855" fill="#38bdf8" font-family="monospace" font-size="13">└── scripts/preflight.py # Injects contract on agent startup</text>
    <text x="95" y="895" fill="#e2e8f0" font-family="sans-serif" font-size="13">✓ Solution: Automatically compile tracked contracts into the agent prompt</text>
  </g>
"""
    elif beat_num == 4:
        accent, badge = "#22c55e", f"{fam_label} // VERIFIED REMEDY"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['remedy_title']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['remedy_sub']}</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <rect x="75" y="200" width="220" height="26" rx="6" fill="#14532d"/>
    <text x="185" y="218" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 1: IMMUTABLE CONTRACT</text>
    <text x="75" y="255" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['contract_name']}</text>
    <text x="75" y="285" fill="#38bdf8" font-family="monospace" font-size="13">{cfg['contract_desc']}</text>
    <circle cx="880" cy="245" r="14" fill="#14532d"/>
    <text x="880" y="252" fill="#86efac" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 490 325 L 490 370" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,370 490,385 497,370" fill="#22c55e"/>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="385" width="880" height="150" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <rect x="75" y="405" width="230" height="26" rx="6" fill="#14532d"/>
    <text x="190" y="423" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 2: PREFLIGHT SCOPE GATE</text>
    <text x="75" y="460" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Automated Gate Validates Task Boundaries</text>
    <text x="75" y="490" fill="#cbd5e1" font-family="sans-serif" font-size="14">Loads policy before allowing code edits or file modifications.</text>
    <circle cx="880" cy="455" r="14" fill="#14532d"/>
    <text x="880" y="462" fill="#86efac" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 535 L 490 580" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,580 490,595 497,580" fill="#22c55e"/>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="595" width="880" height="160" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    <rect x="75" y="615" width="230" height="26" rx="6" fill="#1e293b"/>
    <text x="190" y="633" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 3: SYSTEM PROMPT INJECTION</text>
    <text x="75" y="670" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Inject Rules Into Every Spawned Subprocess</text>
    <text x="75" y="700" fill="#cbd5e1" font-family="sans-serif" font-size="14">Agent startup harness automatically injects instructions into system prompt.</text>
    <circle cx="880" cy="670" r="14" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
    <text x="880" y="676" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>
  </g>

  <g id="flow-arrow-3" class="flow-arrow" data-step-order="6">
    <path d="M 490 755 L 490 800" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,800 490,815 497,800" fill="#22c55e"/>
  </g>

  <g id="flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="815" width="880" height="150" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2.5"/>
    <rect x="75" y="835" width="220" height="26" rx="6" fill="#14532d"/>
    <text x="185" y="853" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 4: EXECUTION WITH GUARDRAILS</text>
    <text x="75" y="890" fill="#22c55e" font-family="sans-serif" font-size="18" font-weight="bold">Guaranteed Deterministic Boundary Compliance</text>
    <text x="75" y="920" fill="#cbd5e1" font-family="sans-serif" font-size="14">Agent delivers verified code with zero boundary violations across sessions.</text>
    <circle cx="880" cy="890" r="14" fill="#22c55e"/>
    <text x="880" y="897" fill="#0b1120" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✓</text>
  </g>
"""
    elif beat_num == 5:
        accent, badge = "#22c55e", f"{fam_label} // VERIFICATION CHECKLIST"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">Local Automated Verification Gate</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Asserting contract rule compliance before any git commit</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <circle cx="95" cy="235" r="20" fill="#22c55e"/>
    <text x="95" y="243" fill="#0b1120" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">✓</text>
    <text x="135" y="225" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['check1']}</text>
    <text x="135" y="255" fill="#94a3b8" font-family="sans-serif" font-size="14">Spawned agent explicitly reads and echoes active architectural boundaries.</text>
    <text x="135" y="285" fill="#22c55e" font-family="monospace" font-size="13">PASS: Boundary acknowledgment verified in session trace</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 490 325 L 490 370" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,370 490,385 497,370" fill="#22c55e"/>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="385" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <circle cx="95" cy="440" r="20" fill="#22c55e"/>
    <text x="95" y="448" fill="#0b1120" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">✓</text>
    <text x="135" y="430" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['check2']}</text>
    <text x="135" y="460" fill="#94a3b8" font-family="sans-serif" font-size="14">Pytest executes contract assertions in isolated temporary sandbox.</text>
    <text x="135" y="490" fill="#22c55e" font-family="monospace" font-size="13">PASS: Isolated verification suite passed cleanly</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 530 L 490 575" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,575 490,590 497,575" fill="#22c55e"/>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="590" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <circle cx="95" cy="645" r="20" fill="#22c55e"/>
    <text x="95" y="653" fill="#0b1120" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">✓</text>
    <text x="135" y="635" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">{cfg['check3']}</text>
    <text x="135" y="665" fill="#94a3b8" font-family="sans-serif" font-size="14">Verify state persistence test passes deterministically on clean checkout.</text>
    <text x="135" y="695" fill="#22c55e" font-family="monospace" font-size="13">{cfg['pass_check3']}</text>
  </g>

  <g id="flow-arrow-3" class="flow-arrow" data-step-order="6">
    <path d="M 490 735 L 490 780" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
    <polygon points="483,780 490,795 497,780" fill="#22c55e"/>
  </g>

  <g id="flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="795" width="880" height="170" rx="14" fill="#14532d" stroke="#22c55e" stroke-width="2.5"/>
    <text x="490" y="845" fill="#86efac" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">DELIVERY GATE: GIT COMMIT APPROVED</text>
    <text x="490" y="880" fill="#ffffff" font-family="sans-serif" font-size="15" text-anchor="middle">All local architectural verifications passed. Ready for review.</text>
    <rect x="240" y="905" width="500" height="36" rx="8" fill="#0f172a"/>
    <text x="490" y="928" fill="#22c55e" font-family="monospace" font-size="13" text-anchor="middle">{cfg['pass_check3']}</text>
  </g>
"""
    elif beat_num == 6 and total_beats == 7:
        accent, badge = "#8b5cf6", f"{fam_label} // CONTRACT ASSERTION"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['contract_name']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['contract_desc']}</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="230" rx="16" fill="#0f172a" stroke="#8b5cf6" stroke-width="2"/>
    <text x="80" y="225" fill="#a78bfa" font-family="sans-serif" font-size="16" font-weight="bold">CONTRACT RULE 1</text>
    <text x="80" y="260" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">{cfg['check1']}</text>
    <text x="80" y="300" fill="#cbd5e1" font-family="sans-serif" font-size="15">{cfg.get('rule_desc', 'Rule: Strict boundary assertion enforced across all agent turns')}</text>
    <rect x="80" y="330" width="820" height="45" rx="8" fill="#1e293b"/>
    <text x="100" y="358" fill="#22c55e" font-family="monospace" font-size="14">✓ Verified: Boundary precondition guaranteed</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 490 410 L 490 440" stroke="#8b5cf6" stroke-width="2.5"/>
    <polygon points="485,440 490,450 495,440" fill="#8b5cf6"/>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="440" width="880" height="230" rx="16" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <text x="80" y="485" fill="#86efac" font-family="sans-serif" font-size="16" font-weight="bold">CONTRACT RULE 2</text>
    <text x="80" y="520" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">{cfg['check2']}</text>
    <text x="80" y="560" fill="#cbd5e1" font-family="sans-serif" font-size="15">Verification suite executes deterministically before merge or publication.</text>
    <rect x="80" y="590" width="820" height="45" rx="8" fill="#1e293b"/>
    <text x="100" y="618" fill="#22c55e" font-family="monospace" font-size="14">✓ Verified: Zero regression assertion violations</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 670 L 490 700" stroke="#8b5cf6" stroke-width="2.5"/>
    <polygon points="485,700 490,710 495,700" fill="#8b5cf6"/>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="700" width="880" height="260" rx="16" fill="#1e1b4b" stroke="#8b5cf6" stroke-width="2"/>
    <text x="490" y="745" fill="#a78bfa" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">ASSERTION GATE STATUS</text>
    <text x="490" y="790" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">{cfg['pass_check3']}</text>
    <text x="490" y="830" fill="#cbd5e1" font-family="sans-serif" font-size="15" text-anchor="middle">{cfg['principle_desc']}</text>
    <rect x="90" y="865" width="800" height="55" rx="10" fill="#0f172a"/>
    <text x="490" y="898" fill="#22c55e" font-family="monospace" font-size="14" text-anchor="middle">{cfg['principle_assert']}</text>
  </g>
"""
    else:
        accent, badge = "#38bdf8", f"{fam_label} // PRODUCTION SUMMARY"
        body = f"""
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">End-to-End Production Pipeline Flow</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Complete architectural flow for resilient AI agent pipelines</text>
  </g>

  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="120" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    <rect x="80" y="200" width="820" height="80" rx="10" fill="#1e293b"/>
    <circle cx="120" cy="240" r="16" fill="#38bdf8"/>
    <text x="120" y="246" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">1</text>
    <text x="155" y="230" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Repository Specification Layer</text>
    <text x="155" y="257" fill="#94a3b8" font-family="sans-serif" font-size="13">Tracked AGENTS.md contract and clean architecture boundary schemas.</text>
  </g>

  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <path d="M 490 300 L 490 330" stroke="#38bdf8" stroke-width="2.5"/>
    <polygon points="485,330 490,340 495,330" fill="#38bdf8"/>
  </g>

  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="340" width="880" height="120" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    <rect x="80" y="360" width="820" height="80" rx="10" fill="#1e293b"/>
    <circle cx="120" cy="400" r="16" fill="#38bdf8"/>
    <text x="120" y="406" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">2</text>
    <text x="155" y="390" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Automated Preflight Scope Gate</text>
    <text x="155" y="417" fill="#94a3b8" font-family="sans-serif" font-size="13">Compiles and injects repo rules into every agent subprocess on startup.</text>
  </g>

  <g id="flow-arrow-2" class="flow-arrow" data-step-order="4">
    <path d="M 490 460 L 490 490" stroke="#38bdf8" stroke-width="2.5"/>
    <polygon points="485,490 490,500 495,490" fill="#38bdf8"/>
  </g>

  <g id="flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="500" width="880" height="120" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    <rect x="80" y="520" width="820" height="80" rx="10" fill="#1e293b"/>
    <circle cx="120" cy="560" r="16" fill="#38bdf8"/>
    <text x="120" y="566" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">3</text>
    <text x="155" y="550" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Hermetic Execution &amp; Testing</text>
    <text x="155" y="577" fill="#94a3b8" font-family="sans-serif" font-size="13">Autonomous coding loop executes within strict boundary constraints.</text>
  </g>

  <g id="flow-arrow-3" class="flow-arrow" data-step-order="6">
    <path d="M 490 620 L 490 650" stroke="#22c55e" stroke-width="2.5"/>
    <polygon points="485,650 490,660 495,650" fill="#22c55e"/>
  </g>

  <g id="flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="660" width="880" height="110" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    <rect x="80" y="675" width="820" height="80" rx="10" fill="#14532d"/>
    <circle cx="120" cy="715" r="16" fill="#22c55e"/>
    <text x="120" y="721" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">4</text>
    <text x="155" y="705" fill="#86efac" font-family="sans-serif" font-size="16" font-weight="bold">Continuous Integration Gate</text>
    <text x="155" y="733" fill="#ffffff" font-family="sans-serif" font-size="13">Re-verifies contract tests across fresh process checkouts.</text>
    <g id="flow-cta-banner">
      <rect x="50" y="785" width="880" height="185" rx="16" fill="#1e1b4b" stroke="#38bdf8" stroke-width="2.5"/>
      <rect x="80" y="800" width="280" height="26" rx="6" fill="#0f172a" stroke="#38bdf8" stroke-width="1"/>
      <text x="220" y="817" fill="#38bdf8" font-family="sans-serif" font-size="11" font-weight="bold" text-anchor="middle">CALL TO ACTION // ARCHITECTURAL BLUEPRINT</text>
      <text x="490" y="855" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">Follow @OpenMontage for Daily Agent Engineering Patterns</text>
      <rect x="140" y="880" width="700" height="42" rx="8" fill="#0f172a" stroke="#22c55e" stroke-width="1.5"/>
      <text x="490" y="906" fill="#86efac" font-family="monospace" font-size="13" font-weight="bold" text-anchor="middle">★ Star Repository on GitHub: github.com/openmontage/openmontage</text>
      <text x="490" y="945" fill="#94a3b8" font-family="sans-serif" font-size="13" text-anchor="middle">Defensive Contracts • Schema Validation • Hermetic Reproduction</text>
    </g>
  </g>
"""
    return accent, badge, body


def generate_pipeline_svg(
    asset_id: str,
    topic_family: str,
    title: str,
    beat_num: int,
    total_beats: int = 6,
    is_vertical: bool = True,
    step_timings: Optional[List[float]] = None,
    progressive: bool = True,
    duration: float = 11.0,
    narration: str = "",
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    beat_start_s: float = 0.0,
) -> str:
    """Generate high-contrast, informative vector geometry showing the AI Agent Pipeline flow.

    When `progressive=True`, steps display sequentially in order of the voice narration.
    """
    fam = topic_family.lower().strip()
    cfg = FAMILY_CONFIGS.get(fam, FAMILY_CONFIGS["context_memory"])
    fam_label = (
        fam.replace("_", " ")
        .upper()
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_title = html.escape(title[:60], quote=True)

    w = 980 if is_vertical else 960
    h = 1100 if is_vertical else 540
    vb = f"0 0 {w} {h}"

    num_steps = STEP_COUNTS.get(beat_num, 4)
    style_block = _resolve_progressive_style(
        progressive=progressive,
        step_timings=step_timings,
        num_steps=num_steps,
        narration=narration,
        duration=duration,
        word_timestamps=word_timestamps,
        beat_start_s=beat_start_s,
    )

    if not is_vertical:
        return _generate_horizontal_svg(fam_label, safe_title, beat_num, total_beats, style_block)

    accent, badge, body = _build_vertical_beat(beat_num, total_beats, fam_label, cfg)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w}" height="{h}">
  <defs>
{style_block}
  </defs>
  <rect width="{w}" height="{h}" fill="#0b1120"/>
  <rect x="50" y="35" width="380" height="40" rx="10" fill="#1e293b" stroke="{accent}" stroke-width="2"/>
  <text x="240" y="61" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{badge}</text>
  <text x="930" y="61" fill="#64748b" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="end">STAGE {beat_num} OF {total_beats}</text>
{body}
  <rect x="50" y="1005" width="880" height="55" rx="10" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="490" y="1038" fill="#e2e8f0" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">Practical AI Agent Engineering — Hermetic Verification Pipeline</text>
</svg>"""


def _generate_horizontal_svg(
    fam_label: str,
    safe_title: str,
    beat_num: int,
    total_beats: int,
    style_block: str = "",
) -> str:
    """Generate 16:9 horizontal fallback with progressive step structure."""
    accent = "#ef4444" if beat_num in (1, 2) else "#22c55e" if beat_num in (4, 5) else "#38bdf8"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">
  <defs>
{style_block}
  </defs>
  <rect width="960" height="540" fill="#0b1120"/>
  <g id="flow-header" class="flow-step flow-header" data-step-order="0">
    <rect x="40" y="30" width="340" height="36" rx="8" fill="#1e293b" stroke="{accent}" stroke-width="1.5"/>
    <text x="210" y="53" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{fam_label} // STAGE {beat_num}</text>
  </g>
  <g id="flow-step-1" class="flow-step" data-step-order="1">
    <rect x="60" y="90" width="840" height="230" rx="16" fill="#0f172a" stroke="{accent}" stroke-width="2"/>
    <text x="90" y="145" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">{safe_title}</text>
    <text x="90" y="185" fill="#94a3b8" font-family="sans-serif" font-size="15">AI Agent Execution Pipeline Flow Diagram</text>
  </g>
  <g id="flow-arrow-1" class="flow-arrow" data-step-order="2">
    <line x1="480" y1="330" x2="480" y2="390" stroke="{accent}" stroke-width="3" stroke-dasharray="6,4"/>
    <polygon points="474,390 486,390 480,402" fill="{accent}"/>
  </g>
  <g id="flow-step-2" class="flow-step" data-step-order="3">
    <rect x="60" y="420" width="840" height="70" rx="12" fill="#1e293b" stroke="#334155" stroke-width="1"/>
    <text x="480" y="460" fill="#e2e8f0" font-family="sans-serif" font-size="15" text-anchor="middle">Stage {beat_num} of {total_beats} — Practical AI Agent Engineering</text>
  </g>
</svg>"""
