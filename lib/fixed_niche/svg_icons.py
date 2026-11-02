"""Vector SVG visual icons and architectural diagram components.

Provides pure-SVG vector graphics for AI agent engineering pipelines:
- Robot / Agent terminal icon
- MCP Server rack icon
- Circuit Breaker switch / lightning fuse icon
- Defense Shield icon
- Database / Storage cylinder icon
- Animated flow arrows with glowing signal pulses
"""
from __future__ import annotations


def render_agent_icon(x: int, y: int, size: int = 44, color: str = "#38bdf8") -> str:
    """Render a crisp Robot / Agent terminal vector icon at (x, y)."""
    scale = size / 44.0
    return f"""<g transform="translate({x}, {y}) scale({scale:.3f})">
    <rect x="2" y="8" width="40" height="32" rx="8" fill="#1e293b" stroke="{color}" stroke-width="2.5"/>
    <line x1="22" y1="2" x2="22" y2="8" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="22" cy="2" r="3" fill="{color}"/>
    <rect x="7" y="14" width="30" height="20" rx="4" fill="#0b1120" stroke="{color}" stroke-width="1.2" stroke-opacity="0.6"/>
    <path d="M 11 21 L 17 24 L 11 27" stroke="{color}" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    <line x1="20" y1="27" x2="28" y2="27" stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>
    <circle cx="33" cy="18" r="2" fill="{color}"/>
  </g>"""


def render_server_icon(x: int, y: int, size: int = 44, color: str = "#38bdf8") -> str:
    """Render an MCP Server rack vector icon at (x, y)."""
    scale = size / 44.0
    return f"""<g transform="translate({x}, {y}) scale({scale:.3f})">
    <rect x="2" y="3" width="40" height="11" rx="3" fill="#1e293b" stroke="{color}" stroke-width="2"/>
    <circle cx="8" cy="8.5" r="2" fill="#22c55e"/>
    <circle cx="14" cy="8.5" r="2" fill="{color}"/>
    <line x1="20" y1="8.5" x2="34" y2="8.5" stroke="{color}" stroke-width="1.8" stroke-dasharray="3 2"/>
    <rect x="2" y="17" width="40" height="11" rx="3" fill="#1e293b" stroke="{color}" stroke-width="2"/>
    <circle cx="8" cy="22.5" r="2" fill="#22c55e"/>
    <circle cx="14" cy="22.5" r="2" fill="{color}"/>
    <line x1="20" y1="22.5" x2="34" y2="22.5" stroke="{color}" stroke-width="1.8" stroke-dasharray="3 2"/>
    <rect x="2" y="31" width="40" height="11" rx="3" fill="#1e293b" stroke="{color}" stroke-width="2"/>
    <circle cx="8" cy="36.5" r="2" fill="#22c55e"/>
    <circle cx="14" cy="36.5" r="2" fill="{color}"/>
    <line x1="20" y1="36.5" x2="34" y2="36.5" stroke="{color}" stroke-width="1.8" stroke-dasharray="3 2"/>
  </g>"""


def render_breaker_icon(x: int, y: int, size: int = 44, color: str = "#ef4444") -> str:
    """Render a Circuit Breaker / lightning fuse vector icon at (x, y)."""
    scale = size / 44.0
    return f"""<g transform="translate({x}, {y}) scale({scale:.3f})">
    <rect x="3" y="2" width="38" height="40" rx="8" fill="#1e293b" stroke="{color}" stroke-width="2.5"/>
    <rect x="9" y="8" width="26" height="28" rx="4" fill="#0b1120" stroke="{color}" stroke-width="1.2" stroke-opacity="0.5"/>
    <path d="M 24 10 L 16 23 L 23 23 L 19 34 L 29 20 L 22 20 Z" fill="{color}" filter="url(#glow-cyan)"/>
    <circle cx="8" cy="7" r="2" fill="{color}"/>
    <circle cx="36" cy="37" r="2" fill="{color}"/>
  </g>"""


