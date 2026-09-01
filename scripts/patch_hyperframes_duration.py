#!/usr/bin/env python3
"""Patch HyperFrames HTML composition duration to match narration audio."""
import json
import re
import subprocess
import sys
from pathlib import Path

FFPROBE = "/home/ubuntu/.local/share/uv/python/cpython-3.12.13-linux-aarch64-gnu/lib/python3.12/site-packages/static_ffmpeg/bin/linux_arm64/ffprobe"

def main():
    root = Path(__file__).resolve().parents[1]
    projects = root / "projects"

    if len(sys.argv) < 2:
        project_ids = [p.name for p in projects.iterdir() if p.is_dir() and p.name.startswith("cand_")]
    else:
        project_ids = sys.argv[1:]

    for pid in project_ids:
        proj = projects / pid
        for comp in ["hyperframes", "hyperframes_reels"]:
            html_path = proj / comp / "index.html"
            if not html_path.is_file():
                continue

            # Find narration file
            narration = proj / comp / "assets" / "narration.mp3"
            if not narration.is_file():
                narration = proj / "assets" / "narration.mp3"
            if not narration.is_file():
                print(f"SKIP {html_path}: no narration found")
                continue

            # Probe duration
            result = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(narration)],
                capture_output=True, text=True
            )
            duration = 60.0
            if result.returncode == 0:
                try:
                    duration = float(json.loads(result.stdout)["format"]["duration"])
                except (KeyError, json.JSONDecodeError):
                    pass

            # Patch HTML
            text = html_path.read_text(encoding="utf-8")
            text = re.sub(r'data-duration="[^"]+"', f'data-duration="{duration:.3f}"', text)
            text = re.sub(r'const totalDuration = \d+(?:\.\d+)?', f'const totalDuration = {duration:.3f}', text)
            html_path.write_text(text, encoding="utf-8")
            print(f"Patched {html_path} to duration={duration:.3f}s")

    print("Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
