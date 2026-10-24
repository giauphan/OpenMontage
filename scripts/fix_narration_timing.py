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
import time
from pathlib import Path
from typing import Any

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

def load_script_text(project: Path, script_name: str = "script_vi.json") -> str:
    script_path = project / "artifacts" / script_name
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

def synth(voice, text, out: Path, rate: str | None = None, locale: str = "en-US", provider: str | None = None):
    if not voice:
        return 1, "--voice: voice identifier is required"
    clean_text = prepare_narration(text) if locale.startswith("vi") else text

    # If explicit edge provider or standard Neural voice without explicit non-edge provider,
    # invoke edge-tts directly via subprocess for backward compatibility.
    is_edge_voice = (provider == "edge") or (not provider and ("Neural" in str(voice) or str(voice).startswith("en-US-") or str(voice).startswith("vi-VN-")))
    if is_edge_voice:
        args = ["edge-tts", "--voice", voice, "--text", clean_text, "--write-media", str(out)]
        if rate:
            args += ["--rate", rate]
        r = subprocess.run(args, capture_output=True, text=True)
        return r.returncode, (r.stderr or "")[-400:]

    # For other tech voices (Kokoro, Pocket, OmniRoute, etc.), use NarrationOrchestrator
    try:
        from lib.audio.narration_orchestrator import NarrationOrchestrator
        orchestrator = NarrationOrchestrator()
        actual_provider = provider
        if not actual_provider:
            v_lower = str(voice).lower()
            if v_lower.startswith("am_") or v_lower.startswith("af_") or "kokoro" in v_lower:
                actual_provider = "kokoro"
            elif "alba" in v_lower or "pocket" in v_lower:
                actual_provider = "pocket18"
            elif "rachel" in v_lower or "omniroute" in v_lower:
                actual_provider = "omniroute"
            else:
                actual_provider = "edge"

        speed = 1.0
        if rate:
            clean_rate = str(rate).replace("%", "").strip()
            if clean_rate.startswith("+"):
                speed = 1.0 + float(clean_rate[1:]) / 100.0
            elif clean_rate.startswith("-"):
                speed = 1.0 - float(clean_rate[1:]) / 100.0
            else:
                speed = 1.0 + float(clean_rate) / 100.0

        settings = {"rate": rate, "speed": speed}
        res = orchestrator.synthesize(
            text=text,
            output_path=out,
            locale=locale,
            provider=actual_provider,
            voice=voice,
            settings=settings,
        )
        if res.get("success"):
            return 0, ""
        return 1, res.get("error", "Narration synthesis failed")
    except Exception as exc:
        return 1, str(exc)


TECH_VOICE_CANDIDATES = [
    {"provider": "edge", "voice": "en-US-ChristopherNeural", "label": "Edge-TTS (Christopher - Tech Broadcast)"},
    {"provider": "kokoro", "voice": "am_michael", "label": "Kokoro-82M (am_michael - Clear Tech Voice, Local CPU)"},
    {"provider": "pocket18", "voice": "alba", "label": "Pocket TTS 18M (alba - Modern Tech Explainer, Tiny CPU)"},
    {"provider": "omniroute", "voice": "rachel", "label": "OmniRoute (rachel - Expressive AI Tech Voice)"},
]


