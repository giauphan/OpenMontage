#!/usr/bin/env python3
"""Copyright preflight CLI: inspect a rendered video before publishing.

Usage:
  python3 scripts/check_copyright.py <video_path> [--manifest path] [--platform meta]
  python3 scripts/check_copyright.py --project quantum-ai-chips-2026
"""
import argparse
import json
import sys
from pathlib import Path

from tools.publishers.copyright_preflight import CopyrightPreflight

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Copyright preflight for rendered videos")
    parser.add_argument("video_path", nargs="?", help="Path to video file")
    parser.add_argument("--project", help="Project name; checks all assets in publish_metadata.json")
    parser.add_argument("--manifest", help="Path to music_manifest.json")
    parser.add_argument("--platform", default="all", choices=["meta", "youtube", "tiktok", "all"])
    args = parser.parse_args()

    tool = CopyrightPreflight()
    targets = []

    if args.project:
        meta_path = ROOT / "projects" / args.project / "publish_metadata.json"
        if not meta_path.is_file():
            print(f"ERROR: {meta_path} not found")
            return 1
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for field in ("yt_shorts", "ig_reels", "fb_video"):
            if field in meta:
                targets.append((field, ROOT / meta[field]))
    elif args.video_path:
        targets.append(("video", Path(args.video_path)))
    else:
        parser.error("provide video_path or --project")

    exit_code = 0
    seen = set()
    for label, path in targets:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            print(f"[{label}] MISSING {path}")
            exit_code = 1
            continue
        inputs = {"video_path": str(path), "target_platform": args.platform}
        if args.manifest:
            inputs["music_manifest_path"] = args.manifest
        result = tool.execute(inputs)
        if not result.success:
            print(f"[{label}] ERROR {result.error}")
            exit_code = 1
            continue
        data = result.data
        flag = "PASS" if data["passed"] else "FAIL"
        print(f"[{label}] {flag} status={data['copyright_status']} streams={len(data['audio_streams'])}")
        print(f"    {data['recommendation']}")
        for w in data["warnings"]:
            print(f"    WARN: {w}")
        if not data["passed"]:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
