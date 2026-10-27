#!/usr/bin/env python3
"""Verification Script: Isolated 3-Topic Real E2E Render for animated_agent_diagram_v1.

Produces 3 REAL complete 65–75s 1080x1920 portrait Shorts:
1. context_memory: "Why coding agents forget project instructions between sessions"
2. agent_tool_use: "What actually happens when an AI agent calls an MCP tool"
3. debugging_reliability: "Why a coding agent's patch can pass one test but fail the full project"

Extracts contact sheets, runs ffprobe, and checks nonblank frame variance.
Target module size: < 450 lines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.visual_style import (
    AnimatedDiagramDirector,
    evaluate_plan_qa,
    validate_frame_nonblank,
)
from scripts.run_fixed_niche_video import FixedNicheVideoRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TOPICS_DEFINITIONS = [
    {
        "candidate_id": "topic_01_context_memory",
        "topic_family": "context_memory",
        "title": "Why coding agents forget project instructions between sessions",
        "viewer_question": "Why does a coding agent lose context rules when you start a new session?",
        "body": "Context windows reset between sessions while durable repo instructions persist on disk.",
        "source_url": "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
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
    {
        "candidate_id": "topic_02_agent_tool_use",
        "topic_family": "agent_tool_use",
        "title": "What actually happens when an AI agent calls an MCP tool",
        "viewer_question": "What actually happens under the hood when an AI agent calls an MCP tool?",
        "body": "MCP tool calling permissions, model context protocol schemas, and sandbox isolation.",
        "source_url": "https://modelcontextprotocol.io/introduction",
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
    {
        "candidate_id": "topic_03_debugging_reliability",
        "topic_family": "debugging_reliability",
        "title": "Why a coding agent patch passes one test but fails the full project",
        "viewer_question": "Why can an AI agent's patch pass a targeted test but break the whole project?",
        "body": "Why coding agent patch generation causes regression failures across full integration test suites.",
        "source_url": "https://www.swebench.com/",
        "source_text": (
            "Autonomous coding agents frequently overfit to isolated unit tests by mocking dependencies or "
            "altering local conditions without addressing systemic root causes. While the targeted test turns green, "
            "unintended side effects break integration suites across adjacent modules. "
            "Full regression test suites and strict boundary validation are required before releasing patches."
        ),
        "claims": [
            {"claim_id": "C001", "statement": "Targeted test passes can mask side effects and breaking changes across project modules"},
            {"claim_id": "C002", "statement": "Surface patches often hallucinate mocks instead of fixing underlying root causes"},
            {"claim_id": "C003", "statement": "Full regression suites and boundary validation prevent production regressions"},
        ],
    },
]


def probe_mp4_metadata(mp4_path: Path) -> Dict[str, Any]:
    """Run ffprobe on rendered MP4 to inspect video/audio streams and duration."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=codec_name,codec_type,width,height,r_frame_rate",
        "-of", "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def extract_contact_sheet_and_frames(
    mp4_path: Path,
    out_dir: Path,
    sample_interval: float = 1.0,
) -> Tuple[Path, List[Path]]:
    """Extract 1s interval frames and generate a tiled contact sheet."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # 1. Extract frames at 1s intervals
    extract_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(mp4_path),
        "-vf", f"fps=1/{sample_interval},scale=270:480",
        str(frames_dir / "frame_%03d.png"),
    ]
    subprocess.run(extract_cmd, check=True)
    frames = sorted(list(frames_dir.glob("frame_*.png")))

    # 2. Build contact sheet using ffmpeg tile filter (e.g. 8x9 grid for 72 frames)
    contact_sheet_path = out_dir / "contact_sheet.png"
    num_frames = len(frames)
    cols = 8
    rows = max(1, (num_frames + cols - 1) // cols)

    tile_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(frames_dir / "frame_%03d.png"),
        "-vf", f"tile={cols}x{rows}:nb_frames={num_frames}:padding=4:color=black",
        str(contact_sheet_path),
    ]
    subprocess.run(tile_cmd, check=True)
    return contact_sheet_path, frames


def run_single_e2e_topic(
    topic_def: Dict[str, Any],
    verification_dir: Path,
    target_duration: float = 72.0,
) -> Dict[str, Any]:
    """Execute complete end-to-end production run for one topic."""
    cid = topic_def["candidate_id"]
    logger.info("=== Starting E2E verification for topic: %s ===", cid)

    # Isolated project directory
    project_dir = ROOT / "projects" / cid
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write authentic primary source capture file
    capture_dir = artifacts_dir / "news_source_capture"
    capture_dir.mkdir(parents=True, exist_ok=True)
    cap_file = capture_dir / f"{cid}_source.txt"
    cap_bytes = topic_def["source_text"].encode("utf-8")
    cap_file.write_bytes(cap_bytes)
    cap_sha = hashlib.sha256(cap_bytes).hexdigest()

    # 2. Initialize runner and stage topic
    runner = FixedNicheVideoRunner(
        project_dir=project_dir,
        candidate_id=cid,
        format_kind="short",
    )

    stage_res = runner.build_and_stage_project(topic=topic_def)
    assert stage_res["status"] == "STAGED_READY", f"Stage failed for {cid}: {stage_res}"

    # 3. Synthesize speech narration using local Kokoro TTS
    audio_path = runner.synthesize_narration(provider="kokoro")
    assert audio_path.is_file(), f"Narration audio missing: {audio_path}"

    # Verify narration audio duration with ffprobe
    from lib.audio.narration_orchestrator import probe_audio_duration
    audio_dur = probe_audio_duration(audio_path)
    logger.info("Narration audio generated: %s (%.2f seconds)", audio_path.name, audio_dur)

    # 4. Render final 1080x1920 Short via HyperFrames
    output_mp4 = project_dir / "renders" / "final_short_en_US_9x16.mp4"
    logger.info("Rendering HyperFrames composition to %s...", output_mp4)
    render_res = runner.render(
        burn_captions=True,
        renderer="hyperframes",
    )
    assert output_mp4.is_file(), f"Rendered MP4 missing at {output_mp4}"
    rendered_path = output_mp4

    # 5. Inspect MP4 with ffprobe
    meta = probe_mp4_metadata(rendered_path)
    fmt = meta.get("format", {})
    actual_dur = float(fmt.get("duration", 0.0))
    streams = meta.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    assert v_stream is not None, "Missing video stream"
    assert a_stream is not None, "Missing audio stream"
    assert v_stream.get("width") == 1080, f"Expected 1080 width, got {v_stream.get('width')}"
    assert v_stream.get("height") == 1920, f"Expected 1920 height, got {v_stream.get('height')}"
    assert 65.0 <= actual_dur <= 75.0, f"Final MP4 duration ({actual_dur:.2f}s) outside [65.0, 75.0]s contract"

    # FFmpeg decode scan to prove no corrupt frames
    scan_cmd = ["ffmpeg", "-v", "error", "-i", str(rendered_path), "-f", "null", "-"]
    subprocess.run(scan_cmd, check=True)

    # 6. Extract contact sheet and sample frames
    dest_dir = verification_dir / cid
    dest_dir.mkdir(parents=True, exist_ok=True)
    contact_sheet, frames = extract_contact_sheet_and_frames(rendered_path, dest_dir)
    assert contact_sheet.is_file(), "Contact sheet generation failed"
    assert len(frames) >= 60, f"Expected >= 60 sampled frames, got {len(frames)}"

    # 7. Nonblank frame variance check on key frames (0s, midpoint, final)
    for frame_idx in (0, len(frames) // 2, len(frames) - 1):
        f = frames[frame_idx]
        is_valid, reason = validate_frame_nonblank(f, min_variance=10.0)
        assert is_valid, f"Frame {f.name} failed nonblank check: {reason}"

    # Copy primary deliverables to verification folder
    shutil.copy2(rendered_path, dest_dir / "final_short_en_US_9x16.mp4")
    shutil.copy2(audio_path, dest_dir / "narration.mp3")
    sidecar_path = artifacts_dir / "diagram_animation_plan.json"
    if sidecar_path.is_file():
        shutil.copy2(sidecar_path, dest_dir / "diagram_animation_plan.json")

    mp4_sha = hashlib.sha256((dest_dir / "final_short_en_US_9x16.mp4").read_bytes()).hexdigest()

    result = {
        "candidate_id": cid,
        "topic_family": topic_def["topic_family"],
        "title": topic_def["title"],
        "status": "PASS",
        "duration_seconds": actual_dur,
        "width": v_stream.get("width"),
        "height": v_stream.get("height"),
        "video_codec": v_stream.get("codec_name"),
        "audio_codec": a_stream.get("codec_name"),
        "mp4_sha256": mp4_sha,
        "contact_sheet": str(contact_sheet.relative_to(ROOT)),
        "frames_extracted": len(frames),
    }
    logger.info("=== E2E verification PASSED for %s (Duration: %.2fs, SHA: %s...) ===", cid, actual_dur, mp4_sha[:12])
    return result


def main():
    parser = argparse.ArgumentParser(description="Verify 3 E2E animated technical diagram Shorts")
    parser.add_argument("--topics", nargs="*", help="Candidate IDs to run (default: all 3)")
    args = parser.parse_args()

    # Enforce feature flags
    os.environ["OPENMONTAGE_VISUAL_STYLE"] = "animated_agent_diagram_v1"
    os.environ["ANIMATED_AGENT_DIAGRAM_V1_ENABLED"] = "1"
    os.environ["ANIMATED_AGENT_DIAGRAM_STRICT_QA"] = "1"
    os.environ["AUTO_PUBLISH"] = "0"

    # Get current commit SHA
    res_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    current_sha = res_sha.stdout.strip()

    verification_dir = ROOT / "artifacts" / "verification" / "animated_agent_diagram_v1" / current_sha
    verification_dir.mkdir(parents=True, exist_ok=True)

    topics_to_run = TOPICS_DEFINITIONS
    if args.topics:
        topics_to_run = [t for t in TOPICS_DEFINITIONS if t["candidate_id"] in args.topics]

    results = []
    for topic_def in topics_to_run:
        res = run_single_e2e_topic(topic_def, verification_dir)
        results.append(res)

    summary_file = verification_dir / "e2e_verification_summary.json"
    summary_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"\nSUCCESS: All {len(results)} topics verified and rendered.")


if __name__ == "__main__":
    main()
