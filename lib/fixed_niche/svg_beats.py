"""Architectural SVG beat renderers for Practical AI Agent Engineering.

Renders vertical (9:16) and horizontal (16:9) diagram beats with:
- Pure vector icons (Robot Agent, Server Rack, Circuit Breaker, Shield, Database)
- Mechanical circuit breaker relays and finite state machine diagrams
- Circular telemetry gauges and live system health arcs
- Connecting animated flow arrows with glowing signal pulses
- Voice synchronization via progressive step reveal classes
"""
from __future__ import annotations

from html import escape as html_escape
from typing import Dict

from lib.fixed_niche.svg_icons import (
    render_agent_icon,
    render_breaker_icon,
    render_circuit_switch,
    render_database_icon,
    render_flow_arrow,
    render_metric_gauge,
    render_server_icon,
    render_shield_icon,
    render_state_machine,
)


def _wrap_words_to_lines(words: list[str], max_chars: int) -> list[str]:
    """Greedy word wrapping helper."""
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip() if cur else w
        if cur and len(cand) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def _split_into_lines(text: str, max_chars: int) -> list[str]:
    """Split text into lines respecting '//' delimiters and max_chars limit."""
    clean = text.strip()
    if "//" in clean:
        parts = [p.strip() for p in clean.split("//", 1)]
        return [parts[0], parts[1]]
    if len(clean) <= max_chars:
        return [clean]
    return _wrap_words_to_lines(clean.split(), max_chars)


def render_wrapped_text(
    text: str,
    x: int,
    y: int,
    max_chars: int = 34,
    line_height: int = 22,
    font_size: int = 17,
    font_weight: str = "bold",
    fill: str = "#f8fafc",
    font_family: str = "sans-serif",
) -> str:
    """Render single-line or multi-line SVG text, wrapping at word/delimiter boundaries to prevent overlap."""
    lines = _split_into_lines(text, max_chars)
    if len(lines) <= 1:
        val = html_escape(lines[0]) if lines else ""
        return f'<text x="{x}" y="{y}" fill="{fill}" font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}">{val}</text>'

    visible_lines = lines[:3]
    y_offset = y - ((len(visible_lines) - 1) * line_height // 2)
    tspans = "".join(
        f'<tspan x="{x}" dy="{0 if idx == 0 else line_height}">{html_escape(ln)}</tspan>'
        for idx, ln in enumerate(visible_lines)
    )
    return f'<text x="{x}" y="{y_offset}" fill="{fill}" font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}">{tspans}</text>'


def _beat_1_content(p: str, fam_label: str, cfg: Dict[str, str]) -> tuple[str, str, str]:
    accent, badge = "#ef4444", f"{fam_label} // AI AGENT PIPELINE HOOK"
    hook_alert = cfg.get("hook_alert", "⚡ CRITICAL FAILURE // RECURRING BREAKDOWN")
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <rect x="470" y="41" width="460" height="28" rx="6" fill="#7f1d1d" stroke="#ef4444" stroke-width="1.5"/>
    <text x="700" y="60" fill="#fca5a5" font-family="sans-serif" font-size="11" font-weight="bold" text-anchor="middle">{hook_alert}</text>
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">AI Agent Execution Pipeline</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['hook_sub']}</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="170" width="880" height="135" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_agent_icon(75, 195, size=50, color="#38bdf8")}
    <rect x="145" y="190" width="190" height="26" rx="6" fill="#1e293b"/>
    <text x="240" y="208" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 1: DEVELOPER TASK</text>
    {render_wrapped_text(cfg['task_desc'], 145, 246, max_chars=36, line_height=20, font_size=16, fill="#f8fafc")}
    {render_circuit_switch(640, 190, is_open=False, color="#22c55e", label="STATE: CLOSED")}
    <circle cx="880" cy="235" r="15" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
    <text x="880" y="242" fill="#38bdf8" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✓</text>
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 305, 355, color="#38bdf8", label="DISPATCH TURN")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="355" width="880" height="155" rx="14" fill="#1e1b4b" stroke="#ef4444" stroke-width="2.5" stroke-dasharray="8 6"/>
    {render_breaker_icon(75, 380, size=50, color="#ef4444")}
    <rect x="145" y="375" width="210" height="26" rx="6" fill="#7f1d1d"/>
    <text x="250" y="393" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 2: FAILURE POINT</text>
    {render_wrapped_text(cfg['fail_title'], 145, 432, max_chars=24, line_height=20, font_size=17, fill="#ef4444")}
    {render_circuit_switch(500, 380, is_open=True, color="#ef4444", label="TRIPPED: OPEN")}
    {render_metric_gauge(740, 432, r=30, percentage=100, label="ERROR RATE", value_str="CRITICAL", color="#ef4444")}
    <circle cx="880" cy="432" r="15" fill="#7f1d1d" stroke="#ef4444" stroke-width="2"/>
    <text x="880" y="439" fill="#ef4444" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✕</text>
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 510, 560, color="#ef4444", label="DROPPED CONTEXT", dashed=True)}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="560" width="880" height="140" rx="14" fill="#0f172a" stroke="#f59e0b" stroke-width="2"/>
    {render_server_icon(75, 585, size=50, color="#f59e0b")}
    <rect x="145" y="580" width="220" height="26" rx="6" fill="#1e293b"/>
    <text x="255" y="598" fill="#f59e0b" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 3: AGENT REASONING</text>
    {render_wrapped_text(cfg['unanchored_title'], 145, 636, max_chars=24, line_height=20, font_size=16, fill="#f8fafc")}
    {render_metric_gauge(580, 630, r=30, percentage=15, label="THROUGHPUT", value_str="STALLED", color="#f59e0b")}
    {render_metric_gauge(740, 630, r=30, percentage=95, label="LATENCY", value_str="TIMEOUT", color="#ef4444")}
    <circle cx="880" cy="630" r="15" fill="#1e293b" stroke="#f59e0b" stroke-width="2"/>
    <text x="880" y="637" fill="#f59e0b" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">!</text>
  </g>

