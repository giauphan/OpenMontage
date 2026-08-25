#!/usr/bin/env python3
"""Gate 2: QA check for render-ready candidates."""
import subprocess
from pathlib import Path

FP = "/usr/bin/ffprobe"
PROJ = ["cand_2782966506bbb63c", "cand_60b047b0a308b9cf", "cand_c160b3afda23a02e"]

def dur(path):
    if not path.exists():
        return "MISSING"
    r = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return (r.stdout.strip().splitlines() or ["?"])[-1]

def info(path, stream="v:0"):
    if not path.exists():
        return "MISSING"
    r = subprocess.run([FP, "-v", "error", "-select_streams", stream,
                       "-show_entries", "stream=codec_name,width,height",
                       "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return (r.stdout.strip() or "?")

all_pass = True
for pid in PROJ:
    p = Path(f"/app/projects/{pid}")
    r_full = p / "renders/final_full_vi_9x16.mp4"
    r_reels = p / "renders/final_reels_vi_9x16.mp4"
    narr = p / "assets/narration.mp3"

    nd = dur(narr)
    rd = dur(r_full)
    vd = dur(r_reels)

    vc = info(r_full, "v:0")
    ac = info(r_full, "a:0")
    sz = r_full.stat().st_size if r_full.exists() else 0

    print(f"=== {pid} ===")
    print(f"  narration={nd}s  full_render={rd}s  reels_render={vd}s")
    print(f"  full_video={vc}  full_audio={ac}  full_size={sz}")

    try:
        narr_f = float(nd)
        render_f = float(rd)
        diff = abs(narr_f - render_f)
        ok = diff <= 3.0
        print(f"  narration_render_gap={diff:.3f}s  {'PASS' if ok else 'FAIL'} (tolerance=3.0s)")
        if not ok:
            all_pass = False
    except (ValueError, TypeError):
        print(f"  narration_render_gap=CANNOT_COMPUTE  FAIL")
        all_pass = False

    if not all(s.exists() and s.stat().st_size > 0 for s in [r_full, r_reels, narr]):
        print(f"  MISSING_FILES  FAIL")
        all_pass = False

print(f"\nGATE2={'PASS' if all_pass else 'FAIL'}")
