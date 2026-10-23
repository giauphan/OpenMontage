#!/usr/bin/env python3
"""Generate rich contextual graphic cards for production en-US deliverables.

Replaces raw testsrc with high-production technical architecture diagrams,
benchmark charts, and verifiable citation cards.
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


def generate_short_graphics(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = 1080, 1920

    # Fonts
    f_badge = ImageFont.truetype(FONT_BOLD, 22)
    f_title = ImageFont.truetype(FONT_BOLD, 46)
    f_subtitle = ImageFont.truetype(FONT_REGULAR, 28)
    f_body = ImageFont.truetype(FONT_REGULAR, 26)
    f_mono = ImageFont.truetype(FONT_MONO, 24)
    f_stat = ImageFont.truetype(FONT_BOLD, 56)

    # -------------------------------------------------------------
    # Scene 1: Hook (0s - 12s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    # Main Card
    d.rounded_rectangle([60, 220, 1020, 1500], radius=24, fill=CARD_BG, outline=CARD_BORDER, width=3)
    d.text((100, 260), "[ AI PRODUCTION INFRASTRUCTURE ]", fill=TEXT_CYAN, font=f_badge)
    d.text((100, 310), "AUTONOMOUS AI\nCODING AGENTS", fill=TEXT_WHITE, font=f_title, spacing=10)
    d.text((100, 430), "Why Tool Sandboxing & Boundary Governance Matter", fill=TEXT_MUTED, font=f_subtitle)

    # Visual Comparison: Speed vs Uncontrolled Side-effects
    d.rounded_rectangle([100, 520, 980, 760], radius=16, fill=(15, 23, 42, 255), outline=TEXT_AMBER, width=2)
    d.text((130, 540), "THE PRODUCTION DILEMMA", fill=TEXT_AMBER, font=f_badge)
    d.text((130, 580), "High Synthesis Velocity", fill=TEXT_GREEN, font=f_badge)
    d.text((130, 615), "LLMs generate multi-file code solutions in seconds.", fill=TEXT_WHITE, font=f_body)
    d.text((130, 665), "Unchecked Execution Blast Radius", fill=TEXT_RED, font=f_badge)
    d.text((130, 700), "Raw shell access risks silent workspace state corruption.", fill=TEXT_WHITE, font=f_body)

    # Architecture Preview
    d.rounded_rectangle([100, 800, 980, 1140], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((130, 830), "CORE ENGINEERING FOUNDATION", fill=TEXT_CYAN, font=f_badge)
    d.text((130, 880), "1. Hardware-Isolated Containers", fill=TEXT_WHITE, font=f_body)
    d.text((130, 930), "2. Typed Schema IPC Contracts", fill=TEXT_WHITE, font=f_body)
    d.text((130, 980), "3. Structured Error Diagnostics", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1030), "4. Preflight Shadow Dry-Runs", fill=TEXT_WHITE, font=f_body)

    d.rounded_rectangle([100, 1180, 980, 1440], radius=16, fill=(15, 23, 42, 255), outline=TEXT_MUTED, width=1)
    d.text((130, 1210), "INDUSTRY STANDARDS", fill=TEXT_MUTED, font=f_badge)
    d.text((130, 1250), "Empirical benchmarks & distributed consensus protocols", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1290), "SWE-bench (ICLR 2024) · MetaGPT (ICLR 2024) · DORA 2024", fill=TEXT_CYAN, font=f_mono)
    d.text((130, 1340), "Non-negotiable verification gates for autonomous pipelines", fill=TEXT_MUTED, font=f_body)

    img.save(output_dir / "scene_01_hook.png")

    # -------------------------------------------------------------
    # Scene 2: Benchmark (12s - 26s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 220, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_RED, width=3)
    d.text((100, 260), "[ EMPIRICAL BENCHMARK · ICLR 2024 ]", fill=TEXT_RED, font=f_badge)
    d.text((100, 310), "SWE-BENCH RESOLUTION\nFAILURE ANALYSIS", fill=TEXT_WHITE, font=f_title, spacing=10)
    d.text((100, 430), "2,294 Real-World GitHub Issues across 12 Python Repos", fill=TEXT_MUTED, font=f_subtitle)

    # Chart Card
    d.rounded_rectangle([100, 500, 980, 1080], radius=16, fill=(15, 23, 42, 255), outline=BAR_BG, width=2)
    d.text((130, 530), "BASELINE MODEL RESOLUTION RATES (UNASSISTED)", fill=TEXT_MUTED, font=f_badge)

    # Claude 2 Bar: 4.8% (bar width out of 700px)
    d.text((130, 590), "Claude 2 (Jimenez et al. 2024)", fill=TEXT_WHITE, font=f_body)
    d.rounded_rectangle([130, 630, 850, 670], radius=8, fill=BAR_BG)
    d.rounded_rectangle([130, 630, 130 + int(720 * 0.048), 670], radius=8, fill=TEXT_AMBER)
    d.text((870, 630), "4.8%", fill=TEXT_AMBER, font=f_badge)

    # GPT-4 Bar: 1.74%
    d.text((130, 710), "GPT-4 (Jimenez et al. 2024)", fill=TEXT_WHITE, font=f_body)
    d.rounded_rectangle([130, 750, 850, 790], radius=8, fill=BAR_BG)
    d.rounded_rectangle([130, 750, 130 + int(720 * 0.0174), 790], radius=8, fill=TEXT_AMBER)
    d.text((870, 750), "1.74%", fill=TEXT_AMBER, font=f_badge)

    # Overall unassisted failure rate
    d.text((130, 840), "Unassisted Task Failure Rate", fill=TEXT_RED, font=f_badge)
    d.rounded_rectangle([130, 880, 850, 920], radius=8, fill=BAR_BG)
    d.rounded_rectangle([130, 880, 130 + int(720 * 0.952), 920], radius=8, fill=TEXT_RED)
    d.text((870, 880), ">95%", fill=TEXT_RED, font=f_badge)

    d.text((130, 970), "Baseline models struggle with multi-file reasoning", fill=TEXT_MUTED, font=f_body)
    d.text((130, 1010), "without structured execution sandboxes and feedback.", fill=TEXT_MUTED, font=f_body)

    # Citation Card
    d.rounded_rectangle([100, 1120, 980, 1440], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((130, 1150), "PRIMARY LITERATURE CITATION", fill=TEXT_CYAN, font=f_badge)
    d.text((130, 1200), "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1240), "Carlos E. Jimenez et al., Princeton Language and Intelligence", fill=TEXT_MUTED, font=f_body)
    d.text((130, 1280), "Venue: ICLR 2024 (Oral) · Published: Oct 2023 · arXiv:2310.06770", fill=TEXT_MUTED, font=f_body)
    d.text((130, 1320), "Table 2 Full Benchmark (2,294 tasks): Claude 2 solved 4.80%, GPT-4 1.74%", fill=TEXT_CYAN, font=f_mono)
    d.text((130, 1360), "Canonical Reference: https://arxiv.org/abs/2310.06770", fill=TEXT_MUTED, font=f_mono)

    img.save(output_dir / "scene_02_benchmark.png")

    # -------------------------------------------------------------
    # Scene 3: Coordination / MetaGPT (26s - 41s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 220, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_AMBER, width=3)
    d.text((100, 260), "[ MULTI-AGENT COORDINATION · ICLR 2024 ]", fill=TEXT_AMBER, font=f_badge)
    d.text((100, 310), "CIRCULAR DEBATES VS\nSTRUCTURED SOPS", fill=TEXT_WHITE, font=f_title, spacing=10)
    d.text((100, 430), "MetaGPT Multi-Agent Role Architecture (Hong et al.)", fill=TEXT_MUTED, font=f_subtitle)

    # Visual Workflow Diagram
    d.rounded_rectangle([100, 500, 980, 770], radius=16, fill=(15, 23, 42, 255), outline=TEXT_RED, width=2)
    d.text((130, 530), "UNSTRUCTURED AGENT SWARMS (FAILURE PATTERN)", fill=TEXT_RED, font=f_badge)
    d.text((130, 570), "• Peer-to-peer unconstrained agent debate", fill=TEXT_WHITE, font=f_body)
    d.text((130, 615), "• Cascading circular confirmation loops", fill=TEXT_WHITE, font=f_body)
    d.text((130, 660), "• State drift and accidental destructive file mutations", fill=TEXT_WHITE, font=f_body)
    d.text((130, 705), "• Hallucination amplification across turns", fill=TEXT_WHITE, font=f_body)

    d.rounded_rectangle([100, 800, 980, 1140], radius=16, fill=(15, 23, 42, 255), outline=TEXT_GREEN, width=2)
    d.text((130, 830), "METAGPT STRUCTURED SOPS (VERIFIED SOLUTION)", fill=TEXT_GREEN, font=f_badge)
    d.text((130, 870), "1. Role Division: Product -> Architect -> Engineer -> QA", fill=TEXT_WHITE, font=f_body)
    d.text((130, 915), "2. Standard Operating Procedures (SOPs) eliminate debate loops", fill=TEXT_WHITE, font=f_body)
    d.text((130, 960), "3. Structured intermediate artifacts form strict handoff contracts", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1005), "4. Supervisor evaluates deliverables against immutable schemas", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1050), "Result: 100% task completion on software development benchmarks", fill=TEXT_GREEN, font=f_body)

    # Citation
    d.rounded_rectangle([100, 1170, 980, 1440], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((130, 1200), "PRIMARY LITERATURE CITATION", fill=TEXT_CYAN, font=f_badge)
    d.text((130, 1245), "MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1290), "Sirui Hong et al., DeepWisdom & KAUST · ICLR 2024", fill=TEXT_MUTED, font=f_body)
    d.text((130, 1345), "Canonical DOI / URL: https://arxiv.org/abs/2308.00352", fill=TEXT_CYAN, font=f_mono)

    img.save(output_dir / "scene_03_coordination.png")

    # -------------------------------------------------------------
    # Scene 4: Sandboxing Architecture (41s - 55s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 220, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_GREEN, width=3)
    d.text((100, 260), "[ DETERMINISTIC RUNTIME GOVERNANCE ]", fill=TEXT_GREEN, font=f_badge)
    d.text((100, 310), "ISOLATED TOOL\nEXECUTION BOUNDARIES", fill=TEXT_WHITE, font=f_title, spacing=10)
    d.text((100, 430), "Hardware Enforced Containers & Schema Validation", fill=TEXT_MUTED, font=f_subtitle)

    # Three Boundary Pillars
    pillars = [
        ("PILLAR 1: CONTAINER ISOLATION", "Ephemeral IPC namespaces, read-only system roots, and network socket isolation restrict execution blast radius.", TEXT_CYAN, 510),
        ("PILLAR 2: STRICT SCHEMA PROTOCOLS", "Every tool call enforces immutable typed JSON schemas. Out-of-bounds parameters fail before execution.", TEXT_AMBER, 750),
        ("PILLAR 3: STRUCTURED ERROR PAYLOADS", "Execution errors return machine-readable diagnostic payloads rather than crashing the agent state machine.", TEXT_GREEN, 990),
    ]
    for p_title, p_desc, p_col, p_y in pillars:
        d.rounded_rectangle([100, p_y, 980, p_y + 200], radius=16, fill=(15, 23, 42, 255), outline=p_col, width=2)
        d.text((130, p_y + 25), p_title, fill=p_col, font=f_badge)
        # Wrap description
        words = p_desc.split()
        l1, l2 = " ".join(words[:8]), " ".join(words[8:])
        d.text((130, p_y + 75), l1, fill=TEXT_WHITE, font=f_body)
        d.text((130, p_y + 115), l2, fill=TEXT_WHITE, font=f_body)

    d.rounded_rectangle([100, 1230, 980, 1440], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((130, 1260), "OPERATIONAL BENEFIT", fill=TEXT_CYAN, font=f_badge)
    d.text((130, 1305), "Prevents credential exfiltration, destructive shell operations,", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1345), "and unverified workspace mutations across autonomous pipelines.", fill=TEXT_WHITE, font=f_body)

    img.save(output_dir / "scene_04_sandboxing.png")

    # -------------------------------------------------------------
    # Scene 5: Verification & DORA 2024 (55s - 72s)
    # -------------------------------------------------------------
    img = Image.new("RGBA", (w, h), BG_DARK)
    d = ImageDraw.Draw(img)
    draw_grid_background(d, w, h)

    d.rounded_rectangle([60, 220, 1020, 1500], radius=24, fill=CARD_BG, outline=TEXT_CYAN, width=3)
    d.text((100, 260), "[ DEVOPS RESEARCH & ASSESSMENT · DORA 2024 ]", fill=TEXT_CYAN, font=f_badge)
    d.text((100, 310), "AUTOMATED PREFLIGHT\nVERIFICATION GATES", fill=TEXT_WHITE, font=f_title, spacing=10)
    d.text((100, 430), "Validating System State Before Live Environment Release", fill=TEXT_MUTED, font=f_subtitle)

    # Verification Gate Flow
    d.rounded_rectangle([100, 500, 980, 1100], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((130, 530), "PRE-RELEASE QUALITY GATES (DORA 2024 RECOMMENDATIONS)", fill=TEXT_MUTED, font=f_badge)

    gates = [
        ("GATE 1: STATIC SCHEMA & CITATION AUDIT", "Verified canonical DOIs, bounded claims, script span matching", TEXT_GREEN, 590),
        ("GATE 2: AUTOMATED TESTING & FFPROBE QA", "Zero black frames, exact 9:16 SAR 1:1, audio-sync verification", TEXT_GREEN, 720),
        ("GATE 3: SHADOW DRY-RUN SIMULATION", "Executes full release protocol without live state mutations", TEXT_CYAN, 850),
        ("GATE 4: INDEPENDENT QUALITY SUPERVISOR", "Cryptographic approval bound to media SHA-256 (Zero self-approval)", TEXT_AMBER, 980),
    ]
    for g_title, g_desc, g_col, g_y in gates:
        d.text((130, g_y), f"✓ {g_title}", fill=g_col, font=f_badge)
        d.text((155, g_y + 35), g_desc, fill=TEXT_WHITE, font=f_body)

    # Citation Card
    d.rounded_rectangle([100, 1140, 980, 1440], radius=16, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
    d.text((130, 1170), "PRIMARY LITERATURE CITATION", fill=TEXT_CYAN, font=f_badge)
    d.text((130, 1215), "Google Cloud State of DevOps Report (DORA 2024)", fill=TEXT_WHITE, font=f_body)
    d.text((130, 1255), "DevOps Research and Assessment · Published: Oct 2024", fill=TEXT_MUTED, font=f_body)
    d.text((130, 1295), "Key Finding: Fast verification gates mitigate delivery risks", fill=TEXT_GREEN, font=f_body)
    d.text((130, 1345), "Canonical URL: https://dora.dev/research/2024/dora-report/", fill=TEXT_CYAN, font=f_mono)

    img.save(output_dir / "scene_05_verification.png")
    print(f"Generated 5 Short scene graphics in {output_dir}")


def generate_longform_graphics(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    w, h = 1920, 1080

    # Fonts
    f_badge = ImageFont.truetype(FONT_BOLD, 22)
    f_title = ImageFont.truetype(FONT_BOLD, 44)
    f_subtitle = ImageFont.truetype(FONT_REGULAR, 26)
    f_body = ImageFont.truetype(FONT_REGULAR, 24)
    f_mono = ImageFont.truetype(FONT_MONO, 22)

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
                "• Compounding Hallucination: Minor errors amplify across multi-file edits",
                "• Token Saturation: Context window becomes noisy scratchpad",
            ],
            "col2_title": "SYSTEMS ENGINEERING SOLUTION",
            "col2_items": [
                "• Decouple monolithic prompts into distributed state machines",
                "• Formal RPC boundaries replace unstructured instruction blocks",
                "• Ephemeral sub-task contexts prevent memory contamination",
                "• Verified deterministic gates supersede subjective self-checks",
            ],
            "citation": "Autonomous AI coding requires disciplined system scaffolding, not longer prompts."
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
                "2. Tier 2: Structured Semantic Store (Vector indexed decisions & references)",
                "3. Tier 3: Immutable Disk Ledger (Append-only state machine audit log)",
                "Principle: Long-term state lives on disk, not in the model context window",
            ],
            "col2_title": "ENGINEERING ADVANTAGES",
            "col2_items": [
                "• Maximizes reasoning precision by filtering historical token noise",
                "• Deterministic reproducibility: Every state transition is recorded",
                "• Scalable knowledge retrieval across multi-hour production runs",
                "• Zero token drift: Exact schema preservation across pipeline stages",
            ],
            "citation": "Production agents offload long-term state to external ledgers to maintain reasoning clarity."
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
            "citation": "Giving agents unconstrained shell access is an unacceptable risk; boundaries must be hardware-enforced."
        },
        {
            "id": "ch04_rollback_checkpoints",
            "badge": "ACM COMPUTING SURVEYS · CHAPTER 4",
            "title": "STATE MACHINES & ROLLBACK-RECOVERY PROTOCOLS",
            "subtitle": "Coordinated Checkpointing on Stable Storage (Elnozahy et al., ACM CSUR 2002)",
            "color": TEXT_AMBER,
            "col1_title": "COORDINATED CHECKPOINTING PROTOCOL",
            "col1_items": [
                "• Immutable stage snapshots written to disk at every transition barrier",
                "• Cryptographic SHA-256 digests bind artifacts to execution state",
                "• Crash or network timeout -> Resume from latest valid snapshot",
                "• Eliminates cascading rollbacks and bounded recovery overhead",
            ],
            "col2_title": "PRIMARY CITATION & STANDARDS",
            "col2_items": [
                "• Paper: 'A Survey of Rollback-Recovery Protocols in Message-Passing Systems'",
                "• Authors: E.N. Elnozahy, Lorenzo Alvisi, Yi-Min Wang, David B. Johnson",
                "• Publisher: ACM Computing Surveys (CSUR), Vol. 34, No. 3, 2002",
                "• DOI: 10.1145/568522.568525 (Verified Computer Science Literature)",
            ],
            "citation": "Immutable checkpoint ledgers bound crash recovery time by resuming execution from valid state snapshots."
        },
        {
            "id": "ch05_supervisors_vs_swarms",
            "badge": "ICLR 2024 · CHAPTER 5",
            "title": "MULTI-AGENT ORCHESTRATION: SUPERVISORS VS SWARMS",
            "subtitle": "Standard Operating Procedures Eliminate Circular Coordination Loops (Hong et al., MetaGPT)",
            "color": TEXT_CYAN,
            "col1_title": "SUPERVISOR HIERARCHY WITH SOPS",
            "col1_items": [
                "• Supervisor Agent maintains state machine & schema contracts",
                "• Worker Agents focus on isolated sub-tasks (Analysis, Coding, QA)",
                "• Standard Operating Procedures (SOPs) eliminate circular debates",
                "• Verified handoff contracts replace free-form chat swarms",
            ],
            "col2_title": "EMPIRICAL BENCHMARK EVIDENCE",
            "col2_items": [
                "• Paper: 'MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework'",
                "• Authors: Sirui Hong et al. · Venue: ICLR 2024 · arXiv:2308.00352",
                "• Result: 100% completion on SoftwareDev; eliminates deadlocks",
                "• Evaluated on structured multi-agent software engineering workflows",
            ],
            "citation": "Structuring agent collaboration with SOPs and specialized roles prevents circular coordination loops."
        },
        {
            "id": "ch06_quality_gates",
            "badge": "QUALITY ASSURANCE · CHAPTER 6",
            "title": "EMPIRICAL BENCHMARK VALIDATION & REGRESSION GATES",
            "subtitle": "Automated Code Checks, Video Frame Decoding, and Subtitle Safe-Zones",
            "color": TEXT_GREEN,
            "col1_title": "THE DANGER OF MODEL SELF-APPROVAL",
            "col1_items": [
                "• LLMs self-evaluating their own code frequently report false PASS",
                "• Subjective confidence masks silent syntax, logic, and layout regressions",
                "• Production requires non-negotiable deterministic quality gates",
                "• Releases halt immediately if any automated acceptance check fails",
            ],
            "col2_title": "DETERMINISTIC MEDIA & CODE GATES",
            "col2_items": [
                "• Code Gates: Unit & integration test suites, strict type validation",
                "• Video Gates: Black-frame detection, frozen-frame checks, SAR 1:1, DAR 16:9",
                "• Audio Gates: Integrated LUFS loudness bounds, AV duration alignment",
                "• Subtitle Gates: 80% safe-zone margin inspection, word-level sync",
            ],
            "citation": "Code never reaches production based on model self-approval alone; verification must be empirical."
        },
        {
            "id": "ch07_cost_token_circuits",
            "badge": "SYSTEM ECONOMICS · CHAPTER 7",
            "title": "PRODUCTION COST, LATENCY & TOKEN CIRCUITS",
            "subtitle": "Per-Stage Ceilings, Automated Circuit Breakers, and Tiered Model Routing",
            "color": TEXT_RED,
            "col1_title": "ECONOMIC SAFEGUARDS",
            "col1_items": [
                "• Per-Stage Token Ceilings: Hard budget caps halt runaway retry loops",
                "• Automated Circuit Breakers: Stop execution on repeated identical errors",
                "• Exponential Backoff & Jitter: Protects API rate limit exhaustion",
                "• Real-Time Ledger: Dollar-denominated spend logged per turn",
            ],
            "col2_title": "TIERED MODEL ROUTING",
            "col2_items": [
                "• Frontier High-Reasoning Models: Architecture design, final editorial QA",
                "• Lightweight Fast Models: Unit test runners, transcription, formatting",
                "• Benchmark Evidence: Unconstrained retry loops rapidly exhaust context windows",
                "• Architectural Strategy: Tiered routing contains API spend during automated runs",
            ],
            "citation": "Without strict token budget circuits, runaway retry loops burn through API spend without resolving failures."
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
                "3. Supervisor-Worker SOP Hierarchy: Zero circular coordination deadlocks",
                "4. Automated Quality Gates: Non-negotiable empirical acceptance checks",
            ],
            "col2_title": "SHADOW SIMULATION & VERIFICATION",
            "col2_items": [
                "• Shadow Dry-Runs: Prove zero mutations and zero unverified side effects",
                "• Full mock transport verifies permission envelopes end-to-end",
                "• DORA 2024: Fast automated verification gates protect deployment stability",
                "• Canonical Citation: https://dora.dev/research/2024/dora-report/",
            ],
            "citation": "Comprehensive preflight verification and automated testing gates validate system state before changes deploy."
        },
    ]

    for ch in chapters:
        img = Image.new("RGBA", (w, h), BG_DARK)
        d = ImageDraw.Draw(img)
        draw_grid_background(d, w, h)

        # Main Card
        d.rounded_rectangle([80, 80, 1840, 940], radius=24, fill=CARD_BG, outline=ch["color"], width=3)
        d.text((120, 120), f"[ {ch['badge']} ]", fill=ch["color"], font=f_badge)
        d.text((120, 160), ch["title"], fill=TEXT_WHITE, font=f_title)
        d.text((120, 220), ch["subtitle"], fill=TEXT_MUTED, font=f_subtitle)

        # Left Column Box
        d.rounded_rectangle([120, 290, 940, 750], radius=16, fill=(15, 23, 42, 255), outline=BAR_BG, width=2)
        d.text((150, 320), ch["col1_title"], fill=ch["color"], font=f_badge)
        y = 380
        for item in ch["col1_items"]:
            d.text((150, y), item, fill=TEXT_WHITE, font=f_body)
            y += 80

        # Right Column Box
        d.rounded_rectangle([980, 290, 1800, 750], radius=16, fill=(15, 23, 42, 255), outline=BAR_BG, width=2)
        d.text((1010, 320), ch["col2_title"], fill=TEXT_CYAN, font=f_badge)
        y = 380
        for item in ch["col2_items"]:
            d.text((1010, y), item, fill=TEXT_WHITE, font=f_body)
            y += 80

        # Bottom Callout / Footnote
        d.rounded_rectangle([120, 780, 1800, 900], radius=12, fill=(15, 23, 42, 255), outline=CARD_BORDER, width=2)
        d.text((150, 805), "CORE ENGINEERING TAKEAWAY", fill=TEXT_CYAN, font=f_badge)
        d.text((150, 845), ch["citation"], fill=TEXT_WHITE, font=f_body)

        img.save(output_dir / f"{ch['id']}.png")

    print(f"Generated 8 Longform chapter graphics in {output_dir}")


if __name__ == "__main__":
    generate_short_graphics(Path("/tmp/scene_graphics/short"))
    generate_longform_graphics(Path("/tmp/scene_graphics/long"))
