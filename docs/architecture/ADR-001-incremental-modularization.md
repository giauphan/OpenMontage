# ADR-001: Incremental Capability Modularization for OpenMontage Hotspots

## Status
Accepted (Phase 0 Baseline, 2026-10-19)

## Context
OpenMontage is an instruction-driven, agent-first video production platform where AI agents act as the production control plane (guiding pipeline stages, reviews, and checkpoints) and Python provides tools and persistence.

Over iterative development, core tools accumulated multiple concerns. In particular:
- `tools/video/video_compose.py` (2,915 physical LOC, cyclomatic complexity ~396) currently combines:
  1. Input parameter validation and cut sequence validation
  2. Asset path resolution and media file inspection
  3. Render runtime selection and policy enforcement (`remotion`, `hyperframes`, `ffmpeg`)
  4. FFmpeg filtergraph construction and execution
  5. Remotion payload assembly, props formatting, and CLI execution
  6. Subtitle burning, transitions, and overlays
  7. Output post-processing and render report generation

Refactoring this hotspot is required to improve maintainability, isolated testability, and clarity of boundaries. However, refactoring must NOT:
- Alter the agent control plane or introduce Python stage orchestrators
- Alter public tool names, schemas, or `BaseTool` discovery mechanisms
- Allow silent runtime fallback (e.g., Remotion falling back to Ken Burns / FFmpeg when Remotion fails)
- Break existing pipeline manifests (`pipeline_defs/*.yaml`) or stage director skills (`skills/pipelines/*`)

## Decision
We choose **Option A: Contract-first incremental modularization behind existing facades**.

Key rules of this architecture:
1. **Preserve Public Façade**: `VideoCompose` in `tools/video/video_compose.py` remains the canonical `BaseTool` subclass registered in `tools.tool_registry` under the tool name `video_compose`.
2. **Private Helper Package**: Cohesive responsibilities are extracted into internal modules under `tools/video/_compose/`.
3. **No Dynamic Discovery Pollution**: Modules inside `_compose/` MUST NOT declare concrete `BaseTool` subclasses, ensuring the registry discovery count and tool catalog remain strictly identical.
4. **No Reverse Imports (Acyclic Dependency Graph)**: Internal helpers in `_compose/` must never import `tools.video.video_compose`. Dependencies strictly flow inward: `video_compose.py` -> `_compose/*`.
5. **Pure Functions First**: Extract deterministic helpers (validation, path/asset resolution, payload shaping) before subprocess/render wrappers.
6. **Strict Governance & Fail-Closed Runtime Policy**: When a chosen `render_runtime` is unavailable or fails, it raises an explicit error/blocker rather than silently substituting an alternative runtime.

## Consequences

### Positive
- Individual concerns (e.g. asset resolution, payload creation) become independently unit-testable without invoking FFmpeg or Node subprocesses.
- Cyclomatic complexity of `video_compose.py` is substantially reduced.
- No breaking changes for pipelines, stage directors, or external callers.
- Reversible via single git revert.

### Negative / Trade-offs
- Requires maintaining the public `VideoCompose` class as a delegating coordinator.
- Requires rigorous contract tests to ensure no regressions in parameter defaults or output formats.

## Compliance and Verification
- Characterization tests (`tests/contracts/test_video_compose_stability.py`) freeze the exact tool contract before refactoring.
- Tool registry parity test (`tests/contracts/test_tool_registry_parity.py`) verifies tool counts and schemas before and after extractions.
- Import cycle tests ensure no circular dependencies.