def render_shield_icon(x: int, y: int, size: int = 44, color: str = "#22c55e") -> str:
    """Render a Defense Shield verification vector icon at (x, y)."""
    scale = size / 44.0
    return f"""<g transform="translate({x}, {y}) scale({scale:.3f})">
    <path d="M 22 2 L 40 9 V 22 C 40 33 22 41 22 41 C 22 41 4 33 4 22 V 9 Z" fill="#1e293b" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>
    <path d="M 22 6 L 36 12 V 22 C 36 30 22 37 22 37 C 22 37 8 30 8 22 V 12 Z" fill="#0b1120" stroke="{color}" stroke-width="1" stroke-opacity="0.5"/>
    <path d="M 14 22 L 20 27 L 30 16" stroke="{color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  </g>"""


def render_database_icon(x: int, y: int, size: int = 44, color: str = "#38bdf8") -> str:
    """Render a Database / Storage cylinder vector icon at (x, y)."""
    scale = size / 44.0
    return f"""<g transform="translate({x}, {y}) scale({scale:.3f})">
    <ellipse cx="22" cy="10" rx="18" ry="6" fill="#1e293b" stroke="{color}" stroke-width="2.2"/>
    <path d="M 4 10 V 22 C 4 25.5 12 28 22 28 C 32 28 40 25.5 40 22 V 10" fill="#1e293b" stroke="{color}" stroke-width="2.2"/>
    <path d="M 4 22 V 34 C 4 37.5 12 40 22 40 C 32 40 40 37.5 40 34 V 22" fill="#1e293b" stroke="{color}" stroke-width="2.2"/>
    <ellipse cx="22" cy="22" rx="18" ry="5.5" fill="none" stroke="{color}" stroke-width="1.2" stroke-dasharray="3 2"/>
    <circle cx="10" cy="16" r="1.8" fill="#22c55e"/>
    <circle cx="10" cy="28" r="1.8" fill="#22c55e"/>
  </g>"""


def render_flow_arrow(
    arrow_id: str,
    step_order: int,
    y_start: int,
    y_end: int,
    x: int = 490,
    color: str = "#38bdf8",
    label: str = "",
    dashed: bool = False,
) -> str:
    """Render an animated architectural flow arrow with a glowing signal pulse."""
    dash_attr = ' stroke-dasharray="6 4"' if dashed else ""
    y_mid = (y_start + y_end) // 2
    label_markup = ""
    if label:
        lbl_w = max(110, len(label) * 9 + 24)
        label_markup = f"""
    <rect x="{x - lbl_w//2}" y="{y_mid - 11}" width="{lbl_w}" height="22" rx="6" fill="#0b1120" stroke="{color}" stroke-width="1.2"/>
    <text x="{x}" y="{y_mid + 4}" fill="{color}" font-family="monospace" font-size="10" font-weight="bold" text-anchor="middle">{label}</text>"""

    return f"""  <g id="{arrow_id}" class="flow-arrow" data-step-order="{step_order}">
    <path d="M {x} {y_start} L {x} {y_end - 10}" stroke="{color}" stroke-width="3" stroke-linecap="round"{dash_attr}/>
    <polygon points="{x - 7},{y_end - 10} {x},{y_end} {x + 7},{y_end - 10}" fill="{color}"/>
    <circle class="flow-pulse" cx="{x}" cy="{y_mid}" r="4.5" fill="{color}" filter="url(#glow-cyan)"/>{label_markup}
  </g>"""


def render_metric_gauge(
    cx: int,
    cy: int,
    r: int = 36,
    percentage: int = 95,
    label: str = "AVAILABILITY",
    value_str: str = "HEALTHY",
    color: str = "#22c55e",
) -> str:
    """Render a circular SVG telemetry gauge with a glowing arc."""
    circ = 2 * 3.14159 * r
    offset = circ * (1.0 - (percentage / 100.0))
    return f"""<g transform="translate({cx}, {cy})">
    <circle cx="0" cy="0" r="{r}" fill="#0b1120" stroke="#1e293b" stroke-width="7"/>
    <circle cx="0" cy="0" r="{r}" fill="none" stroke="{color}" stroke-width="7"
            stroke-dasharray="{circ:.1f}" stroke-dashoffset="{offset:.1f}"
            stroke-linecap="round" transform="rotate(-90)"/>
    <text x="0" y="5" fill="#f8fafc" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">{value_str}</text>
    <text x="0" y="{r + 18}" fill="{color}" font-family="monospace" font-size="10" font-weight="bold" text-anchor="middle">{label}</text>
  </g>"""


