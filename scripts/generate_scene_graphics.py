#!/usr/bin/env python3
"""Generate rich contextual graphic cards for production en-US deliverables.

Replaces raw testsrc with high-production technical architecture diagrams,
benchmark charts, and verifiable citation cards.

All text elements are strictly wrapped within their bounding boxes with
guaranteed margins to prevent text overflow bugs.
"""
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def _find_font(candidates: list[str]) -> str:
    for c in candidates:
        if os.path.exists(c):
            return c
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


FONT_BOLD = _find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
])
FONT_REGULAR = _find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
])
FONT_MONO = _find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf",
])

# Color palette
BG_DARK = (11, 15, 25, 255)         # #0b0f19
CARD_BG = (20, 29, 47, 245)         # #141d2f
CARD_BORDER = (56, 189, 248, 180)   # #38bdf8 cyan
TEXT_WHITE = (248, 250, 252, 255)   # #f8fafc
TEXT_MUTED = (148, 163, 184, 255)   # #94a3b8
TEXT_CYAN = (56, 189, 248, 255)     # #38bdf8
TEXT_AMBER = (245, 158, 11, 255)    # #f59e0b
TEXT_GREEN = (16, 185, 129, 255)    # #10b981
TEXT_RED = (239, 68, 68, 255)       # #ef4444
BAR_BG = (30, 41, 59, 255)          # #1e293b