def try_tech_voices_fit(
    project: Path,
    text: str,
    target: float,
    tolerance: float,
    locale: str = "en-US",
    candidates: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Try through tech voice candidates to find the best fit for project duration and server resources."""
    import time
    candidates = candidates or TECH_VOICE_CANDIDATES
    results = []
    tmp_out = project / "assets" / "tmp_tech_voice_fit.mp3"
    tmp_out.parent.mkdir(parents=True, exist_ok=True)

    rates = [None, "+5%", "-5%", "+10%", "-10%", "+15%", "-15%", "+20%", "+25%", "+30%"]

    for cand in candidates:
        provider = cand["provider"]
        voice = cand["voice"]
        label = cand.get("label", f"{provider}:{voice}")
        best_cand_fit = None

        for rate in rates:
            t0 = time.time()
            rc, err = synth(voice, text, tmp_out, rate, locale=locale, provider=provider)
            elapsed = time.time() - t0
            if rc != 0:
                continue
            dur = probe_duration(tmp_out)
            if dur <= 0:
                continue
            delta = abs(dur - target)
            rtf = elapsed / dur if dur > 0 else 999.0
            fit_entry = {
                "provider": provider,
                "voice": voice,
                "label": label,
                "rate": rate,
                "duration": dur,
                "target": target,
                "delta": delta,
                "within_tolerance": delta <= tolerance,
                "elapsed_seconds": round(elapsed, 3),
                "rtf": round(rtf, 4),
            }
            if best_cand_fit is None or delta < best_cand_fit["delta"]:
                best_cand_fit = fit_entry
            if delta <= tolerance:
                # Found a rate that fits project perfectly
                break

        if best_cand_fit:
            results.append(best_cand_fit)

    if tmp_out.exists():
        tmp_out.unlink()

    # Sort results by within_tolerance DESC, then delta ASC, then RTF ASC (server efficiency)
    results.sort(key=lambda r: (not r["within_tolerance"], r["delta"], r["rtf"]))
    return {
        "best_fit": results[0] if results else None,
        "all_evaluations": results,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--target", type=float, default=None)
    ap.add_argument("--tolerance", type=float, default=3.0)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--provider", default=None, help="TTS provider override (kokoro, pocket18, omniroute, edge, elevenlabs)")
    ap.add_argument("--try-tech-voices", action="store_true", help="Try candidate tech voices to find the best fit for project duration and server resources")
    ap.add_argument("--max-rate", default="+40%")
    ap.add_argument(
        "--reels-only",
        action="store_true",
        help="Use artifacts/script_vi_reels.json and update only reels assets/render",
    )
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if args.target is None:
        # Infer target duration from existing composition root data-duration or narration
        target_val = 70.0
        comp_dir = project / ("hyperframes_reels" if args.reels_only else "hyperframes")
        index_file = comp_dir / "index.html"
        if index_file.is_file():
            try:
                matches = re.findall(r"data-duration=[^\d]*([0-9.]+)", index_file.read_text(encoding="utf-8"))
                if matches:
                    target_val = float(matches[0])
            except Exception:
                pass
        args.target = target_val
    if not project.is_dir():
        raise SystemExit(f"ERROR: {project} is not a directory")

    from lib.artifact_paths import resolve_project_locale, is_english_locale, resolve_render_paths
    locale = resolve_project_locale(project)
    voice = args.voice
    if not voice:
        voice = "en-US-ChristopherNeural" if is_english_locale(locale) else "vi-VN-HoaiMyNeural"

    if is_english_locale(locale):
        script_name = "script_en_US.json"
    else:
        script_name = "script_vi_reels.json" if args.reels_only else "script_vi.json"
    text = load_script_text(project, script_name)
    warn(f"narration text derived: {len(text)} chars, {len(text.split())} words")
    contam = find_contamination(text)
    if contam:
        warn("REJECTING narration text — contamination markers found: " + ", ".join(sorted(set(contam))))
        warn("Text head: " + text[:200])
        raise SystemExit("ERROR: narration text is contaminated; refusing to synthesize")

    narration_name = "narration_reels.mp3" if args.reels_only else "narration.mp3"
    narration = project / "assets" / narration_name
    tmp = project / "assets" / f"{narration_name}.synth.mp3"

    chosen = None
    if args.try_tech_voices and is_english_locale(locale):
        warn(f"Evaluating candidate tech voices to fit project target {args.target:.1f}s (tolerance {args.tolerance:.1f}s)...")
        fit_eval = try_tech_voices_fit(project, text, args.target, args.tolerance, locale=locale)
        best = fit_eval.get("best_fit")
        if best:
            warn(f"Best tech voice fit: {best['label']} rate={best['rate'] or 'natural'} -> dur={best['duration']:.2f}s (delta={best['delta']:.2f}s, rtf={best['rtf']:.3f})")
            voice = best["voice"]
            args.provider = best["provider"]
            rc, err = synth(voice, text, tmp, best["rate"], locale=locale, provider=args.provider)
            if rc == 0:
                chosen = (best["rate"], best["duration"])

    if chosen is None:
        # Try increasing or decreasing speed until it fits, starting at natural.
        rates = [None] + [f"-{p}%" for p in range(5, 26, 5)] + [f"+{p}%" for p in range(5, 41, 5)]
        for rate in rates:
            warn(f"synth rate={rate or 'natural'}")
            rc, err = synth(voice, text, tmp, rate, locale=locale, provider=args.provider)
            if rc != 0:
                warn(f"synth error ({args.provider or 'default'}): " + err)
                continue
            dur = probe_duration(tmp)
            warn(f"  duration={dur:.3f}s target={args.target:.1f}s tolerance={args.tolerance:.1f}s")
            if dur > 0 and abs(dur - args.target) <= args.tolerance:
                chosen = (rate, dur)
                break
    if chosen is None:
        # Keep the closest natural reading and record the gap; do not fail silently.
        warn("no rate fit within tolerance; using closest natural and letting QA decide")
        rc, err = synth(voice, text, tmp, None, locale=locale, provider=args.provider)
        if rc != 0:
            raise SystemExit("ERROR: baseline synth failed: " + err)
        dur = probe_duration(tmp)
        if dur <= 0:
            raise SystemExit("ERROR: cannot probe synthesized narration")
        chosen = (None, dur)

    rate, dur = chosen
    warn(f"chosen narration: rate={rate or 'natural'} duration={dur:.3f}s")
    shutil.move(tmp, narration)

    if args.reels_only:
        d = project / "hyperframes_reels" / "assets"
        if d.is_dir():
            shutil.copy2(narration, d / "narration.mp3")
            shutil.copy2(narration, d / "narration_reels.mp3")
            warn("copied narration -> hyperframes_reels/assets/narration.mp3 and narration_reels.mp3")
    else:
        for comp in ("hyperframes", "hyperframes_reels"):
            d = project / comp / "assets"
            if d.is_dir():
                shutil.copy2(narration, d / "narration.mp3")
                shutil.copy2(narration, d / "narration_reels.mp3")
                warn(f"copied narration -> {comp}/assets/narration.mp3 and narration_reels.mp3")
        root_assets = project / "assets"
        if root_assets.is_dir():
            if narration != root_assets / "narration.mp3":
                shutil.copy2(narration, root_assets / "narration.mp3")
            if narration != root_assets / "narration_reels.mp3":
                shutil.copy2(narration, root_assets / "narration_reels.mp3")

    # Sync composition data-duration with chosen narration duration so render matches audio
    for comp in (("hyperframes_reels",) if args.reels_only else ("hyperframes", "hyperframes_reels")):
        comp_index = project / comp / "index.html"
        if comp_index.is_file():
            html_text = comp_index.read_text(encoding="utf-8")
            html_text = re.sub(r'data-duration="[^"]+"', f'data-duration="{dur:.3f}"', html_text)
            html_text = re.sub(r"const\s+dur\s*=\s*[0-9.]+;", f"const dur = {dur:.3f};", html_text)
            comp_index.write_text(html_text, encoding="utf-8")
            warn(f"synced {comp}/index.html data-duration to {dur:.3f}s")

    # Repair quality (fonts + audio src bindings). This gate is mandatory:
    # skipping it silently was how landscape/missing-font compositions reached
    # the renderer.
    repair_script = ROOT / "scripts" / "repair_hyperframes_quality.py"
    if not repair_script.is_file():
        raise SystemExit(f"ERROR: repair script not found at {repair_script}")
    repair_command = [sys.executable, str(repair_script), str(project)]
    if args.reels_only:
        repair_command += ["--composition", "hyperframes_reels"]
    r = subprocess.run(repair_command, capture_output=True, text=True)
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

    if is_english_locale(locale):
        full_path, reels_path = resolve_render_paths(project, locale=locale)
        full_name, reels_name = full_path.name, reels_path.name
    else:
        full_name, reels_name = "final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"

    if args.reels_only:
        render("hyperframes_reels", reels_name)
    else:
        render("hyperframes", full_name)
        render("hyperframes_reels", reels_name)

    qa_command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_render_quality.py"),
        str(project),
        "--no-auto-repair",
    ]
    if args.reels_only:
        qa_command += ["--render", "reels", "--min-duration", "0", "--reels-max-duration", "60"]
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