{render_flow_arrow(f"{p}flow-arrow-3", 6, 700, 750, color="#ef4444", label="REGRESSION DETECTED")}

  <g id="{p}flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="750" width="880" height="145" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
    {render_shield_icon(75, 775, size=50, color="#ef4444")}
    <rect x="145" y="770" width="225" height="26" rx="6" fill="#7f1d1d"/>
    <text x="257" y="788" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">OUTCOME: DELIVERY DEADLOCK</text>
    {render_wrapped_text("Multi-Turn Execution Halted", 145, 828, max_chars=24, font_size=17, fill="#f8fafc")}
    {render_circuit_switch(520, 775, is_open=True, color="#ef4444", label="CI GATE: REJECTED")}
    {render_metric_gauge(750, 822, r=30, percentage=0, label="CI PASS", value_str="BLOCKED", color="#ef4444")}
    <circle cx="880" cy="822" r="15" fill="#ef4444"/>
    <text x="880" y="829" fill="#ffffff" font-family="sans-serif" font-size="15" font-weight="bold" text-anchor="middle">✕</text>
  </g>
"""
    return accent, badge, body


def _beat_2_content(p: str, fam_label: str, cfg: Dict[str, str]) -> tuple[str, str, str]:
    accent, badge = "#f59e0b", f"{fam_label} // DEVELOPER IMPACT"
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['impact_title']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['impact_sub']}</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="170" width="880" height="140" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_agent_icon(75, 195, size=48, color="#38bdf8")}
    <rect x="145" y="190" width="220" height="26" rx="6" fill="#1e293b"/>
    <text x="255" y="208" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 1: CLIENT DISPATCH</text>
    {render_wrapped_text(cfg['task_desc'], 145, 246, max_chars=32, line_height=20, font_size=16, fill="#f8fafc")}
    {render_metric_gauge(750, 240, r=30, percentage=100, label="REQUEST", value_str="SENT", color="#38bdf8")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 310, 360, color="#f59e0b", label="FAILURE DETECTED")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="360" width="880" height="150" rx="14" fill="#0f172a" stroke="#ef4444" stroke-width="2"/>
    {render_breaker_icon(75, 385, size=48, color="#ef4444")}
    <rect x="145" y="380" width="220" height="26" rx="6" fill="#7f1d1d"/>
    <text x="255" y="398" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 2: UNANCHORED STATE</text>
    {render_wrapped_text(cfg['unanchored_title'], 145, 435, max_chars=24, line_height=20, font_size=17, fill="#ef4444")}
    {render_circuit_switch(520, 385, is_open=True, color="#ef4444", label="NO CIRCUIT BREAKER")}
    {render_metric_gauge(750, 435, r=30, percentage=100, label="RETRY BURDEN", value_str="CASCADE", color="#ef4444")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 510, 560, color="#ef4444", label="DELIVERY BLOCKED")}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="560" width="880" height="190" rx="14" fill="#1e1b4b" stroke="#ef4444" stroke-width="2"/>
    {render_shield_icon(75, 585, size=48, color="#ef4444")}
    <rect x="145" y="580" width="220" height="26" rx="6" fill="#7f1d1d"/>
    <text x="255" y="598" fill="#fca5a5" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">PHASE 3: PIPELINE DEADLOCK</text>
    {render_wrapped_text("Automated CI Regression Gate Blocks Delivery", 145, 635, max_chars=30, line_height=20, font_size=16, fill="#f8fafc")}
    {render_state_machine(145, 660, active_state="OPEN")}
    {render_metric_gauge(750, 655, r=32, percentage=0, label="AVAILABILITY", value_str="OFFLINE", color="#ef4444")}
  </g>
"""
    return accent, badge, body


