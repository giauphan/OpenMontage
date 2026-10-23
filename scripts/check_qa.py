#!/usr/bin/env python3
"""Gate 2: QA check for render-ready projects.

Takes project directories (or a projects root) as arguments instead of
hardcoding container paths and candidate IDs, so same gate runs on a developer
checkout, in CI, and on publish host.

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

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

FULL_RENDER = "renders/final_full_vi_9x16.mp4"
REELS_RENDER = "renders/final_reels_vi_9x16.mp4"
NARRATION_CANDIDATES = ("assets/narration.mp3", "assets/voice/narration.mp3")
NARRATION_TEXT = "artifacts/narration_vi_text.txt"
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
    try:
        return float(lines[-1])
    except (IndexError, ValueError):
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


def check_project(project: Path, ffprobe: str, tolerance: float) -> bool:
    import json
    from lib.artifact_paths import resolve_project_locale, is_english_locale, resolve_render_paths, resolve_narration_text_path
    locale = resolve_project_locale(project)
    is_en = is_english_locale(locale)
    if is_en:
        full, reels = resolve_render_paths(project, locale=locale)
        narration_text = resolve_narration_text_path(project, locale=locale)
    else:
        full = project / FULL_RENDER
        reels = project / REELS_RENDER
        narration_text = project / NARRATION_TEXT
    narration = narration_path(project)

    # Determine project format
    format_type = None
    meta_path = project / "publish_metadata.json"
    if meta_path.is_file():
        try:
            format_type = json.loads(meta_path.read_text(encoding="utf-8")).get("format")
        except Exception:
            pass
    if not format_type:
        proj_path = project / "project.json"
        if proj_path.is_file():
            try:
                format_type = json.loads(proj_path.read_text(encoding="utf-8")).get("format")
            except Exception:
                pass

    narration_seconds = duration(narration, ffprobe)
    full_seconds = duration(full, ffprobe)
    reels_seconds = duration(reels, ffprobe)

    print(f"=== {project.name} ===")
    print(f"  narration={narration_seconds}  full_render={full_seconds}  reels_render={reels_seconds}")
    print(f"  full_video={stream_info(full, ffprobe, 'v:0')}  full_audio={stream_info(full, ffprobe, 'a:0')}")

    passed = True
    reels_max = 180.0 if is_en else REELS_MAX_SECONDS

    is_short_only = format_type in ("short", "shorts", "reels", "9x16") or (is_en and reels.is_file() and not full.is_file())
    is_long_only = format_type in ("long", "longform", "16x9", "full") or (is_en and full.is_file() and not reels.is_file())

    if is_short_only:
        if not narration.is_file() or narration.stat().st_size == 0:
            print(f"  MISSING_FILE narration: {narration}  FAIL")
            passed = False
        if not reels.is_file() or reels.stat().st_size == 0:
            print(f"  MISSING_FILE reels render: {reels}  FAIL")
            passed = False
        if narration.is_file() and narration_text.is_file():
            narration_fresh = narration.stat().st_mtime_ns >= (narration_text.stat().st_mtime_ns - 1_000_000_000)
            print(f"  narration_stale  {'PASS' if narration_fresh else 'FAIL'}")
            passed = passed and narration_fresh
        else:
            print("  narration_stale=SKIP (source text unavailable)")

        if narration_seconds is None or reels_seconds is None:
            print("  narration_render_gap=CANNOT_COMPUTE  FAIL")
            passed = False
        else:
            gap = abs(narration_seconds - reels_seconds)
            gap_ok = gap <= tolerance
            print(f"  narration_render_gap={gap:.3f}s  {'PASS' if gap_ok else 'FAIL'} (tolerance={tolerance})")
            passed = passed and gap_ok

        if reels_seconds is None:
            print("  reels_duration=CANNOT_COMPUTE  FAIL")
            return False
        reels_ok = reels_seconds <= reels_max
        print(f"  reels_duration={reels_seconds:.3f}s  {'PASS' if reels_ok else 'FAIL'} (max={reels_max:.0f}s)")
        return passed and reels_ok

    elif is_long_only:
        if not narration.is_file() or narration.stat().st_size == 0:
            print(f"  MISSING_FILE narration: {narration}  FAIL")
            passed = False
        if not full.is_file() or full.stat().st_size == 0:
            print(f"  MISSING_FILE full render: {full}  FAIL")
            passed = False
        if narration.is_file() and narration_text.is_file():
            narration_fresh = narration.stat().st_mtime_ns >= (narration_text.stat().st_mtime_ns - 1_000_000_000)
            print(f"  narration_stale  {'PASS' if narration_fresh else 'FAIL'}")
            passed = passed and narration_fresh
        else:
            print("  narration_stale=SKIP (source text unavailable)")

        if narration_seconds is None or full_seconds is None:
            print("  narration_render_gap=CANNOT_COMPUTE  FAIL")
            passed = False
        else:
            gap = abs(narration_seconds - full_seconds)
            gap_ok = gap <= tolerance
            print(f"  narration_render_gap={gap:.3f}s  {'PASS' if gap_ok else 'FAIL'} (tolerance={tolerance})")
            passed = passed and gap_ok

        if full_seconds is None:
            print("  full_duration=CANNOT_COMPUTE  FAIL")
            return False
        full_ok = full_seconds >= 60.0
        print(f"  full_duration={full_seconds:.3f}s  {'PASS' if full_ok else 'FAIL'} (min=60s)")
        return passed and full_ok

    else:
        for label, path in (("narration", narration), ("full render", full), ("reels render", reels)):
            if not path.is_file() or path.stat().st_size == 0:
                print(f"  MISSING_FILE {label}: {path}  FAIL")
                passed = False

        if narration.is_file() and narration_text.is_file():
            narration_fresh = narration.stat().st_mtime_ns >= (narration_text.stat().st_mtime_ns - 1_000_000_000)
            print(f"  narration_stale  {'PASS' if narration_fresh else 'FAIL'}")
            passed = passed and narration_fresh
        else:
            print("  narration_stale=SKIP (source text unavailable)")

        if narration_seconds is None or full_seconds is None:
            print("  narration_render_gap=CANNOT_COMPUTE  FAIL")
            passed = False
        else:
            gap = abs(narration_seconds - full_seconds)
            gap_ok = gap <= tolerance
            print(f"  narration_render_gap={gap:.3f}s  {'PASS' if gap_ok else 'FAIL'} (tolerance={tolerance})")
            passed = passed and gap_ok

        if reels_seconds is None:
            print("  reels_duration=CANNOT_COMPUTE  FAIL")
            return False
        reels_ok = reels_seconds <= reels_max
        print(f"  reels_duration={reels_seconds:.3f}s  {'PASS' if reels_ok else 'FAIL'} (max={reels_max:.0f}s)")
        return passed and reels_ok


def resolve_projects(args: argparse.Namespace) -> list[Path]:
    if args.projects:
        return [Path(item) for item in args.projects]
    root = Path(args.projects_root)
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", nargs="*", help="Project directories to check")
    parser.add_argument("--projects-root", default="projects", help="Scan subdirectories when no projects are given")
    parser.add_argument("--ffprobe", default=None)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args()

    ffprobe = args.ffprobe or shutil.which("ffprobe")
    if not ffprobe:
        print("GATE2=FAIL (ffprobe not found)")
        return 1
    projects = resolve_projects(args)
    if not projects:
        print("GATE2=FAIL (no projects to check)")
        return 1

    all_pass = all(check_project(project, ffprobe, args.tolerance) for project in projects)
    print(f"\nGATE2={'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