def render_circuit_switch(
    x: int,
    y: int,
    is_open: bool = True,
    color: str = "#ef4444",
    label: str = "TRIPPED: OPEN",
) -> str:
    """Render a physical circuit breaker relay schematic with animated lever."""
    arm = f'<line x1="20" y1="20" x2="48" y2="4" stroke="{color}" stroke-width="3.5" stroke-linecap="round"/>' if is_open else f'<line x1="20" y1="20" x2="56" y2="20" stroke="{color}" stroke-width="3.5" stroke-linecap="round"/>'
    spark = '<path d="M 40 10 L 48 18 L 44 20 L 52 26" stroke="#fbbf24" stroke-width="2" fill="none"/>' if is_open else ""
    return f"""<g transform="translate({x}, {y})">
    <rect x="0" y="0" width="150" height="64" rx="10" fill="#0f172a" stroke="{color}" stroke-width="2"/>
    <circle cx="20" cy="20" r="4.5" fill="#1e293b" stroke="{color}" stroke-width="2"/>
    <circle cx="56" cy="20" r="4.5" fill="#1e293b" stroke="{color}" stroke-width="2"/>
    {arm}
    {spark}
    <rect x="10" y="38" width="130" height="18" rx="4" fill="#1e293b"/>
    <text x="75" y="51" fill="{color}" font-family="monospace" font-size="9" font-weight="bold" text-anchor="middle">{label}</text>
  </g>"""


def render_state_machine(x: int, y: int, active_state: str = "OPEN") -> str:
    """Render a 3-state finite state machine showing CLOSED, OPEN, HALF-OPEN transitions."""
    states = [
        ("CLOSED", 60, "#22c55e", "Pass-Through"),
        ("OPEN", 220, "#ef4444", "Fast-Fail active"),
        ("HALF-OPEN", 380, "#f59e0b", "Probe Trial"),
    ]
    nodes = []
    for name, nx, col, sub in states:
        is_active = (name == active_state)
        sw = "3" if is_active else "1.5"
        fill = "#1e293b" if is_active else "#0f172a"
        nodes.append(f"""
    <g transform="translate({nx}, 42)">
      <circle cx="0" cy="0" r="28" fill="{fill}" stroke="{col}" stroke-width="{sw}"/>
      <text x="0" y="4" fill="#f8fafc" font-family="sans-serif" font-size="10" font-weight="bold" text-anchor="middle">{name}</text>
      <text x="0" y="44" fill="{col}" font-family="monospace" font-size="9" text-anchor="middle">{sub}</text>
    </g>""")
    connectors = """
    <path d="M 88 32 C 130 14 150 14 192 32" stroke="#ef4444" stroke-width="1.8" fill="none" stroke-dasharray="4 3"/>
    <polygon points="192,32 184,27 186,37" fill="#ef4444"/>
    <path d="M 248 32 C 290 14 310 14 352 32" stroke="#f59e0b" stroke-width="1.8" fill="none" stroke-dasharray="4 3"/>
    <polygon points="352,32 344,27 346,37" fill="#f59e0b"/>
    <path d="M 355 52 C 270 78 170 78 85 52" stroke="#22c55e" stroke-width="1.8" fill="none" stroke-dasharray="4 3"/>
    <polygon points="85,52 95,50 92,60" fill="#22c55e"/>"""
    return f"""<g transform="translate({x}, {y})">
    <rect x="0" y="0" width="440" height="105" rx="12" fill="#0b1120" stroke="#334155" stroke-width="1.5"/>
    <text x="220" y="18" fill="#94a3b8" font-family="monospace" font-size="10" font-weight="bold" text-anchor="middle">CIRCUIT BREAKER STATE MACHINE</text>
    {connectors}
    {''.join(nodes)}
  </g>"""