def _beat_3_content(p: str, fam_label: str, cfg: Dict[str, str]) -> tuple[str, str, str]:
    accent, badge = "#38bdf8", f"{fam_label} // ARCHITECTURAL MECHANISM"
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['mech_title']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['mech_sub']}</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="170" width="880" height="145" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_agent_icon(80, 195, size=50, color="#38bdf8")}
    <text x="155" y="215" fill="#38bdf8" font-family="monospace" font-size="13" font-weight="bold">TOPOLOGY NODE: CLIENT</text>
    {render_wrapped_text("MCP Client Autonomous Dispatcher", 155, 245, max_chars=28, line_height=20, font_size=17, fill="#f8fafc")}
    {render_metric_gauge(750, 242, r=32, percentage=100, label="CLIENT STATUS", value_str="ACTIVE", color="#38bdf8")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 315, 365, color="#38bdf8", label="FAULT ISOLATION BUS")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="365" width="880" height="210" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_breaker_icon(80, 420, size=50, color="#38bdf8")}
    <text x="155" y="405" fill="#38bdf8" font-family="monospace" font-size="13" font-weight="bold">CIRCUIT BREAKER CORE RELAY</text>
    {render_circuit_switch(155, 425, is_open=False, color="#22c55e", label="MONITORING: CLOSED")}
    {render_state_machine(360, 425, active_state="CLOSED")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 575, 625, color="#38bdf8", label="FAST FAIL BYPASS")}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="625" width="880" height="150" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_server_icon(80, 655, size=50, color="#22c55e")}
    <text x="155" y="670" fill="#22c55e" font-family="monospace" font-size="13" font-weight="bold">ISOLATED BACKEND TOOL</text>
    {render_wrapped_text("Protected Microservice / MCP Tool", 155, 700, max_chars=28, line_height=20, font_size=17, fill="#f8fafc")}
    {render_metric_gauge(750, 700, r=32, percentage=99, label="AVAILABILITY", value_str="HEALTHY", color="#22c55e")}
  </g>
"""
    return accent, badge, body


def _beat_4_content(p: str, fam_label: str, cfg: Dict[str, str]) -> tuple[str, str, str]:
    accent, badge = "#22c55e", f"{fam_label} // VERIFIED REMEDY"
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['remedy_title']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['remedy_sub']}</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="170" width="880" height="145" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_breaker_icon(75, 195, size=48, color="#ef4444")}
    <rect x="145" y="190" width="230" height="26" rx="6" fill="#14532d"/>
    <text x="260" y="208" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 1: FAULT DETECTED</text>
    {render_wrapped_text("Circuit Trips on Consecutive Errors", 145, 246, max_chars=24, line_height=20, font_size=16, fill="#f8fafc")}
    {render_circuit_switch(520, 190, is_open=True, color="#ef4444", label="TRIPPED: OPEN")}
    {render_metric_gauge(750, 242, r=30, percentage=100, label="CIRCUIT STATE", value_str="OPEN", color="#ef4444")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 315, 365, color="#22c55e", label="FAST FAIL BYPASS")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="365" width="880" height="150" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_database_icon(75, 390, size=48, color="#22c55e")}
    <rect x="145" y="385" width="240" height="26" rx="6" fill="#14532d"/>
    <text x="265" y="403" fill="#86efac" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 2: INSTANT FALLBACK CACHE</text>
    {render_wrapped_text("Cached Response Returned in Sub-Millisecond", 145, 440, max_chars=24, line_height=20, font_size=16, fill="#f8fafc")}
    {render_metric_gauge(550, 440, r=30, percentage=100, label="LATENCY", value_str="FAST", color="#22c55e")}
    {render_metric_gauge(750, 440, r=30, percentage=0, label="BACKEND LOAD", value_str="SHIELDED", color="#38bdf8")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 515, 565, color="#22c55e", label="RECOVERY TIMER")}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="565" width="880" height="180" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_shield_icon(75, 590, size=48, color="#38bdf8")}
    <rect x="145" y="585" width="250" height="26" rx="6" fill="#1e293b"/>
    <text x="270" y="603" fill="#38bdf8" font-family="sans-serif" font-size="12" font-weight="bold" text-anchor="middle">STEP 3: AUTOMATIC RECOVERY</text>
    {render_state_machine(145, 625, active_state="HALF-OPEN")}
    {render_metric_gauge(750, 655, r=32, percentage=100, label="STABILITY", value_str="STABLE", color="#22c55e")}
  </g>
"""
    return accent, badge, body


