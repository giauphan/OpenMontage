#!/usr/bin/env python3
"""Animated Diagram Template Generator for Practical AI Agent Engineering Shorts.

Creates and renders animated technical diagram templates matching the Excalidraw/blackboard
interactive engineering style (as seen in Claude Code Mods reference).

Target module size: < 450 lines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
import re
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fixed_niche_video import FixedNicheVideoRunner
from lib.visual_style.layouts import build_preset_graph, get_layout_preset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BUILTIN_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "claude_code_mods": {
        "candidate_id": "template_claude_code_mods",
        "topic_family": "agent_architecture",
        "layout_preset": "agent_harness_mods",
        "layout_preset": "agent_harness_mods",
        "title": "What are Claude Code Mods: Inside the Agent Harness",
        "viewer_question": "Why are Claude Code mods fundamentally different from hooks and MCP tools?",
        "body": "Claude Code mods run inside the agent harness itself to govern agentic workflow and subagent execution.",
        "source_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
        "retrieval_method": "OFFLINE_VERIFIED_PRIMARY_MIRROR",
        "is_offline_test_fixture": True,
        "source_text": (
            "Claude Code introduces internal harness mods that execute directly within the agent process lifecycle. "
            "Unlike external MCP servers or single-event shell hooks, mods maintain state across session turns, "
            "render persistent live terminal panels, and intercept commands before execution. "
            "This architectural shift enables deep agent harness control without external daemon dependencies."
        ),
        "claims": [
            {"claim_id": "C001", "statement": "External extensions like MCP and shell hooks execute outside the core agent process"},
            {"claim_id": "C002", "statement": "Internal mods run inside the agent harness to intercept actions before execution"},
            {"claim_id": "C003", "statement": "Persistent mods maintain state across session turns for live panels and action guards"},
        ],
    },
    "context_memory": {
        "candidate_id": "template_context_memory",
        "topic_family": "context_memory",
        "layout_preset": "context_boundary",
        "title": "Why Coding Agents Forget Project Instructions Between Sessions",
        "viewer_question": "Why does a coding agent lose context rules when you start a new session?",
        "body": "Context windows reset between sessions while durable repo instructions persist on disk.",
        "source_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
        "retrieval_method": "OFFLINE_VERIFIED_PRIMARY_MIRROR",
        "is_offline_test_fixture": True,
        "source_text": (
            "Context windows in large language models represent volatile working memory held in RAM. "
            "When an agent session terminates or resets, conversation history and in-memory instructions disappear. "
            "To survive session resets, instructions must be stored in durable repository files like AGENTS.md, "
            "which are automatically read during agent bootstrap initialization."
        ),
        "claims": [
            {"claim_id": "C001", "statement": "Conversation context in RAM disappears upon session reset or exit"},
            {"claim_id": "C002", "statement": "Durable repo instructions like AGENTS.md persist on disk across sessions"},
            {"claim_id": "C003", "statement": "Automated bootstrap protocols reload durable instructions to guarantee reliability"},
        ],
    },
    "agent_tool_use": {
        "candidate_id": "template_agent_tool_use",
        "topic_family": "agent_tool_use",
        "layout_preset": "tool_permission_path",
        "title": "What Actually Happens When an AI Agent Calls an MCP Tool",
        "viewer_question": "What actually happens under the hood when an AI agent calls an MCP tool?",
        "body": "MCP tool calling permissions, model context protocol schemas, and sandbox isolation.",
        "source_url": "https://modelcontextprotocol.io/introduction",
        "retrieval_method": "OFFLINE_VERIFIED_PRIMARY_MIRROR",
        "is_offline_test_fixture": True,
        "source_text": (
            "The Model Context Protocol defines an open JSON-RPC standard for agent tool discovery and execution. "
            "When an agent calls a tool, the client validates the parameter payload against the tool's JSON schema. "
            "Security policies inspect the call at the sandbox boundary before authorized execution. "
            "Structured results are returned with strict boundary validation before LLM interpretation."
        ),
        "claims": [
            {"claim_id": "C001", "statement": "Agents parse and validate tool schema contracts via Model Context Protocol JSON-RPC"},
            {"claim_id": "C002", "statement": "Security boundaries enforce policy authorization before tool execution"},
            {"claim_id": "C003", "statement": "Structured return payloads pass boundary validation before LLM reasoning"},
        ],
    },
}


def normalize_topic_definition(topic_def: Dict[str, Any]) -> Dict[str, Any]:
    """Map a template topic brief into the fixed-niche runner's evidence contract."""
    topic = dict(topic_def)
    source_text = topic.get("source_text") or topic.get("source_snapshot")
    if not isinstance(source_text, str) or len(source_text.strip()) < 30:
        raise ValueError("topic source_text must contain at least 30 characters of source material")
    source_text = source_text.strip()
    supplied_sha = topic.get("snapshot_sha256")
    computed_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if supplied_sha and str(supplied_sha).lower() != computed_sha:
        raise ValueError("snapshot_sha256 does not match the supplied source_text")

    raw_claims = topic.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ValueError("topic claims must be a non-empty list")
    claims = []
    for index, claim in enumerate(raw_claims, start=1):
        statement = claim.get("statement") if isinstance(claim, dict) else claim
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"claim {index} must be a non-empty string or an object with a statement")
        claims.append(statement.strip())
    if not claims:
        raise ValueError("topic claims must contain at least one usable statement")

    topic["source_text"] = source_text
    topic["source_snapshot"] = source_text
    topic["snapshot_sha256"] = computed_sha
    topic["body"] = str(topic.get("body") or topic.get("summary") or source_text)
    topic["claims"] = claims
    topic["canonical_url"] = topic.get("canonical_url") or topic.get("source_url") or topic.get("url")
    topic["url"] = topic["canonical_url"]
    if not isinstance(topic["canonical_url"], str) or not topic["canonical_url"].startswith("https://"):
        raise ValueError("topic must provide an https canonical_url or source_url")
    topic["publisher"] = topic.get("publisher") or "User-provided primary source"
    topic["is_evergreen"] = True
    topic["layout_preset"] = get_layout_preset(topic.get("layout_preset") or topic.get("topic_family", ""))
    if topic["layout_preset"] not in {
        "context_boundary", "tool_permission_path", "agent_retry_loop",
        "agent_harness_mods", "eval_breakdown", "persistent_agent_flow",
    }:
        raise ValueError("layout_preset/topic_family must select a supported reusable diagram layout")
    return topic


