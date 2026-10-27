"""Vector SVG pipeline diagram generator for Practical AI Agent Engineering.

Draws high-contrast, beautiful architectural flowcharts of the AI Agent Execution Pipeline,
directly synchronizing each beat's visual with the spoken narration.
"""
from __future__ import annotations

import html


def generate_pipeline_svg(
    asset_id: str,
    topic_family: str,
    title: str,
    beat_num: int,
    total_beats: int = 6,
    is_vertical: bool = True,
) -> str:
    """Generate high-contrast, informative vector geometry showing the AI Agent Pipeline flow."""
    fam = topic_family.lower()
    fam_label = (
        fam.replace("_", " ")
        .upper()
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_title = html.escape(title[:60], quote=True)

    # 980 x 1100 for vertical 9:16 layout; 960 x 540 for horizontal 16:9
    w = 980 if is_vertical else 960
    h = 1100 if is_vertical else 540
    vb = f"0 0 {w} {h}"

    if not is_vertical:
        # Fallback horizontal 16:9 box
        return _generate_horizontal_svg(fam_label, safe_title, beat_num, total_beats)

    if beat_num == 1:
        # Beat 1: Problem Hook - AI Agent Pipeline Breakdown
        accent, badge = "#ef4444", f"{fam_label} // AI AGENT PIPELINE HOOK"
        body = f"""
  <!-- Subtitle Header -->
  <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">AI Agent Execution Pipeline</text>
  <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Failure Mode: Ephemeral Memory Drops Requirements Between Sessions</text>

  <!-- Node 1: User Request -->
  <rect x="50" y="180" width="880" height="130" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
  <rect x="75" y="200" width="190" height="26" rx="6" fill="#1e293b"/>
  <text x="170" y="218" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 1: DEVELOPER TASK</text>
  <text x="75" y="255" fill="#f8fafc" font-family="sans-serif" font-size="17" font-weight="bold">"Add session persistence tests for agent runner"</text>
  <text x="75" y="285" fill="#94a3b8" font-family="monospace" font-size="13">Rule: Enforce hermetic verification before git commit</text>
  <circle cx="880" cy="245" r="14" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
  <text x="880" y="251" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>

  <!-- Flow Arrow 1 -> 2 -->
  <path d="M 490 310 L 490 355" stroke="#38bdf8" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,355 490,370 497,355" fill="#38bdf8"/>

  <!-- Node 2: Ephemeral Context Window (FAILURE POINT) -->
  <rect x="50" y="375" width="880" height="175" rx="14" fill="#1e1b4b" stroke="#ef4444" stroke-width="2.5" stroke-dasharray="8 6"/>
  <rect x="75" y="395" width="230" height="26" rx="6" fill="#7f1d1d"/>
  <text x="190" y="413" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 2: EPHEMERAL CONTEXT</text>
  <text x="75" y="450" fill="#ef4444" font-family="sans-serif" font-size="18" font-weight="bold">⚡ SESSION RESET: Working Memory Wiped to 0 KB</text>
  <text x="75" y="480" fill="#cbd5e1" font-family="sans-serif" font-size="14">Process exits after task turn. LLM retains zero state across restarts.</text>
  <rect x="75" y="500" width="830" height="35" rx="6" fill="#0f172a"/>
  <text x="95" y="523" fill="#ef4444" font-family="monospace" font-size="13">✕ CRITICAL: Conversational memory dropped at session boundary</text>

  <!-- Flow Arrow 2 -> 3 (Broken) -->
  <path d="M 490 550 L 490 595" stroke="#ef4444" stroke-width="3" stroke-dasharray="6 4" stroke-linecap="round"/>
  <polygon points="483,595 490,610 497,595" fill="#ef4444"/>

  <!-- Node 3: Unanchored Agent Reasoning -->
  <rect x="50" y="615" width="880" height="150" rx="14" fill="#0f172a" stroke="#f59e0b" stroke-width="2"/>
  <rect x="75" y="635" width="220" height="26" rx="6" fill="#1e293b"/>
  <text x="185" y="653" fill="#f59e0b" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 3: AGENT REASONING</text>
  <text x="75" y="690" fill="#f8fafc" font-family="sans-serif" font-size="17" font-weight="bold">New Subprocess Spawns Without Injected Rules</text>
  <text x="75" y="720" fill="#fca5a5" font-family="sans-serif" font-size="14">Agent hallucinates non-compliant edits and bypasses test constraints.</text>
  <circle cx="880" cy="690" r="14" fill="#1e293b" stroke="#f59e0b" stroke-width="2"/>
  <text x="880" y="696" fill="#f59e0b" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">!</text>

  <!-- Flow Arrow 3 -> 4 -->
  <path d="M 490 765 L 490 810" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,810 490,825 497,810" fill="#ef4444"/>

  <!-- Node 4: Delivery Deadlock -->
  <rect x="50" y="830" width="880" height="135" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
  <rect x="75" y="850" width="200" height="26" rx="6" fill="#7f1d1d"/>
  <text x="175" y="868" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">OUTCOME: DELIVERY DEADLOCK</text>
  <text x="75" y="905" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Multi-Turn Execution Halted Before Delivery</text>
  <text x="75" y="935" fill="#ef4444" font-family="sans-serif" font-size="14">Pull request breaks continuous integration checks.</text>
  <circle cx="880" cy="895" r="14" fill="#ef4444"/>
  <text x="880" y="902" fill="#ffffff" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✕</text>
"""
    elif beat_num == 2:
        # Beat 2: Developer Impact - Multi-turn workflow breakdown
        accent, badge = "#f59e0b", f"{fam_label} // DEVELOPER IMPACT"
        body = f"""
  <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">Multi-Turn Workflow Disruption</text>
  <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">How session boundary resets derail multi-turn code delivery</text>

  <!-- Turn 1 Box -->
  <rect x="50" y="180" width="880" height="180" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
  <rect x="75" y="200" width="180" height="26" rx="6" fill="#1e293b"/>
  <text x="165" y="218" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 1: TURN 1 (ACTIVE)</text>
  <text x="75" y="255" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">User Loads Rules &amp; Architecture Guidelines</text>
  <text x="75" y="285" fill="#cbd5e1" font-family="sans-serif" font-size="14">Agent operates within in-memory context window (volatile working memory).</text>
  <rect x="75" y="305" width="400" height="32" rx="6" fill="#1e293b"/>
  <text x="95" y="326" fill="#22c55e" font-family="monospace" font-size="13">✓ Status: In-Memory Reasoning Succeeded</text>

  <!-- Reset Event -->
  <path d="M 490 360 L 490 410" stroke="#f59e0b" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,410 490,425 497,410" fill="#f59e0b"/>
  <rect x="290" y="380" width="400" height="40" rx="8" fill="#7f1d1d" stroke="#ef4444" stroke-width="1.5"/>
  <text x="490" y="405" fill="#fca5a5" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">⚡ SESSION RESET: PROCESS RESTARTED</text>

  <!-- Turn 2 Box -->
  <rect x="50" y="445" width="880" height="200" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
  <rect x="75" y="465" width="220" height="26" rx="6" fill="#7f1d1d"/>
  <text x="185" y="483" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 2: TURN 2 (NEW PROCESS)</text>
  <text x="75" y="520" fill="#ef4444" font-family="sans-serif" font-size="18" font-weight="bold">New Subprocess Has Zero Working Memory</text>
  <text x="75" y="550" fill="#cbd5e1" font-family="sans-serif" font-size="14">Assumes instructions survive across conversational turns.</text>
  <rect x="75" y="570" width="830" height="50" rx="8" fill="#1e293b"/>
  <text x="95" y="600" fill="#ef4444" font-family="monospace" font-size="13">✕ Defect: Modifies production files violating clean architecture limits</text>

  <!-- Deadlock Box -->
  <path d="M 490 645 L 490 700" stroke="#ef4444" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,700 490,715 497,700" fill="#ef4444"/>

  <rect x="50" y="725" width="880" height="240" rx="14" fill="#1e1b4b" stroke="#ef4444" stroke-width="2"/>
  <rect x="75" y="745" width="210" height="26" rx="6" fill="#7f1d1d"/>
  <text x="180" y="763" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 3: PIPELINE DEADLOCK</text>
  <text x="75" y="800" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Automated CI Regression Gate Blocks Delivery</text>
  <text x="75" y="830" fill="#cbd5e1" font-family="sans-serif" font-size="14">Developer must manually diagnose why agent broke existing boundaries.</text>
  <rect x="75" y="855" width="830" height="85" rx="8" fill="#0f172a"/>
  <text x="95" y="885" fill="#f59e0b" font-family="monospace" font-size="13">Root Cause: Conversational context is non-durable</text>
  <text x="95" y="915" fill="#22c55e" font-family="monospace" font-size="13">Required: Enforce declarative rules on every invocation</text>
"""
    elif beat_num == 3:
        # Beat 3: Mechanism - Ephemeral RAM vs Persistent Disk
        accent, badge = "#38bdf8", f"{fam_label} // ARCHITECTURAL MECHANISM"
        body = f"""
  <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">Ephemeral Memory vs Persistent Storage</text>
  <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Why large language models maintain zero state across restarts</text>

  <!-- Top Container: Volatile RAM -->
  <rect x="50" y="180" width="880" height="320" rx="16" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
  <rect x="75" y="200" width="270" height="28" rx="6" fill="#7f1d1d"/>
  <text x="210" y="219" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">VOLATILE LAYER: EPHEMERAL RAM</text>

  <rect x="75" y="245" width="390" height="170" rx="10" fill="#1e293b" stroke="#334155" stroke-width="1.5"/>
  <text x="95" y="280" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Session A (Active Context)</text>
  <text x="95" y="315" fill="#38bdf8" font-family="sans-serif" font-size="13">• System Prompt in RAM</text>
  <text x="95" y="345" fill="#38bdf8" font-family="sans-serif" font-size="13">• Working Memory Active</text>
  <text x="95" y="375" fill="#22c55e" font-family="sans-serif" font-size="13">✓ Rules In Scope</text>

  <path d="M 480 330 L 535 330" stroke="#ef4444" stroke-width="3" stroke-dasharray="6 4"/>
  <polygon points="535,324 547,330 535,336" fill="#ef4444"/>

  <rect x="555" y="245" width="350" height="170" rx="10" fill="#1e1b4b" stroke="#ef4444" stroke-width="2"/>
  <text x="575" y="280" fill="#ef4444" font-family="sans-serif" font-size="16" font-weight="bold">Session B (New Process)</text>
  <text x="575" y="315" fill="#fca5a5" font-family="sans-serif" font-size="13">✕ RAM Cleared to 0 KB</text>
  <text x="575" y="345" fill="#fca5a5" font-family="sans-serif" font-size="13">✕ Context Forgotten</text>
  <text x="575" y="375" fill="#ef4444" font-family="sans-serif" font-size="13">✕ Zero State Persisted</text>

  <rect x="75" y="435" width="830" height="45" rx="8" fill="#1e1b4b"/>
  <text x="490" y="463" fill="#fca5a5" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">⚡ LLMs hold zero persistent state between requests without explicit loaders</text>

  <!-- Middle Divider: The Missing Bridge -->
  <path d="M 490 500 L 490 560" stroke="#38bdf8" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,560 490,575 497,560" fill="#38bdf8"/>
  <rect x="330" y="520" width="320" height="32" rx="6" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>
  <text x="490" y="541" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">EXPLICIT INJECTION REQUIRED</text>

  <!-- Bottom Container: Persistent Disk -->
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
"""
    elif beat_num == 4:
        # Beat 4: Verified Remedy - Closed-Loop Injection Pipeline
        accent, badge = "#22c55e", f"{fam_label} // VERIFIED REMEDY"
        body = f"""
  <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">Closed-Loop Contract Injection</text>
  <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Deterministic repository injection for autonomous coding agents</text>

  <!-- Step 1: Immutable Contract -->
  <rect x="50" y="180" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
  <rect x="75" y="200" width="220" height="26" rx="6" fill="#14532d"/>
  <text x="185" y="218" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 1: IMMUTABLE CONTRACT</text>
  <text x="75" y="255" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">AGENTS.md at Repository Root</text>
  <text x="75" y="285" fill="#38bdf8" font-family="monospace" font-size="13">Enforces Clean Architecture: Submodules &lt; 450 lines, max 800</text>
  <circle cx="880" cy="245" r="14" fill="#14532d"/>
  <text x="880" y="252" fill="#86efac" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>

  <!-- Arrow 1 -> 2 -->
  <path d="M 490 325 L 490 370" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,370 490,385 497,370" fill="#22c55e"/>

  <!-- Step 2: Automated Preflight Gate -->
  <rect x="50" y="385" width="880" height="150" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
  <rect x="75" y="405" width="230" height="26" rx="6" fill="#14532d"/>
  <text x="190" y="423" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 2: PREFLIGHT SCOPE GATE</text>
  <text x="75" y="460" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Automated Gate Validates Task Boundaries</text>
  <text x="75" y="490" fill="#cbd5e1" font-family="sans-serif" font-size="14">Loads policy before allowing code edits or file modifications.</text>
  <circle cx="880" cy="455" r="14" fill="#14532d"/>
  <text x="880" y="462" fill="#86efac" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>

  <!-- Arrow 2 -> 3 -->
  <path d="M 490 535 L 490 580" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,580 490,595 497,580" fill="#22c55e"/>

  <!-- Step 3: Prompt Injection -->
  <rect x="50" y="595" width="880" height="160" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
  <rect x="75" y="615" width="230" height="26" rx="6" fill="#1e293b"/>
  <text x="190" y="633" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 3: SYSTEM PROMPT INJECTION</text>
  <text x="75" y="670" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">Inject Rules Into Every Spawned Subprocess</text>
  <text x="75" y="700" fill="#cbd5e1" font-family="sans-serif" font-size="14">Agent startup harness automatically injects instructions into system prompt.</text>
  <circle cx="880" cy="670" r="14" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
  <text x="880" y="676" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">✓</text>

  <!-- Arrow 3 -> 4 -->
  <path d="M 490 755 L 490 800" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,800 490,815 497,800" fill="#22c55e"/>

  <!-- Step 4: Autonomous Loop -->
  <rect x="50" y="815" width="880" height="150" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2.5"/>
  <rect x="75" y="835" width="220" height="26" rx="6" fill="#14532d"/>
  <text x="185" y="853" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 4: EXECUTION WITH GUARDRAILS</text>
  <text x="75" y="890" fill="#22c55e" font-family="sans-serif" font-size="18" font-weight="bold">Guaranteed Deterministic Boundary Compliance</text>
  <text x="75" y="920" fill="#cbd5e1" font-family="sans-serif" font-size="14">Agent delivers verified code with zero boundary violations across sessions.</text>
  <circle cx="880" cy="890" r="14" fill="#22c55e"/>
  <text x="880" y="897" fill="#0b1120" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✓</text>
"""
    elif beat_num == 5:
        # Beat 5: Verification Checklist - Automated Local Assertions
        accent, badge = "#22c55e", f"{fam_label} // VERIFICATION CHECKLIST"
        body = f"""
  <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">Local Automated Verification Gate</text>
  <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Asserting contract rule compliance before any git commit</text>

  <!-- Check 1 -->
  <rect x="50" y="180" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
  <circle cx="95" cy="235" r="20" fill="#22c55e"/>
  <text x="95" y="243" fill="#0b1120" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">✓</text>
  <text x="135" y="225" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">1. Subprocess Acknowledges AGENTS.md</text>
  <text x="135" y="255" fill="#94a3b8" font-family="sans-serif" font-size="14">Spawned agent explicitly reads and echoes active architectural boundaries.</text>
  <text x="135" y="285" fill="#22c55e" font-family="monospace" font-size="13">PASS: Boundary acknowledgment verified in session trace</text>

  <!-- Flow Arrow -->
  <path d="M 490 325 L 490 370" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,370 490,385 497,370" fill="#22c55e"/>

  <!-- Check 2 -->
  <rect x="50" y="385" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
  <circle cx="95" cy="440" r="20" fill="#22c55e"/>
  <text x="95" y="448" fill="#0b1120" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">✓</text>
  <text x="135" y="430" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">2. Hermetic Test Suite Passes Cleanly</text>
  <text x="135" y="460" fill="#94a3b8" font-family="sans-serif" font-size="14">Pytest executes contract assertions in isolated temporary sandbox.</text>
  <text x="135" y="490" fill="#22c55e" font-family="monospace" font-size="13">PASS: pytest tests/ -q (53 passed, 0 failures)</text>

  <!-- Flow Arrow -->
  <path d="M 490 530 L 490 575" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,575 490,590 497,575" fill="#22c55e"/>

  <!-- Check 3 -->
  <rect x="50" y="590" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
  <circle cx="95" cy="645" r="20" fill="#22c55e"/>
  <text x="95" y="653" fill="#0b1120" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">✓</text>
  <text x="135" y="635" fill="#f8fafc" font-family="sans-serif" font-size="18" font-weight="bold">3. Zero Silent Regressions Across Clean Restarts</text>
  <text x="135" y="665" fill="#94a3b8" font-family="sans-serif" font-size="14">Verify state persistence test passes deterministically on clean checkout.</text>
  <text x="135" y="695" fill="#22c55e" font-family="monospace" font-size="13">PASS: Process reset retains all required state</text>

  <!-- Flow Arrow -->
  <path d="M 490 735 L 490 780" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="483,780 490,795 497,780" fill="#22c55e"/>

  <!-- Approval Gate -->
  <rect x="50" y="795" width="880" height="170" rx="14" fill="#14532d" stroke="#22c55e" stroke-width="2.5"/>
  <text x="490" y="845" fill="#86efac" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">DELIVERY GATE: GIT COMMIT APPROVED</text>
  <text x="490" y="880" fill="#ffffff" font-family="sans-serif" font-size="15" text-anchor="middle">All local architectural verifications passed. Ready for review.</text>
  <rect x="240" y="905" width="500" height="36" rx="8" fill="#0f172a"/>
  <text x="490" y="928" fill="#22c55e" font-family="monospace" font-size="13" text-anchor="middle">git commit -m "feat: verified contract persistence"</text>
"""
    else:
        # Beat 6: Production Summary - End-to-End Persistence Pipeline
        accent, badge = "#38bdf8", f"{fam_label} // PRODUCTION SUMMARY"
        body = f"""
  <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">End-to-End Production Persistence Flow</text>
  <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Complete architectural flow for resilient AI agent pipelines</text>

  <!-- Architecture Flow Pipeline Box -->
  <rect x="50" y="180" width="880" height="520" rx="16" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>

  <!-- Stage A: Repo Spec -->
  <rect x="80" y="215" width="820" height="80" rx="10" fill="#1e293b"/>
  <circle cx="120" cy="255" r="16" fill="#38bdf8"/>
  <text x="120" y="261" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">1</text>
  <text x="155" y="245" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Repository Specification Layer</text>
  <text x="155" y="272" fill="#94a3b8" font-family="sans-serif" font-size="13">Tracked AGENTS.md contract and clean architecture boundary schemas.</text>

  <!-- Flow Arrow -->
  <path d="M 490 295 L 490 325" stroke="#38bdf8" stroke-width="2.5"/>
  <polygon points="485,325 490,335 495,325" fill="#38bdf8"/>

  <!-- Stage B: Preflight Hook -->
  <rect x="80" y="335" width="820" height="80" rx="10" fill="#1e293b"/>
  <circle cx="120" cy="375" r="16" fill="#38bdf8"/>
  <text x="120" y="381" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">2</text>
  <text x="155" y="365" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Automated Preflight Scope Gate</text>
  <text x="155" y="392" fill="#94a3b8" font-family="sans-serif" font-size="13">Compiles and injects repo rules into every agent subprocess on startup.</text>

  <!-- Flow Arrow -->
  <path d="M 490 415 L 490 445" stroke="#38bdf8" stroke-width="2.5"/>
  <polygon points="485,445 490,455 495,445" fill="#38bdf8"/>

  <!-- Stage C: Execution Loop -->
  <rect x="80" y="455" width="820" height="80" rx="10" fill="#1e293b"/>
  <circle cx="120" cy="495" r="16" fill="#38bdf8"/>
  <text x="120" y="501" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">3</text>
  <text x="155" y="485" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Hermetic Execution &amp; Testing</text>
  <text x="155" y="512" fill="#94a3b8" font-family="sans-serif" font-size="13">Autonomous coding loop executes within strict boundary constraints.</text>

  <!-- Flow Arrow -->
  <path d="M 490 535 L 490 565" stroke="#22c55e" stroke-width="2.5"/>
  <polygon points="485,565 490,575 495,565" fill="#22c55e"/>

  <!-- Stage D: CI Gate -->
  <rect x="80" y="575" width="820" height="95" rx="10" fill="#14532d"/>
  <circle cx="120" cy="622" r="16" fill="#22c55e"/>
  <text x="120" y="628" fill="#0f172a" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">4</text>
  <text x="155" y="612" fill="#86efac" font-family="sans-serif" font-size="16" font-weight="bold">Continuous Integration Gate</text>
  <text x="155" y="640" fill="#ffffff" font-family="sans-serif" font-size="13">Re-verifies contract tests across fresh process checkouts.</text>

  <!-- Bottom Core Principle Banner -->
  <rect x="50" y="730" width="880" height="235" rx="16" fill="#1e1b4b" stroke="#38bdf8" stroke-width="2"/>
  <text x="490" y="775" fill="#38bdf8" font-family="sans-serif" font-size="16" font-weight="bold" text-anchor="middle">THE CORE ENGINEERING PRINCIPLE</text>
  <text x="490" y="820" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">Never Trust Conversational Memory.</text>
  <text x="490" y="855" fill="#cbd5e1" font-family="sans-serif" font-size="16" text-anchor="middle">Always enforce deterministic state persistence across sessions in code and CI.</text>

  <rect x="90" y="885" width="800" height="55" rx="10" fill="#0f172a"/>
  <text x="490" y="918" fill="#22c55e" font-family="monospace" font-size="14" text-anchor="middle">assert agent_session.persisted_state == GROUND_TRUTH</text>
"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w}" height="{h}">
  <rect width="{w}" height="{h}" fill="#0b1120"/>
  <!-- Top Accent Stage Badge -->
  <rect x="50" y="35" width="380" height="40" rx="10" fill="#1e293b" stroke="{accent}" stroke-width="2"/>
  <text x="240" y="61" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{badge}</text>
  <text x="930" y="61" fill="#64748b" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="end">STAGE {beat_num} OF {total_beats}</text>
{body}
  <!-- Bottom Brand Footer -->
  <rect x="50" y="1005" width="880" height="55" rx="10" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="490" y="1038" fill="#e2e8f0" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">Practical AI Agent Engineering — Hermetic Verification Pipeline</text>
</svg>"""


def _generate_horizontal_svg(fam_label: str, safe_title: str, beat_num: int, total_beats: int) -> str:
    """Generate 16:9 horizontal fallback."""
    accent = "#ef4444" if beat_num in (1, 2) else "#22c55e" if beat_num in (4, 5) else "#38bdf8"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">
  <rect width="960" height="540" fill="#0b1120"/>
  <rect x="40" y="30" width="340" height="36" rx="8" fill="#1e293b" stroke="{accent}" stroke-width="1.5"/>
  <text x="210" y="53" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{fam_label} // STAGE {beat_num}</text>
  <rect x="60" y="110" width="840" height="270" rx="16" fill="#0f172a" stroke="{accent}" stroke-width="2"/>
  <text x="90" y="170" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">{safe_title}</text>
  <text x="90" y="210" fill="#94a3b8" font-family="sans-serif" font-size="15">AI Agent Execution Pipeline Flow Diagram</text>
  <rect x="60" y="420" width="840" height="60" rx="12" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="480" y="455" fill="#e2e8f0" font-family="sans-serif" font-size="15" text-anchor="middle">Stage {beat_num} of {total_beats} — Practical AI Agent Engineering</text>
</svg>"""