def _beat_5_content(p: str, fam_label: str, cfg: Dict[str, str]) -> tuple[str, str, str]:
    accent, badge = "#22c55e", f"{fam_label} // VERIFICATION CHECKLIST"
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">Local Automated Verification Gate</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Asserting contract rule compliance before any git commit</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="170" width="880" height="140" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_shield_icon(75, 195, size=46, color="#22c55e")}
    {render_wrapped_text(cfg['check1'], 145, 215, max_chars=30, line_height=20, font_size=16, fill="#f8fafc")}
    <text x="145" y="245" fill="#86efac" font-family="monospace" font-size="12">✓ PASS: Boundary verified in session trace</text>
    {render_metric_gauge(750, 240, r=30, percentage=100, label="GATE 1", value_str="PASS", color="#22c55e")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 310, 360, color="#22c55e", label="TRACE PASS")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="360" width="880" height="140" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_server_icon(75, 385, size=46, color="#22c55e")}
    {render_wrapped_text(cfg['check2'], 145, 405, max_chars=30, line_height=20, font_size=16, fill="#f8fafc")}
    <text x="145" y="435" fill="#86efac" font-family="monospace" font-size="12">✓ PASS: Isolated verification suite passed</text>
    {render_metric_gauge(750, 430, r=30, percentage=100, label="GATE 2", value_str="PASS", color="#22c55e")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 500, 550, color="#22c55e", label="TESTS PASS")}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="550" width="880" height="140" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_database_icon(75, 575, size=46, color="#22c55e")}
    {render_wrapped_text(cfg['check3'], 145, 595, max_chars=30, line_height=20, font_size=16, fill="#f8fafc")}
    <text x="145" y="625" fill="#86efac" font-family="monospace" font-size="12">✓ {cfg['pass_check3']}</text>
    {render_metric_gauge(750, 620, r=30, percentage=100, label="GATE 3", value_str="PASS", color="#22c55e")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-3", 6, 690, 740, color="#22c55e", label="ALL VERIFIED")}

  <g id="{p}flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="740" width="880" height="150" rx="14" fill="#14532d" stroke="#22c55e" stroke-width="2.5"/>
    <text x="490" y="785" fill="#86efac" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">DELIVERY GATE: GIT COMMIT APPROVED</text>
    <text x="490" y="818" fill="#ffffff" font-family="sans-serif" font-size="15" text-anchor="middle">All local architectural verifications passed cleanly. Ready for review.</text>
    {render_circuit_switch(415, 830, is_open=False, color="#22c55e", label="CI PASS: VERIFIED")}
  </g>
"""
    return accent, badge, body


def _beat_6_contract_content(p: str, fam_label: str, cfg: Dict[str, str]) -> tuple[str, str, str]:
    accent, badge = "#8b5cf6", f"{fam_label} // CONTRACT ASSERTION"
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">{cfg['contract_name']}</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">{cfg['contract_desc']}</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="180" width="880" height="170" rx="16" fill="#0f172a" stroke="#8b5cf6" stroke-width="2"/>
    {render_shield_icon(75, 205, size=46, color="#8b5cf6")}
    <text x="145" y="222" fill="#a78bfa" font-family="sans-serif" font-size="15" font-weight="bold">CONTRACT RULE 1</text>
    {render_wrapped_text(cfg['check1'], 145, 255, max_chars=28, line_height=20, font_size=18, fill="#f8fafc")}
    {render_metric_gauge(750, 265, r=30, percentage=100, label="RULE 1", value_str="VERIFIED", color="#8b5cf6")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 350, 400, color="#8b5cf6", label="RULE 1 PASS")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="400" width="880" height="170" rx="16" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_server_icon(75, 425, size=46, color="#22c55e")}
    <text x="145" y="442" fill="#86efac" font-family="sans-serif" font-size="15" font-weight="bold">CONTRACT RULE 2</text>
    {render_wrapped_text(cfg['check2'], 145, 475, max_chars=28, line_height=20, font_size=18, fill="#f8fafc")}
    {render_metric_gauge(750, 485, r=30, percentage=100, label="RULE 2", value_str="VERIFIED", color="#22c55e")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 570, 620, color="#8b5cf6", label="RULE 2 PASS")}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="620" width="880" height="180" rx="16" fill="#1e1b4b" stroke="#8b5cf6" stroke-width="2"/>
    {render_database_icon(75, 645, size=46, color="#8b5cf6")}
    <text x="145" y="660" fill="#a78bfa" font-family="sans-serif" font-size="15" font-weight="bold">ASSERTION GATE STATUS</text>
    {render_wrapped_text(cfg['pass_check3'], 145, 695, max_chars=28, line_height=20, font_size=18, fill="#f8fafc")}
    {render_metric_gauge(750, 710, r=30, percentage=100, label="ASSERTION", value_str="PASS", color="#8b5cf6")}
  </g>
"""
    return accent, badge, body


def _beat_default_content(p: str, fam_label: str) -> tuple[str, str, str]:
    accent, badge = "#38bdf8", f"{fam_label} // PRODUCTION SUMMARY"
    body = f"""  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <text x="50" y="115" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="bold">End-to-End Production Pipeline Flow</text>
    <text x="50" y="145" fill="#94a3b8" font-family="sans-serif" font-size="15">Complete architectural flow for resilient AI agent pipelines</text>
  </g>

  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="50" y="170" width="880" height="105" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_database_icon(75, 185, size=42, color="#38bdf8")}
    <text x="145" y="210" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Repository Specification Layer</text>
    <text x="145" y="235" fill="#94a3b8" font-family="monospace" font-size="11">Tracked AGENTS.md Contract</text>
    {render_metric_gauge(750, 222, r=26, percentage=100, label="STAGE 1", value_str="READY", color="#38bdf8")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-1", 2, 275, 315, color="#38bdf8")}

  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="50" y="315" width="880" height="105" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_shield_icon(75, 330, size=42, color="#38bdf8")}
    <text x="145" y="355" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Automated Preflight Scope Gate</text>
    <text x="145" y="380" fill="#94a3b8" font-family="monospace" font-size="11">Compiles Preflight Invariants</text>
    {render_metric_gauge(750, 367, r=26, percentage=100, label="STAGE 2", value_str="GATED", color="#38bdf8")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-2", 4, 420, 460, color="#38bdf8")}

  <g id="{p}flow-step-3" class="flow-step" data-step-order="5">
    <rect x="50" y="460" width="880" height="105" rx="14" fill="#0f172a" stroke="#38bdf8" stroke-width="2"/>
    {render_agent_icon(75, 475, size=42, color="#38bdf8")}
    <text x="145" y="500" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">Hermetic Execution &amp; Testing</text>
    <text x="145" y="525" fill="#94a3b8" font-family="monospace" font-size="11">Autonomous Loop in Sandbox</text>
    {render_metric_gauge(750, 512, r=26, percentage=100, label="STAGE 3", value_str="PASS", color="#38bdf8")}
  </g>

{render_flow_arrow(f"{p}flow-arrow-3", 6, 565, 605, color="#22c55e")}

  <g id="{p}flow-step-4" class="flow-step" data-step-order="7">
    <rect x="50" y="605" width="880" height="105" rx="14" fill="#0f172a" stroke="#22c55e" stroke-width="2"/>
    {render_server_icon(75, 620, size=42, color="#22c55e")}
    <text x="145" y="645" fill="#86efac" font-family="sans-serif" font-size="16" font-weight="bold">Continuous Integration Gate</text>
    <text x="145" y="670" fill="#86efac" font-family="monospace" font-size="11">Deterministic Zero-Defect Release</text>
    {render_metric_gauge(750, 657, r=26, percentage=100, label="STAGE 4", value_str="RELEASE", color="#22c55e")}
  </g>

  <g id="{p}flow-cta-banner" class="flow-cta-banner">
    <rect x="50" y="730" width="880" height="230" rx="16" fill="url(#cta-bg-grad)" stroke="#38bdf8" stroke-width="2.5" filter="url(#glow-cyan)"/>
    <rect x="80" y="748" width="310" height="26" rx="8" fill="#0f172a" stroke="#38bdf8" stroke-width="1.5"/>
    <text x="235" y="766" fill="#38bdf8" font-family="sans-serif" font-size="11" font-weight="bold" text-anchor="middle">CALL TO ACTION // ARCHITECTURAL BLUEPRINT</text>
    <text x="490" y="802" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle">What do you think? Let me know below 👇</text>
    <text x="490" y="826" fill="#38bdf8" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">Follow for Daily Agent Engineering Patterns</text>
    <rect x="110" y="842" width="760" height="42" rx="10" fill="url(#star-btn-grad)" stroke="#fbbf24" stroke-width="2" filter="url(#glow-gold)"/>
    <text x="490" y="868" fill="#fbbf24" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">★ Star the Repository on GitHub</text>
    <text x="490" y="910" fill="#94a3b8" font-family="sans-serif" font-size="12" text-anchor="middle">Defensive Contracts • Schema Validation • Hermetic Reproduction</text>
  </g>
"""
    return accent, badge, body


def build_vertical_beat(
    beat_num: int,
    total_beats: int,
    fam_label: str,
    cfg: Dict[str, str],
    prefix: str = "",
) -> tuple[str, str, str]:
    """Build the accent color, header badge, and SVG body elements for a vertical pipeline beat."""
    if beat_num == 1:
        return _beat_1_content(prefix, fam_label, cfg)
    if beat_num == 2:
        return _beat_2_content(prefix, fam_label, cfg)
    if beat_num == 3:
        return _beat_3_content(prefix, fam_label, cfg)
    if beat_num == 4:
        return _beat_4_content(prefix, fam_label, cfg)
    if beat_num == 5:
        return _beat_5_content(prefix, fam_label, cfg)
    if beat_num == 6 and total_beats == 7:
        return _beat_6_contract_content(prefix, fam_label, cfg)
    return _beat_default_content(prefix, fam_label)


def generate_horizontal_svg(
    fam_label: str,
    safe_title: str,
    beat_num: int,
    total_beats: int,
    style_block: str = "",
    prefix: str = "",
) -> str:
    """Generate 16:9 horizontal fallback with progressive step structure and vector icons."""
    p = prefix
    if beat_num in (1, 2):
        accent = "#ef4444"
    elif beat_num in (4, 5):
        accent = "#22c55e"
    else:
        accent = "#38bdf8"
    icon = render_agent_icon(80, 110, 48, accent) if beat_num == 1 else render_server_icon(80, 110, 48, accent)
    switch = render_circuit_switch(650, 120, is_open=(beat_num in (1, 2)), color=accent)
    gauge = render_metric_gauge(500, 150, r=32, percentage=95 if beat_num > 2 else 15, label="AVAILABILITY", value_str="HEALTHY" if beat_num > 2 else "DEGRADED", color=accent)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">
  <defs>
{style_block}
  </defs>
  <rect width="960" height="540" fill="#0b1120"/>
  <g id="{p}flow-header" class="flow-step flow-header" data-step-order="0">
    <rect x="40" y="30" width="340" height="36" rx="8" fill="#1e293b" stroke="{accent}" stroke-width="1.5"/>
    <text x="210" y="53" fill="{accent}" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle">{fam_label} // STAGE {beat_num}</text>
  </g>
  <g id="{p}flow-step-1" class="flow-step" data-step-order="1">
    <rect x="60" y="90" width="840" height="230" rx="16" fill="#0f172a" stroke="{accent}" stroke-width="2"/>
    {icon}
    <text x="145" y="145" fill="#f8fafc" font-family="sans-serif" font-size="20" font-weight="bold">{safe_title}</text>
    <text x="145" y="185" fill="#94a3b8" font-family="sans-serif" font-size="15">AI Agent Execution Pipeline Flow Diagram</text>
    {switch}
    {gauge}
  </g>
{render_flow_arrow(f"{p}flow-arrow-1", 2, 330, 390, x=480, color=accent)}
  <g id="{p}flow-step-2" class="flow-step" data-step-order="3">
    <rect x="60" y="410" width="840" height="80" rx="12" fill="#1e293b" stroke="#334155" stroke-width="1"/>
    <text x="480" y="455" fill="#e2e8f0" font-family="sans-serif" font-size="15" text-anchor="middle">Stage {beat_num} of {total_beats} — Practical AI Agent Engineering</text>
  </g>
</svg>"""