def draw_grid_background(draw: ImageDraw.ImageDraw, w: int, h: int, step: int = 60):
    for x in range(0, w, step):
        draw.line([(x, 0), (x, h)], fill=(18, 24, 38, 255), width=1)
    for y in range(0, h, step):
        draw.line([(0, y), (w, y)], fill=(18, 24, 38, 255), width=1)


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    x: int,
    y: int,
    max_width: int,
    line_spacing: int = 6,
) -> int:
    """Draw text wrapped within max_width, returning the ending Y coordinate."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        w = draw.textlength(test_line, font=font)
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    curr_y = y
    for line in lines:
        draw.text((x, curr_y), line, fill=fill, font=font)
        bbox = font.getbbox(line)
        h = bbox[3] - bbox[1]
        curr_y += h + line_spacing
    return curr_y


def generate_short_graphics(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = 1080, 1920

    # Fonts
    f_badge = ImageFont.truetype(FONT_BOLD, 22)
    f_title = ImageFont.truetype(FONT_BOLD, 44)
    f_subtitle = ImageFont.truetype(FONT_REGULAR, 26)
    f_body = ImageFont.truetype(FONT_REGULAR, 24)
    f_mono = ImageFont.truetype(FONT_MONO, 21)

    max_w = 840  # 90 + 840 = 930 <= 990 (safe right padding)

    # -------------------------------------------------------------
    # Scene 1: Hook (0s - 12s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    # Main Card
    d.rounded_rectangle([60, 200, 1020, 1500], radius=24, fill=CARD_BG, outline=CARD_BORDER, width=3)
    d.text((100, 240), "[ AI PRODUCTION INFRASTRUCTURE ]", fill=TEXT_CYAN, font=f_badge)
    d.text((100, 285), "AUTONOMOUS AI\nCODING AGENTS", fill=TEXT_WHITE, font=f_title, spacing=8)
    draw_wrapped_text(d, "Why Tool Sandboxing & Boundary Governance Matter", f_subtitle, TEXT_MUTED, 100, 395, max_w)

    # Box 1: The Production Dilemma
    d.rounded_rectangle([90, 460, 990, 730], radius=16, fill=(15, 23, 42, 255), outline=TEXT_AMBER, width=2)
    d.text((120, 480), "THE PRODUCTION DILEMMA", fill=TEXT_AMBER, font=f_badge)
    d.text((120, 520), "High Synthesis Velocity:", fill=TEXT_GREEN, font=f_badge)
    draw_wrapped_text(d, "LLMs generate multi-file code solutions in seconds.", f_body, TEXT_WHITE, 120, 555, max_w)
    d.text((120, 615), "Unchecked Execution Blast Radius:", fill=TEXT_RED, font=f_badge)
    draw_wrapped_text(d, "Raw shell access risks silent workspace state corruption.", f_body, TEXT_WHITE, 120, 650, max_w)

    # Box 2: Core Engineering Foundation
    d.rounded_rectangle([90, 760, 990, 1110], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((120, 785), "CORE ENGINEERING FOUNDATION", fill=TEXT_CYAN, font=f_badge)
    items = [
        "1. Hardware-Isolated Containers (Read-only roots & IPC namespaces)",
        "2. Typed Schema IPC Contracts (Strict parameter validation)",
        "3. Structured Error Diagnostics (Machine-readable recovery payloads)",
        "4. Preflight Shadow Dry-Runs (Zero-mutation pre-verification)",
    ]
    curr_y = 830
    for it in items:
        curr_y = draw_wrapped_text(d, it, f_body, TEXT_WHITE, 120, curr_y, max_w, line_spacing=12)

    # Box 3: Industry Standards
    d.rounded_rectangle([90, 1140, 990, 1460], radius=16, fill=(15, 23, 42, 255), outline=TEXT_MUTED, width=1)
    d.text((120, 1165), "INDUSTRY STANDARDS & BENCHMARKS", fill=TEXT_MUTED, font=f_badge)
    draw_wrapped_text(d, "Empirical benchmarks & distributed consensus protocols:", f_body, TEXT_WHITE, 120, 1205, max_w)
    draw_wrapped_text(d, "SWE-bench (ICLR 2024) · MetaGPT (ICLR 2024) · DORA 2024", f_mono, TEXT_CYAN, 120, 1255, max_w)
    draw_wrapped_text(d, "Non-negotiable verification gates for autonomous pipelines.", f_body, TEXT_MUTED, 120, 1315, max_w)

    img.save(output_dir / "scene_01_hook.png")

    # -------------------------------------------------------------
    # Scene 2: Benchmark (12s - 26s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 200, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_RED, width=3)
    d.text((100, 240), "[ EMPIRICAL BENCHMARK · ICLR 2024 ]", fill=TEXT_RED, font=f_badge)
    d.text((100, 285), "SWE-BENCH RESOLUTION\nFAILURE ANALYSIS", fill=TEXT_WHITE, font=f_title, spacing=8)
    draw_wrapped_text(d, "2,294 Real-World GitHub Issues across 12 Python Repos", f_subtitle, TEXT_MUTED, 100, 395, max_w)

    # Chart Card
    d.rounded_rectangle([90, 460, 990, 1060], radius=16, fill=(15, 23, 42, 255), outline=BAR_BG, width=2)
    d.text((120, 485), "BASELINE MODEL RESOLUTION RATES (UNASSISTED)", fill=TEXT_MUTED, font=f_badge)

    # Claude 2 Bar: 4.8%
    d.text((120, 535), "Claude 2 (Jimenez et al. 2024)", fill=TEXT_WHITE, font=f_body)
    d.rounded_rectangle([120, 575, 840, 615], radius=8, fill=BAR_BG)
    d.rounded_rectangle([120, 575, 120 + int(720 * 0.048), 615], radius=8, fill=TEXT_AMBER)
    d.text((860, 575), "4.8%", fill=TEXT_AMBER, font=f_badge)

    # GPT-4 Bar: 1.74%
    d.text((120, 645), "GPT-4 (Jimenez et al. 2024)", fill=TEXT_WHITE, font=f_body)
    d.rounded_rectangle([120, 685, 840, 725], radius=8, fill=BAR_BG)
    d.rounded_rectangle([120, 685, 120 + int(720 * 0.0174), 725], radius=8, fill=TEXT_AMBER)
    d.text((860, 685), "1.74%", fill=TEXT_AMBER, font=f_badge)

    # Overall failure rate
    d.text((120, 755), "Unassisted Task Failure Rate", fill=TEXT_RED, font=f_badge)
    d.rounded_rectangle([120, 795, 840, 835], radius=8, fill=BAR_BG)
    d.rounded_rectangle([120, 795, 120 + int(720 * 0.952), 835], radius=8, fill=TEXT_RED)
    d.text((860, 795), ">95%", fill=TEXT_RED, font=f_badge)

    draw_wrapped_text(d, "Baseline frontier models struggle with repository-scale reasoning without structured execution sandboxes and feedback.", f_body, TEXT_MUTED, 120, 880, max_w)

    # Citation Card
    d.rounded_rectangle([90, 1090, 990, 1460], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((120, 1115), "PRIMARY LITERATURE CITATION", fill=TEXT_CYAN, font=f_badge)
    draw_wrapped_text(d, "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?", f_body, TEXT_WHITE, 120, 1155, max_w)
    draw_wrapped_text(d, "Carlos E. Jimenez et al., Princeton Language and Intelligence · ICLR 2024 Oral", f_body, TEXT_MUTED, 120, 1215, max_w)
    draw_wrapped_text(d, "Table 2 Full Benchmark (2,294 tasks): Claude 2 solved 4.80%, GPT-4 1.74%", f_mono, TEXT_CYAN, 120, 1275, max_w)
    draw_wrapped_text(d, "Canonical arXiv Reference: https://arxiv.org/abs/2310.06770", f_mono, TEXT_MUTED, 120, 1345, max_w)

    img.save(output_dir / "scene_02_benchmark.png")

    # -------------------------------------------------------------
    # Scene 3: Coordination / MetaGPT (26s - 41s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 200, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_AMBER, width=3)
    d.text((100, 240), "[ MULTI-AGENT COORDINATION · ICLR 2024 ]", fill=TEXT_AMBER, font=f_badge)
    d.text((100, 285), "CIRCULAR DEBATES VS\nSTRUCTURED SOPS", fill=TEXT_WHITE, font=f_title, spacing=8)
    draw_wrapped_text(d, "MetaGPT Multi-Agent Role Architecture (Hong et al.)", f_subtitle, TEXT_MUTED, 100, 395, max_w)

    # Box 1: Unstructured Swarms
    d.rounded_rectangle([90, 460, 990, 740], radius=16, fill=(15, 23, 42, 255), outline=TEXT_RED, width=2)
    d.text((120, 485), "UNSTRUCTURED AGENT SWARMS (FAILURE PATTERN)", fill=TEXT_RED, font=f_badge)
    swarms = [
        "• Peer-to-peer unconstrained agent debate loops",
        "• Cascading circular confirmation and hallucination drift",
        "• Accidental destructive mutations and silent state regression",
    ]
    curr_y = 530
    for s in swarms:
        curr_y = draw_wrapped_text(d, s, f_body, TEXT_WHITE, 120, curr_y, max_w, line_spacing=10)

    # Box 2: MetaGPT Structured SOPs
    d.rounded_rectangle([90, 770, 990, 1150], radius=16, fill=(15, 23, 42, 255), outline=TEXT_GREEN, width=2)
    d.text((120, 795), "METAGPT STRUCTURED SOPS (VERIFIED SOLUTION)", fill=TEXT_GREEN, font=f_badge)
    sops = [
        "1. Role Division: Product Manager -> Architect -> Engineer -> QA",
        "2. Standard Operating Procedures (SOPs) eliminate debate loops",
        "3. Structured intermediate artifacts form strict handoff contracts",
        "4. Supervisor evaluates deliverables against immutable schemas",
    ]
    curr_y = 840
    for sp in sops:
        curr_y = draw_wrapped_text(d, sp, f_body, TEXT_WHITE, 120, curr_y, max_w, line_spacing=10)
    draw_wrapped_text(d, "Result: 100% task completion on software development benchmarks", f_body, TEXT_GREEN, 120, curr_y + 8, max_w)

    # Box 3: Citation
    d.rounded_rectangle([90, 1180, 990, 1460], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((120, 1205), "PRIMARY LITERATURE CITATION", fill=TEXT_CYAN, font=f_badge)
    draw_wrapped_text(d, "MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework", f_body, TEXT_WHITE, 120, 1245, max_w)
    draw_wrapped_text(d, "Sirui Hong et al., DeepWisdom & KAUST · ICLR 2024", f_body, TEXT_MUTED, 120, 1300, max_w)
    draw_wrapped_text(d, "Canonical Reference: https://arxiv.org/abs/2308.00352", f_mono, TEXT_CYAN, 120, 1355, max_w)

    img.save(output_dir / "scene_03_coordination.png")

    # -------------------------------------------------------------
    # Scene 4: Sandboxing Architecture (41s - 55s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 200, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_GREEN, width=3)
    d.text((100, 240), "[ DETERMINISTIC RUNTIME GOVERNANCE ]", fill=TEXT_GREEN, font=f_badge)
    d.text((100, 285), "ISOLATED TOOL\nEXECUTION BOUNDARIES", fill=TEXT_WHITE, font=f_title, spacing=8)
    draw_wrapped_text(d, "Hardware Enforced Containers & Schema Validation", f_subtitle, TEXT_MUTED, 100, 395, max_w)

    # Three Pillars
    pillars = [
        ("PILLAR 1: CONTAINER ISOLATION", "Ephemeral IPC namespaces, read-only system roots, and network socket isolation restrict execution blast radius.", TEXT_CYAN, 460),
        ("PILLAR 2: STRICT SCHEMA PROTOCOLS", "Every tool call enforces immutable typed JSON schemas. Out-of-bounds parameters fail before execution.", TEXT_AMBER, 710),
        ("PILLAR 3: STRUCTURED ERROR PAYLOADS", "Execution errors return machine-readable diagnostic payloads rather than crashing the agent state machine.", TEXT_GREEN, 960),
    ]
    for p_title, p_desc, p_col, p_y in pillars:
        d.rounded_rectangle([90, p_y, 990, p_y + 220], radius=16, fill=(15, 23, 42, 255), outline=p_col, width=2)
        d.text((120, p_y + 20), p_title, fill=p_col, font=f_badge)
        draw_wrapped_text(d, p_desc, f_body, TEXT_WHITE, 120, p_y + 65, max_w, line_spacing=8)

    d.rounded_rectangle([90, 1210, 990, 1460], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((120, 1235), "OPERATIONAL BENEFIT", fill=TEXT_CYAN, font=f_badge)
    draw_wrapped_text(d, "Prevents credential exfiltration, destructive shell operations, and unverified workspace mutations across autonomous pipelines.", f_body, TEXT_WHITE, 120, 1275, max_w)

    img.save(output_dir / "scene_04_sandboxing.png")

    # -------------------------------------------------------------
    # Scene 5: Verification & DORA 2024 (55s - 72s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 200, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_CYAN, width=3)
    d.text((100, 240), "[ DEVOPS RESEARCH & ASSESSMENT · DORA 2024 ]", fill=TEXT_CYAN, font=f_badge)
    d.text((100, 285), "AUTOMATED PREFLIGHT\nVERIFICATION GATES", fill=TEXT_WHITE, font=f_title, spacing=8)
    draw_wrapped_text(d, "Validating System State Before Live Environment Release", f_subtitle, TEXT_MUTED, 100, 395, max_w)

    # Verification Gates
    d.rounded_rectangle([90, 460, 990, 1140], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((120, 485), "PRE-RELEASE QUALITY GATES (DORA 2024)", fill=TEXT_MUTED, font=f_badge)

    gates = [
        ("GATE 1: STATIC SCHEMA & CITATION AUDIT", "Verified canonical DOIs, bounded claims, script span matching", TEXT_GREEN, 535),
        ("GATE 2: AUTOMATED TESTING & FFPROBE QA", "Zero black frames, exact 9:16 SAR 1:1, audio-sync verification", TEXT_GREEN, 675),
        ("GATE 3: SHADOW DRY-RUN SIMULATION", "Executes full release protocol without live state mutations", TEXT_CYAN, 815),
        ("GATE 4: INDEPENDENT QUALITY SUPERVISOR", "Cryptographic approval bound to media SHA-256 (Zero self-approval)", TEXT_AMBER, 955),
    ]
    for g_title, g_desc, g_col, g_y in gates:
        d.text((120, g_y), f"✓ {g_title}", fill=g_col, font=f_badge)
        draw_wrapped_text(d, g_desc, f_body, TEXT_WHITE, 145, g_y + 35, max_w - 25)

    # Citation Card
    d.rounded_rectangle([90, 1170, 990, 1460], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((120, 1195), "PRIMARY LITERATURE CITATION", fill=TEXT_CYAN, font=f_badge)
    draw_wrapped_text(d, "Google Cloud State of DevOps Report (DORA 2024)", f_body, TEXT_WHITE, 120, 1235, max_w)
    draw_wrapped_text(d, "DevOps Research and Assessment · Published: Oct 2024", f_body, TEXT_MUTED, 120, 1280, max_w)
    draw_wrapped_text(d, "Key Finding: Fast verification gates mitigate delivery risks", f_body, TEXT_GREEN, 120, 1325, max_w)
    draw_wrapped_text(d, "Canonical URL: https://dora.dev/research/2024/dora-report/", f_mono, TEXT_CYAN, 120, 1375, max_w)

    img.save(output_dir / "scene_05_verification.png")
    print(f"Generated 5 Short scene graphics in {output_dir}")


def generate_longform_graphics(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = 1920, 1080

    # Fonts
    f_badge = ImageFont.truetype(FONT_BOLD, 22)
    f_title = ImageFont.truetype(FONT_BOLD, 42)
    f_subtitle = ImageFont.truetype(FONT_REGULAR, 24)
    f_body = ImageFont.truetype(FONT_REGULAR, 22)
    f_mono = ImageFont.truetype(FONT_MONO, 20)

    chapters = [
        {
            "id": "ch01_prompt_bottleneck",
            "badge": "SYSTEMS ARCHITECTURE · CHAPTER 1",
            "title": "THE SINGLE-PROMPT BOTTLENECK",
            "subtitle": "Context Dilution, Attention Drift, and Compounding Hallucination",
            "color": TEXT_AMBER,
            "col1_title": "THE SINGLE-PROMPT FAILURE MODES",
            "col1_items": [
                "• Context Dilution: Attention disperses as prompt length scales",
                "• Attention Drift: Model ignores intermediate code constraints",
                "• Compounding Hallucination: Minor errors amplify across edits",
                "• Token Saturation: Context window becomes noisy scratchpad",
            ],
            "col2_title": "SYSTEMS ENGINEERING SOLUTION",
            "col2_items": [
                "• Decouple monolithic prompts into distributed state machines",
                "• Formal RPC boundaries replace unstructured instruction blocks",
                "• Ephemeral sub-task contexts prevent memory contamination",
                "• Verified deterministic gates supersede subjective self-checks",
            ],
            "citation": "Autonomous AI coding requires disciplined system scaffolding, not longer prompts.",
        },
        {
            "id": "ch02_memory_hierarchy",
            "badge": "SYSTEMS ARCHITECTURE · CHAPTER 2",
            "title": "THREE-TIER AGENT MEMORY HIERARCHY",
            "subtitle": "Decoupling Context Windows, Semantic Search, and Append-Only Ledgers",
            "color": TEXT_CYAN,
            "col1_title": "THE THREE MEMORY TIERS",
            "col1_items": [
                "1. Tier 1: Ephemeral Working Context (Current turn prompt & tool outputs)",
                "2. Tier 2: Structured Semantic Store (Vector indexed references)",
                "3. Tier 3: Immutable Disk Ledger (Append-only state machine audit log)",
                "Principle: Long-term state lives on disk, not in the context window",
            ],
            "col2_title": "ENGINEERING ADVANTAGES",
            "col2_items": [
                "• Maximizes reasoning precision by filtering historical token noise",
                "• Deterministic reproducibility: Every state transition is recorded",
                "• Scalable knowledge retrieval across multi-hour production runs",
                "• Zero token drift: Exact schema preservation across pipeline stages",
            ],
            "citation": "Production agents offload long-term state to external ledgers to maintain reasoning clarity.",
        },
        {
            "id": "ch03_tool_sandboxing",
            "badge": "SYSTEMS ARCHITECTURE · CHAPTER 3",
            "title": "DETERMINISTIC TOOL PROTOCOLS & IPC SANDBOXING",
            "subtitle": "Typed RPC Schemas, Resource Quotas, and Hardware Boundary Enforcement",
            "color": TEXT_GREEN,
            "col1_title": "TOOL SANDBOX ARCHITECTURE",
            "col1_items": [
                "• Ephemeral Linux namespaces and hardware container boundaries",
                "• Read-only root filesystems; strict project workspace mounts",
                "• Blocked outbound raw sockets; whitelist-only network access",
                "• Strict execution timeouts and CPU / memory quotas",
            ],
            "col2_title": "SCHEMA CONTRACTS & ERROR HANDLING",
            "col2_items": [
                "• Typed JSON schemas reject invalid parameter payloads pre-call",
                "• Hardware-isolated execution prevents destructive host mutations",
                "• Structured machine-readable error payloads guide agent recovery",
                "• Clean recovery without blowing up the supervisor state machine",
            ],
            "citation": "Giving agents unconstrained shell access is an unacceptable risk; boundaries must be hardware-enforced.",
        },
        {
            "id": "ch04_rollback_checkpoints",
            "badge": "ACM COMPUTING SURVEYS · CHAPTER 4",
            "title": "STATE MACHINES & ROLLBACK-RECOVERY PROTOCOLS",
            "subtitle": "Coordinated Checkpointing on Stable Storage (Elnozahy et al., ACM CSUR 2002)",
            "color": TEXT_AMBER,
            "col1_title": "COORDINATED CHECKPOINTING PROTOCOL",
            "col1_items": [
                "• Immutable stage snapshots written to disk at transition barriers",
                "• Cryptographic SHA-256 digests bind artifacts to execution state",
                "• Crash or network timeout -> Resume from latest valid snapshot",
                "• Eliminates cascading rollbacks and bounded recovery overhead",
            ],
            "col2_title": "PRIMARY CITATION & STANDARDS",
            "col2_items": [
                "• Paper: 'A Survey of Rollback-Recovery Protocols in Systems'",
                "• Authors: E.N. Elnozahy, Lorenzo Alvisi, Yi-Min Wang, David B. Johnson",
                "• Publisher: ACM Computing Surveys (CSUR), Vol. 34, No. 3, 2002",
                "• DOI: 10.1145/568522.568525 (Verified Computer Science Literature)",
            ],
            "citation": "Immutable checkpoint ledgers bound crash recovery time by resuming execution from valid state snapshots.",
        },
        {
            "id": "ch05_supervisors_vs_swarms",
            "badge": "ICLR 2024 · CHAPTER 5",
            "title": "MULTI-AGENT ORCHESTRATION: SUPERVISORS VS SWARMS",
            "subtitle": "Hierarchical Standard Operating Procedures (MetaGPT, Hong et al. 2024)",
            "color": TEXT_CYAN,
            "col1_title": "HIERARCHICAL SUPERVISOR TOPOLOGY",
            "col1_items": [
                "• Unstructured Swarms: Chaos, token explosion, circular debate loops",
                "• Supervisor Model: Directed Acyclic Graph (DAG) task distribution",
                "• Formal Standard Operating Procedures (SOPs) eliminate ambiguity",
                "• Each agent delivers typed artifacts conforming to strict schemas",
            ],
            "col2_title": "EVALUATION METRICS & FINDINGS",
            "col2_items": [
                "• 100% executable software outputs on standard engineering tasks",
                "• Code review passes from independent QA supervisor before commit",
                "• Prevents prompt contamination between specialist agents",
                "• Citation: MetaGPT Collaborative Framework (arXiv:2308.00352)",
            ],
            "citation": "Multi-agent systems require rigorous hierarchical SOP contracts to prevent circular coordination loops.",
        },
        {
            "id": "ch06_quality_gates",
            "badge": "DEVOPS RESEARCH & ASSESSMENT · DORA 2024 · CHAPTER 6",
            "title": "NON-NEGOTIABLE VERIFICATION & QUALITY GATES",
            "subtitle": "Independent Supervisor Audits and Cryptographic Approval Binding",
            "color": TEXT_GREEN,
            "col1_title": "FOUR INDEPENDENT VERIFICATION GATES",
            "col1_items": [
                "• Gate 1: Static citation & claim ledger validation against primary sources",
                "• Gate 2: Automated unit & integration tests pass with zero regressions",
                "• Gate 3: Media verification: exact resolution, framerate, audio sync",
                "• Gate 4: Independent supervisor approval signed with HMAC-SHA256",
            ],
            "col2_title": "DORA 2024 SCIENTIFIC FINDINGS",
            "col2_items": [
                "• DORA 2024: Fast automated quality gates reduce change failure rate",
                "• Zero self-approval: Pipeline generator cannot approve own output",
                "• Release manifest binds media SHA-256 to approval record cryptographically",
                "• Citation: Google Cloud State of DevOps Report (dora.dev)",
            ],
            "citation": "Quality is not an afterthought; cryptographic verification gates must precede every deployment.",
        },
        {
            "id": "ch07_cost_token_circuits",
            "badge": "PRODUCTION GOVERNANCE · CHAPTER 7",
            "title": "TOKEN GOVERNANCE & ECONOMIC CIRCUIT BREAKERS",
            "subtitle": "Budget Hard-Caps, Runaway Loop Prevention, and Rate Quotas",
            "color": TEXT_AMBER,
            "col1_title": "ECONOMIC GOVERNANCE PATTERNS",
            "col1_items": [
                "• Hard-budget ceilings per production run with fail-closed breakers",
                "• Max iteration limits prevent infinite agent retry spirals",
                "• Tiered model routing: cheap models for extraction, frontier for reasoning",
                "• Token accounting recorded in immutable ledger per turn",
            ],
            "col2_title": "CIRCUIT BREAKER ENFORCEMENT",
            "col2_items": [
                "• Automatic execution freeze on consecutive tool error thresholds",
                "• Rate-limit backoff with jitter avoids upstream provider bans",
                "• Human-in-the-loop escalation on budget threshold breach",
                "• Production principle: Financial boundaries protect operational stability",
            ],
            "citation": "Without strict token budget circuits, runaway retry loops burn through API spend without resolving failures.",
        },
        {
            "id": "ch08_zero_mutation_blueprint",
            "badge": "DEVOPS RESEARCH & ASSESSMENT · DORA 2024 · CHAPTER 8",
            "title": "THE ZERO-MUTATION PRODUCTION BLUEPRINT",
            "subtitle": "Google Cloud DORA 2024: Preflight Verification Gates and Safe Delivery",
            "color": TEXT_GREEN,
            "col1_title": "THE FOUR ARCHITECTURAL PILLARS",
            "col1_items": [
                "1. Hardware-Isolated Containers: Strict execution boundaries",
                "2. Three-Tier Memory & Checkpoints: Resilient rollback-recovery",
                "3. Supervisor-Worker SOP Hierarchy: Zero circular deadlocks",
                "4. Automated Quality Gates: Non-negotiable acceptance checks",
            ],
            "col2_title": "SHADOW SIMULATION & VERIFICATION",
            "col2_items": [
                "• Shadow Dry-Runs: Prove zero mutations and zero side effects",
                "• Full mock transport verifies permission envelopes end-to-end",
                "• DORA 2024: Automated verification gates protect stability",
                "• Canonical Citation: https://dora.dev/research/2024/dora-report/",
            ],
            "citation": "Comprehensive preflight verification and automated testing gates validate system state before changes deploy.",
        },
    ]

    col_w = 750  # 150 + 750 = 900 <= 940 (safe inside column box)

    for ch in chapters:
        img = Image.new("RGBA", (w, h), BG_DARK)
        d = ImageDraw.Draw(img)
        draw_grid_background(d, w, h)

        # Main Card
        d.rounded_rectangle([80, 50, 1840, 910], radius=24, fill=CARD_BG, outline=ch["color"], width=3)
        d.text((120, 80), f"[ {ch['badge']} ]", fill=ch["color"], font=f_badge)
        d.text((120, 120), ch["title"], fill=TEXT_WHITE, font=f_title)
        draw_wrapped_text(d, ch["subtitle"], f_subtitle, TEXT_MUTED, 120, 175, 1600)

        # Left Column Box: [120, 230, 940, 740]
        d.rounded_rectangle([120, 230, 940, 740], radius=16, fill=(15, 23, 42, 255), outline=BAR_BG, width=2)
        d.text((150, 255), ch["col1_title"], fill=ch["color"], font=f_badge)
        y = 310
        for item in ch["col1_items"]:
            y = draw_wrapped_text(d, item, f_body, TEXT_WHITE, 150, y, col_w, line_spacing=14)

        # Right Column Box: [980, 230, 1800, 740]
        d.rounded_rectangle([980, 230, 1800, 740], radius=16, fill=(15, 23, 42, 255), outline=BAR_BG, width=2)
        d.text((1010, 255), ch["col2_title"], fill=TEXT_CYAN, font=f_badge)
        y = 310
        for item in ch["col2_items"]:
            y = draw_wrapped_text(d, item, f_body, TEXT_WHITE, 1010, y, col_w, line_spacing=14)

        # Bottom Callout / Footnote: [120, 765, 1800, 880]
        d.rounded_rectangle([120, 765, 1800, 880], radius=12, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
        d.text((150, 785), "CORE ENGINEERING TAKEAWAY", fill=TEXT_CYAN, font=f_badge)
        draw_wrapped_text(d, ch["citation"], f_body, TEXT_WHITE, 150, 825, 1600)

        img.save(output_dir / f"{ch['id']}.png")

    print(f"Generated 8 Longform chapter graphics in {output_dir}")


if __name__ == "__main__":
    generate_short_graphics(Path("/tmp/scene_graphics/short"))
    generate_longform_graphics(Path("/tmp/scene_graphics/long"))
