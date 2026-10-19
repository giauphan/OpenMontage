# OpenMontage Module Ownership and Architectural Boundaries

## 1. Overview
OpenMontage enforces a clear separation between **agent instructions** (the intelligence), **tools & persistence** (Python implementations), and **composition runtimes** (FFmpeg, Remotion, HyperFrames).

## 2. Directory and Layer Ownership

### Layer 1: Core System & Tools (`tools/`)
- **Owner**: Core Platform Engineering
- **Contract**: Every tool inherits from `tools.base_tool.BaseTool`, returns `ToolResult`, and declares capability, tier, status, and parameters.
- **Discovery**: Dynamic discovery through `tools.tool_registry.ToolRegistry.discover()`. Modules must not emit side effects on import.
- **Key Modules**:
  - `tools/video/video_compose.py`: Public composition facade (`video_compose`).
  - `tools/video/_compose/`: Private modularized composition components (asset resolution, runtime policy, command construction).
  - `tools/video/hyperframes_compose.py`: HyperFrames runtime adapter.
  - `tools/video/video_stitch.py`: Clip concatenation and spatial validation.

### Layer 2: Pipeline Definitions & Skills (`pipeline_defs/`, `skills/`)
- **Owner**: AI Agent Orchestration & Production Engineering
- **Contract**:
  - `pipeline_defs/*.yaml`: Declarative stage definitions, required/fallback tools, approval gates.
  - `skills/pipelines/<pipeline>/<stage>-director.md`: Stage director prompts teaching agents how to produce canonical artifacts.
  - `skills/meta/`: Meta skills for reviewing (`reviewer.md`), checkpoint protocol (`checkpoint-protocol.md`), and onboarding.
- **Rule**: Pure Markdown and YAML. No Python orchestration code allowed here.

### Layer 3: External Vendor Knowledge (`.agents/skills/`)
- **Owner**: Vendor integrations & Prompt engineering
- **Contract**: Domain-specific guidance for external services (ElevenLabs, Runway, Seedance, Kling, etc.).

### Shared Infrastructure (`lib/`)
- **Owner**: Infrastructure Engineering
- **Contract**:
  - `lib/checkpoint.py`: Checkpoint persistence and stage gate enforcement.
  - `lib/pipeline_loader.py`: YAML manifest parsing, schema validation, and read-only caching.
  - `lib/media_profiles.py`: Encoding profiles and media presets.

### Composition Runtimes
- **Remotion**: `remotion-composer/` (React, TypeScript, Node.js).
- **HyperFrames**: `npx hyperframes` (HTML/CSS/GSAP).
- **FFmpeg**: Direct local CLI execution.

### User Interface & Observability (`backlot/`)
- **Owner**: Studio Board & Inspection Engineering
- **Contract**: Fast, passive observer of project workspaces (`projects/<project-id>/`). Never acts as an orchestrator or blocker.

## 3. Dependency Rules
1. `tools/` may import from `lib/`, but `lib/` must never import from `tools/`.
2. `tools/video/_compose/` internal modules must never import `tools.video.video_compose`.
3. Modules inside `tools/` must never define dynamic side effects at import time.
4. Production cleanup scripts (`scripts/check_cleanup_eligibility.py`) require verified publication evidence before marking projects eligible for cleanup.
