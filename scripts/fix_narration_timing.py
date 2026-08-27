#!/usr/bin/env python3
"""Re-synthesize narration to fit the composition timeline, re-render, and QA.

Run this inside the worker container (has edge-tts + hyperframes):
  cd /app/projects/<id>
  python3 <this-script> --target 70.0 --tolerance 3.0

Steps:
  1. Build narration text from script_vi.json sections (text_vi) — the trusted
     source that the Compose director wrote. Reject if contaminated.
  2. Synthesize with edge-tts, sweeping --rate until duration lands within
     tolerance of the composition target (default 70s).
  3. Refresh narration into assets + both compositions, re-run the quality
     repair, re-render both MP4s, run validate_render_quality.py.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.narration_text import prepare_narration

CONTAMINATION = [
    "raining", "rainy", "sunny weather", "shopping list", "breakfast",
    "bananas", "oranges", "the store", "gym", "TypeScript", "PostgreSQL",
    "a different approach", "english lesson", "new lession", "good morning",
    "low-fat milk", "chicken breast", "go to the gym", "read a book",
    "play games", "more shopping", "different delimiter", "before going to the store",
]

def warn(msg):
    print(f"[fix_narration] {msg}")

def load_script_text(project: Path) -> str:
    script_path = project / "artifacts" / "script_vi.json"
    data = json.loads(script_path.read_text(encoding="utf-8"))
    parts = []
    sections = data.get("sections") if isinstance(data, dict) else None
    if sections:
        for s in sections:
            t = s.get("text_vi") or s.get("text") or ""
            if t:
                parts.append(t)
    if not parts:
        script = data.get("script", "") if isinstance(data, dict) else ""
        if script:
            parts.append(script)
    text = " ".join(p.strip() for p in parts if p.strip())
    text = re.sub(r"[*\n\r\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise SystemExit("ERROR: no narration text could be derived from script_vi.json")
    return text

def find_contamination(text: str):
    low = text.lower()
    hits = [c for c in CONTAMINATION if c.lower() in low]
    return hits

def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip().splitlines()[-1])
    except Exception:
        return -1.0


def hyperframes_command() -> list[str]:
    """Resolve the HyperFrames CLI without assuming a container layout."""
    cli = shutil.which("hyperframes")
    if cli:
        return [cli]
    for candidate in (
        ROOT / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs",
        Path("/app/node_modules/hyperframes/bin/hyperframes.mjs"),
    ):
        if candidate.is_file():
            return ["node", str(candidate)]
    raise SystemExit("ERROR: hyperframes CLI not found (install it or add it to PATH)")

def synth(voice, text, out: Path, rate: str):
    args = ["edge-tts", "--voice", voice, "--text", prepare_narration(text), "--write-media", str(out)]
    if rate:
        args += ["--rate", rate]
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, (r.stderr or "")[-400:]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--target", type=float, default=70.0)
    ap.add_argument("--tolerance", type=float, default=3.0)
    ap.add_argument("--voice", default="vi-VN-HoaiMyNeural")
    ap.add_argument("--max-rate", default="+40%")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        raise SystemExit(f"ERROR: {project} is not a directory")

    text = load_script_text(project)
    warn(f"narration text derived: {len(text)} chars, {len(text.split())} words")
    contam = find_contamination(text)
    if contam:
        warn("REJECTING narration text — contamination markers found: " + ", ".join(sorted(set(contam))))
        warn("Text head: " + text[:200])
        raise SystemExit("ERROR: narration text is contaminated; refusing to synthesize")

    narration = project / "assets" / "narration.mp3"
    tmp = project / "assets" / "narration.synth.mp3"

    # Try increasing speed until it fits, starting at 0 (natural).
    rates = [None] + [f"+{p}%" for p in range(5, 41, 5)]
    chosen = None
    for rate in rates:
        warn(f"synth rate={rate or 'natural'}")
        rc, err = synth(args.voice, text, tmp, rate)
        if rc != 0:
            warn("edge-tts error: " + err)
            continue
        dur = probe_duration(tmp)
        warn(f"  duration={dur:.3f}s target={args.target:.1f}s tolerance={args.tolerance:.1f}s")
        if dur > 0 and abs(dur - args.target) <= args.tolerance:
            chosen = (rate, dur)
            break
    if chosen is None:
        # Keep the closest natural reading and record the gap; do not fail silently.
        warn("no rate fit within tolerance; using closest natural and letting QA decide")
        rc, err = synth(args.voice, text, tmp, None)
        if rc != 0:
            raise SystemExit("ERROR: baseline synth failed: " + err)
        dur = probe_duration(tmp)
        if dur <= 0:
            raise SystemExit("ERROR: cannot probe synthesized narration")
        chosen = (None, dur)

    rate, dur = chosen
    warn(f"chosen narration: rate={rate or 'natural'} duration={dur:.3f}s")
    shutil.move(tmp, narration)

    # Refresh in both composition asset dirs.
    for comp in ("hyperframes", "hyperframes_reels"):
        d = project / comp / "assets"
        if d.is_dir():
            shutil.copy2(narration, d / "narration.mp3")
            warn(f"copied narration -> {comp}/assets/narration.mp3")

    # Repair quality (fonts + audio src bindings). This gate is mandatory:
    # skipping it silently was how landscape/missing-font compositions reached
    # the renderer.
    repair_script = ROOT / "scripts" / "repair_hyperframes_quality.py"
    if not repair_script.is_file():
        raise SystemExit(f"ERROR: repair script not found at {repair_script}")
    r = subprocess.run([sys.executable, str(repair_script), str(project)],
                       capture_output=True, text=True)
    warn("repair exit=" + str(r.returncode))
    if r.returncode != 0:
        warn(r.stdout[-500:])
        warn(r.stderr[-500:])
        raise SystemExit("ERROR: repair_hyperframes_quality failed")

    renders = project / "renders"
    renders.mkdir(exist_ok=True)

    def render(comp, out_name):
        comp_dir = project / comp
        out = renders / out_name
        out.unlink(missing_ok=True)
        r = subprocess.run(
            hyperframes_command() + ["render", str(comp_dir), "--output", str(out)],
            capture_output=True, text=True)
        warn(f"render {comp}: exit={r.returncode} exists={out.exists()} size={out.stat().st_size if out.exists() else 0}")
        if r.returncode != 0:
            warn("render stdout tail: " + (r.stdout or "")[-400:])
            warn("render stderr tail: " + (r.stderr or "")[-400:])
            raise SystemExit(f"ERROR: render failed for {comp}")

    render("hyperframes", "final_full_vi_9x16.mp4")
    render("hyperframes_reels", "final_reels_vi_9x16.mp4")

    qa_command = [sys.executable, str(ROOT / "scripts" / "validate_render_quality.py"), str(project)]
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        qa_command += ["--ffprobe", ffprobe]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        qa_command += ["--ffmpeg", ffmpeg]
    qa = subprocess.run(qa_command, capture_output=True, text=True)
    warn("QA exit=" + str(qa.returncode))
    warn((qa.stdout or "")[-1200:])
    warn((qa.stderr or "")[-400:])
    print("FINAL_QA_EXIT=" + str(qa.returncode))
    if qa.returncode != 0:
        raise SystemExit("ERROR: render quality gate failed")

    print("RESULT_OK narration_duration=%.3f" % dur)

if __name__ == "__main__":
    main()