def create_template_package(template_name: str, project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Write a reusable visual template definition without fabricating sourced claims."""
    topic = BUILTIN_TEMPLATES[template_name]
    layout_preset = get_layout_preset(topic.get("layout_preset") or topic["topic_family"])
    template_id = f"chalkboard_{layout_preset}"
    project_id = f"{template_id}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{time.time_ns() % 1_000_000_000:09d}"
    if project_dir is None:
        projects_root = (ROOT / "projects").resolve()
        if not os.access(projects_root, os.W_OK):
            projects_root = Path("/tmp/projects")
        project_dir = projects_root / project_id
    else:
        project_dir = Path(project_dir).resolve()
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    graph_skeleton = build_preset_graph(layout_preset, topic["title"]).to_dict()
    for node in graph_skeleton["nodes"]:
        node["label"] = "{{" + node["id"] + "_label}}"
    for edge in graph_skeleton["edges"]:
        edge["label"] = "{{" + edge["id"] + "_label}}"

    template = {
        "version": "1.0",
        "template_id": template_id,
        "name": template_name,
        "layout_preset": layout_preset,
        "reference_video": "plan/pending/YTSave.to_Shorts_Media_eN77oHqAiUU_What-Are-Claude-Code-Mods_002_720p.mp4",
        "format": {"width": 1080, "height": 1920, "aspect_ratio": "9:16"},
        "visual_system": {
            "background": "#090A0C",
            "texture": "subtle speckled board",
            "chalk_colors": {
                "primary_system": "#F28C7A",
                "main_concept": "#46D9D1",
                "secondary_labels": "#B7A0F5",
                "callouts": "#F0D94E",
                "body": "#F1EEE8",
            },
            "reveal": "draw the diagram progressively in narration order",
        },
        "beat_templates": [
            "hook", "establish_system", "introduce_mechanism", "trace_flow",
            "show_use_case", "compare_alternative", "connect_model", "takeaway",
        ],
        "graph_skeleton": graph_skeleton,
        "content_policy": "Replace all labels and claims with topic-specific, source-backed content before production.",
    }
    output_path = artifacts_dir / "visual_template.json"
    output_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return {
        "status": "TEMPLATE_READY",
        "template_id": template_id,
        "template_path": str(output_path),
        "project_dir": str(project_dir),
    }


def build_and_render_diagram_template(
    topic_def: Dict[str, Any],
    project_dir: Optional[Path] = None,
    render_video: bool = True,
    tts_provider: str = "kokoro",
) -> Dict[str, Any]:
    """Execute complete staging and rendering for an animated diagram template."""
    os.environ.setdefault("OPENMONTAGE_VISUAL_STYLE", "animated_agent_diagram_v1")
    os.environ.setdefault("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "1")
    os.environ.setdefault("ANIMATED_AGENT_DIAGRAM_STRICT_QA", "1")
    os.environ.setdefault("AUTO_PUBLISH", "0")

    topic_def = normalize_topic_definition(topic_def)
    requested_id = str(topic_def.get("candidate_id") or topic_def.get("id") or "").strip()
    if not requested_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,79}", requested_id):
        raise ValueError("topic candidate_id must be 2-80 letters, digits, '_' or '-' and start with a letter or digit")
    if project_dir is None:
        cid = f"{requested_id}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{time.time_ns() % 1_000_000_000:09d}"
        projects_root = (ROOT / "projects").resolve()
        if not os.access(projects_root, os.W_OK):
            projects_root = Path("/tmp/projects")
        project_dir = projects_root / cid
    else:
        project_dir = Path(project_dir).resolve()
        cid = project_dir.name
    topic_def = dict(topic_def)
    topic_def["candidate_id"] = cid
    if project_dir.exists():
        raise FileExistsError(f"project output already exists; choose a new project ID: {project_dir}")

    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Stage offline primary source mirror fixture
    capture_dir = artifacts_dir / "news_source_capture"
    capture_dir.mkdir(parents=True, exist_ok=True)
    cap_file = capture_dir / f"{cid}_source.txt"
    cap_bytes = topic_def["source_text"].encode("utf-8")
    cap_file.write_bytes(cap_bytes)
    cap_sha = hashlib.sha256(cap_bytes).hexdigest()

    fixture_prov = {
        "candidate_id": cid,
        "is_offline_test_fixture": bool(topic_def.get("is_offline_test_fixture", False)),
        "retrieval_method": topic_def.get("retrieval_method", "USER_PROVIDED_SOURCE"),
        "source_url": topic_def.get("source_url"),
        "sha256": cap_sha,
    }
    (capture_dir / f"{cid}_provenance.json").write_text(json.dumps(fixture_prov, indent=2), encoding="utf-8")

    # 2. Stage fixed niche project
    runner = FixedNicheVideoRunner(
        project_dir=project_dir,
        candidate_id=cid,
        format_kind="short",
    )
    stage_res = runner.build_and_stage_project(topic=topic_def)
    if stage_res["status"] != "STAGED_READY":
        raise RuntimeError(f"Failed to stage template {cid}: {stage_res}")

    result: Dict[str, Any] = {
        "candidate_id": cid,
        "status": "STAGED_READY",
        "project_dir": str(project_dir),
        "diagram_plan_path": str(artifacts_dir / "diagram_animation_plan.json"),
    }
    if (artifacts_dir / "diagram_animation_plan.json").is_file():
        diagram_plan = json.loads((artifacts_dir / "diagram_animation_plan.json").read_text(encoding="utf-8"))
        result["template_id"] = diagram_plan.get("template_id")

    if render_video:
        # 3. Synthesize narration
        audio_path = runner.synthesize_narration(provider=tts_provider)
        # 4. Render HyperFrames animated composition
        render_res = runner.render(burn_captions=True, renderer="hyperframes")
        output_mp4 = project_dir / "renders" / "final_short_en_US_9x16.mp4"
        result.update({
            "status": "RENDERED",
            "audio_path": str(audio_path),
            "rendered_mp4": str(output_mp4),
            "render_result": render_res,
        })

    return result


def main():
    parser = argparse.ArgumentParser(description="Create and render animated diagram templates")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preset",
        choices=list(BUILTIN_TEMPLATES.keys()),
        help="Create a reusable visual template package from a built-in layout",
    )
    mode.add_argument(
        "--topic-json",
        type=Path,
        help="Render a sourced topic brief with candidate_id, title, topic_family, viewer_question, source_text, source_url, and claims",
    )
    parser.add_argument(
        "--project-id",
        help="Output project ID (a UTC timestamp suffix is added to prevent collisions)",
    )
    parser.add_argument(
        "--template-json",
        type=Path,
        help="Apply a visual_template.json package created by --preset",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="Explicit target directory for project artifacts and renders",
    )
    parser.add_argument("--render", action="store_true", help="Render video for the chosen preset")
    parser.add_argument("--no-render", action="store_true", help="Stage template artifacts without rendering MP4")
    parser.add_argument("--tts", default="kokoro", help="TTS provider (kokoro, flite, edge-tts)")
    args = parser.parse_args()

    if args.preset and not args.render:
        if args.project_id or args.no_render:
            parser.error("--project-id and --no-render apply only when rendering")
        print(json.dumps(create_template_package(args.preset, project_dir=args.project_dir), indent=2))
        return

    # Enforce animated diagram visual style flags
    os.environ["OPENMONTAGE_VISUAL_STYLE"] = "animated_agent_diagram_v1"
    os.environ["ANIMATED_AGENT_DIAGRAM_V1_ENABLED"] = "1"
    os.environ["ANIMATED_AGENT_DIAGRAM_STRICT_QA"] = "1"
    os.environ["AUTO_PUBLISH"] = "0"

    if args.topic_json:
        topic_def = json.loads(args.topic_json.read_text(encoding="utf-8"))
        if not isinstance(topic_def, dict):
            parser.error("--topic-json must contain a JSON object")
        missing = [key for key in ("title", "topic_family", "viewer_question", "source_text", "claims") if not topic_def.get(key)]
        if missing:
            parser.error("--topic-json is missing required fields: " + ", ".join(missing))
        if args.template_json:
            template = json.loads(args.template_json.read_text(encoding="utf-8"))
            if not isinstance(template, dict) or not template.get("template_id") or not template.get("layout_preset"):
                parser.error("--template-json must be a visual_template.json package with template_id and layout_preset")
            topic_def["layout_preset"] = template["layout_preset"]
            expected_template_id = f"chalkboard_{get_layout_preset(topic_def['layout_preset'])}"
            if template["template_id"] != expected_template_id:
                parser.error("template_id does not match the template package layout_preset")
        topic_def.setdefault("candidate_id", args.project_id or f"topic_{int(time.time())}")
        if args.project_id:
            topic_def["candidate_id"] = args.project_id
        template_name = "custom topic"
    elif args.preset:
        topic_def = dict(BUILTIN_TEMPLATES[args.preset])
        if args.project_id:
            topic_def["candidate_id"] = args.project_id
        template_name = args.preset
    else:
        parser.error("Either --preset or --topic-json must be specified")
    logger.info("Executing diagram template generator for %s", template_name)

    try:
        res = build_and_render_diagram_template(
            topic_def=topic_def,
            project_dir=args.project_dir,
            render_video=not args.no_render,
            tts_provider=args.tts,
        )
    except (FileExistsError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    print(json.dumps(res, indent=2))
    logger.info("Template execution completed successfully.")


if __name__ == "__main__":
    main()
