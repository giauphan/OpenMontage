#!/usr/bin/env python3
"""Gate 2: QA check for render-ready candidates.

Takes project directories (or a projects root) as arguments instead of
hardcoding container paths and candidate IDs, so the same gate runs on a
developer checkout, in CI, and on the publish host.

Usage:
  python3 scripts/check_qa.py projects/cand_abc projects/cand_def
  python3 scripts/check_qa.py --projects-root projects
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

FULL_RENDER = "renders/final_full_vi_9x16.mp4"
REELS_RENDER = "renders/final_reels_vi_9x16.mp4"
NARRATION_CANDIDATES = ("assets/narration.mp3", "assets/voice/narration.mp3")
DEFAULT_TOLERANCE = 3.0
REELS_MAX_SECONDS = 60.0


def duration(path: Path, ffprobe: str) -> float | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return float(lines[-1])
    except ValueError:
        return None


def stream_info(path: Path, ffprobe: str, selector: str) -> str:
    if not path.is_file():
        return "MISSING"
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", selector,
         "-show_entries", "stream=codec_name,width,height", "-of", "csv=p=0", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "?"


def narration_path(project: Path) -> Path:
    for candidate in NARRATION_CANDIDATES:
        path = project / candidate
        if path.is_file() and path.stat().st_size > 0:
            return path
    return project / NARRATION_CANDIDATES[0]


def check_project(project: Path, ffprobe: str, tolerance: float, reels_max_seconds: float = REELS_MAX_SECONDS) -> bool:
    full = project / FULL_RENDER
    reels = project / REELS_RENDER
    narration = narration_path(project)

    narration_seconds = duration(narration, ffprobe)
    full_seconds = duration(full, ffprobe)
    reels_seconds = duration(reels, ffprobe)

    print(f"=== {project.name} ===")
    print(f"  narration={narration_seconds}  full_render={full_seconds}  reels_render={reels_seconds}")
    print(f"  full_video={stream_info(full, ffprobe, 'v:0')}  full_audio={stream_info(full, ffprobe, 'a:0')}")

    passed = True
    for label, path in (("narration", narration), ("full render", full), ("reels render", reels)):
        if not path.is_file() or path.stat().st_size == 0:
            print(f"  MISSING_FILE {label}: {path}  FAIL")
            passed = False

    if narration_seconds is None or full_seconds is None:
        print("  narration_render_gap=CANNOT_COMPUTE  FAIL")
        return False

    gap = abs(narration_seconds - full_seconds)
    ok = gap <= tolerance
    print(f"  narration_render_gap={gap:.3f}s  {'PASS' if ok else 'FAIL'} (tolerance={tolerance})")
    passed = passed and ok

    if reels_seconds is None:
        print(f"  reels_duration=CANNOT_COMPUTE  FAIL")
        passed = False
    else:
        reels_ok = reels_seconds <= reels_max_seconds
        print(f"  reels_duration={reels_seconds:.3f}s  {'PASS' if reels_ok else 'FAIL'} (max={reels_max_seconds:.0f}s)")
        passed = passed and reels_ok

    return passed


def resolve_projects(args: argparse.Namespace) -> list[Path]:
    if args.projects:
        return [Path(item) for item in args.projects]
    root = Path(args.projects_root)
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", nargs="*", help="Project directories to check")
    parser.add_argument("--projects-root", default="projects",
                        help="Scan every subdirectory of this root when no projects are given")
    parser.add_argument("--ffprobe", default=None)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--reels-max-duration", type=float, default=REELS_MAX_SECONDS)
    args = parser.parse_args()

    ffprobe = args.ffprobe or shutil.which("ffprobe")
    if not ffprobe:
        print("GATE2=FAIL (ffprobe not found)")
        return 1

    projects = resolve_projects(args)
    if not projects:
        print("GATE2=FAIL (no projects to check)")
        return 1

    all_pass = all(check_project(project, ffprobe, args.tolerance, args.reels_max_duration) for project in projects)
    print(f"\nGATE2={'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())