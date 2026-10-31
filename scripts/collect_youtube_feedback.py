#!/usr/bin/env python3
"""Collects and maps YouTube audience feedback and retention curves for local projects.

Usage:
    python scripts/collect_youtube_feedback.py --project-dir outputs/projects/my_project --output-json report.json
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.youtube_feedback.retention_mapper import (
    SceneTiming,
    generate_hypotheses_from_analysis,
    map_retention_curve,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("collect_youtube_feedback")


def _load_scenes_from_project(project_dir: Path) -> tuple[float, list[SceneTiming]]:
    """Extracts scene timings and total duration from a project directory."""
    scenes: list[SceneTiming] = []
    duration = 0.0

    # 1. Primary OpenMontage path: artifacts/news_visual_plan.json
    plan_candidates = [
        project_dir / "artifacts" / "news_visual_plan.json",
        project_dir / "visual_plan.json",
        project_dir / "scenes.json",
    ]

    for plan_file in plan_candidates:
        if plan_file.is_file():
            try:
                data = json.loads(plan_file.read_text(encoding="utf-8"))
                # Check for beats (news_visual_plan format)
                beats = data.get("beats", [])
                if beats:
                    for b in beats:
                        bid = b.get("id") or b.get("beat_id") or "beat"
                        start = float(b.get("start_seconds", 0.0))
                        end = float(b.get("end_seconds", start))
                        fn = b.get("story_function", "")
                        scenes.append(SceneTiming(scene_id=bid, start_time=start, end_time=end, story_function=fn))
                        if end > duration:
                            duration = end
                    break

                # Fallback to scenes format
                scene_list = data.get("scenes", [])
                if scene_list:
                    for sc in scene_list:
                        sid = sc.get("scene_id") or f"scene_{sc.get('scene_index', 0):03d}"
                        start = float(sc.get("start_time", 0.0))
                        end = float(sc.get("end_time", start + float(sc.get("duration", 0.0))))
                        fn = sc.get("story_function", "")
                        scenes.append(SceneTiming(scene_id=sid, start_time=start, end_time=end, story_function=fn))
                        if end > duration:
                            duration = end
                    break
            except Exception as e:
                logger.warning("Failed parsing %s: %s", plan_file, e)

    if not scenes:
        # Fallback to audio_manifest.json or default placeholder
        audio_manifest = project_dir / "audio_manifest.json"
        if audio_manifest.is_file():
            try:
                adata = json.loads(audio_manifest.read_text(encoding="utf-8"))
                duration = float(adata.get("duration_seconds", 60.0))
                scenes.append(SceneTiming(scene_id="scene_001_full", start_time=0.0, end_time=duration))
            except Exception:
                pass

    return duration or 60.0, scenes


def main() -> int:
    parser = argparse.ArgumentParser(description="Map YouTube retention curve to video scenes")
    parser.add_argument("--project-dir", type=Path, default=None, help="Path to project directory")
    parser.add_argument("--video-id", type=str, default="", help="YouTube video ID")
    parser.add_argument("--retention-curve-file", type=Path, default=None, help="Path to JSON file with curve data")
    parser.add_argument("--output-json", type=Path, default=None, help="Where to write analysis report")
    args = parser.parse_args()

    duration = 60.0
    scenes: list[SceneTiming] = []
    project_id = ""

    if args.project_dir and args.project_dir.is_dir():
        project_id = args.project_dir.name
        duration, scenes = _load_scenes_from_project(args.project_dir)

    curve_data: list[tuple[float, float]] = []
    if args.retention_curve_file and args.retention_curve_file.is_file():
        try:
            raw = json.loads(args.retention_curve_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        curve_data.append((float(item[0]), float(item[1])))
                    elif isinstance(item, dict):
                        elapsed = item.get("elapsedVideoTimeRatio")
                        watch = item.get("audienceWatchRatio")
                        if elapsed is not None and watch is not None:
                            curve_data.append((float(elapsed), float(watch)))
        except Exception as e:
            logger.warning("Failed to parse retention curve file: %s", e)

    analysis = map_retention_curve(
        duration_seconds=duration,
        retention_curve=curve_data,
        scenes=scenes,
        video_id=args.video_id,
        project_id=project_id,
    )

    hypotheses = generate_hypotheses_from_analysis(analysis)

    report = {
        "status": analysis.status,
        "video_id": analysis.video_id,
        "project_id": analysis.project_id,
        "duration_seconds": analysis.duration,
        "points_count": len(analysis.points),
        "scene_retention": analysis.scene_retention,
        "dropoffs_count": len(analysis.dropoffs),
        "spikes_count": len(analysis.spikes),
        "hypotheses": [
            {
                "observation": h.observation,
                "scene_id": h.scene_id,
                "confidence": h.confidence,
                "proposed_change": h.proposed_change,
                "owner_status": h.owner_status,
                "recheck_date": h.recheck_date,
            }
            for h in hypotheses
        ],
    }

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Saved retention feedback report to %s", args.output_json)
    else:
        print(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
