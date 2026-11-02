# Agent Pipeline Flow Template Package (`agent-pipeline-flow`)

Official OpenMontage reusable template package for **Practical AI Agent Engineering** technical explainers and architecture breakdowns.

## Overview

- **Package ID**: `agent-pipeline-flow`
- **Version**: `1.0.0`
- **Variants**:
  - `short`: 9:16 vertical (1080x1920) optimized for YouTube Shorts, Instagram Reels, and TikTok.
  - `full`: 16:9 horizontal (1920x1080) for YouTube full explainers.
- **Visual Style**: Progressive SVG diagram flows with voice-ordered step reveals, telemetry metric gauges, interactive circuit switches, 3-state relay finite-state machines, and persistent CTA banner.

## Guaranteed Timing & Hold Contract

This template strictly enforces our **Domain-Driven Design Timing Contract**:
1. **Sequential Step Reveals**: Blocks pop in progressively synchronized with voice narration phrasing and ASR word timestamps.
2. **Completed Diagram Hold Time (2.0s – 4.0s)**:
   For standard scenes ($1 \le i \le N-1$), the final step appears early enough to guarantee:
   $$\text{hold\_time} = \min(4.0\text{s}, \max(2.5\text{s}, \text{duration} \times 0.28))$$
   The completed diagram state remains displayed until the scene exit transition, ensuring the viewer can fully absorb the full pipeline flow before switching screens.
3. **Final Scene CTA Persistence ($\ge 5.0\text{s}$)**:
   In the final summary scene, all pipeline stages reveal within the first $48\%$ of the scene window ($\le 5.5\text{s}$). The *"Follow me for Daily Agent Engineering Patterns"* CTA banner reveals $\sim 1.0\text{s}$ later, and **all elements persist until the very end of the video ($t=\text{duration}$)**.

## Package Structure

```
templates/agent_engineering/packages/agent-pipeline-flow/
├── content.schema.json             # JSON Schema validating all input fields
├── README.md                       # Architecture & timing contract documentation
├── fixtures/
│   └── short_circuit_breakers.json # Reference candidate fixture (cand_mcp_circuit_breakers_oct31)
├── hyperframes_reels/
│   └── index.html                  # 9:16 vertical composition template
└── hyperframes/
    └── index.html                  # 16:9 horizontal composition template
```

## Supported Topic Families

Defined in `content.schema.json`:
- `agent_tool_use`: MCP server resilience, schema validation boundaries, retry isolation.
- `context_memory`: Session boundary persistence, volatile memory resets, deterministic state contracts.
- `debugging_reliability`: Hermetic bug reproduction, test assertions before git commit.
- `agent_evaluation`: Multi-seed deterministic evaluation matrices, flake detection.
- `agent_architecture`: Typed immutable state handoffs between parent and worker agents.
