"""Repair GSAP timeline syntax and guarantee continuous camera drift across all scenes.

Director-generated HyperFrames HTML compositions can fail render quality validation
if the visual canvas is static for >= 2.0s (ffmpeg freezedetect), triggering the
frozen canvas threshold (>95% static frames). This module ensures:
1. Malformed tl.to(target, {vars1}, {vars2}, pos) calls are merged into valid GSAP syntax.
2. Every scene container (#scene-1..N) is guaranteed continuous micro-motion
   (scale: 1.0 -> 1.035, y: 0 -> -8px) across its full section duration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _fix_tl_to_signature(match: re.Match) -> str:
    target = match.group(1)
    vars1 = match.group(2).strip()
    vars2 = match.group(3).strip()
    pos_arg = match.group(4)
    pos = f", {pos_arg.strip()}" if pos_arg else ""
    # Strip scale: 1.035 from entrance tween so it doesn't conflict with full-scene drift
    combined = vars1.rstrip(" }") + ", " + vars2.lstrip(" {")
    combined = re.sub(r"(?:,\s*)?\bscale\s*:\s*1\.035\b", "", combined)
    combined = re.sub(r"(?:,\s*)?\by\s*:\s*-8\b", "", combined)
    combined = re.sub(r"^\s*,\s*", "", combined)
    return f"tl.to({target}, {{{combined}}}{pos})"


def _resolve_scene_timings(
    scene_ids: list[str],
    script_body: str,
    path: Path,
    narration_duration: float,
) -> list[tuple[float, float]]:
    timings: list[tuple[float, float]] = []
    artifacts_dir = path.parent.parent / "artifacts"
    if artifacts_dir.is_dir():
        for script_file in sorted(artifacts_dir.glob("script*.json")):
            try:
                data = json.loads(script_file.read_text(encoding="utf-8"))
                sections = data.get("sections", [])
                if sections:
                    for sec in sections:
                        s = float(sec.get("start_seconds", 0.0))
                        e = float(sec.get("end_seconds", 0.0))
                        timings.append((s, max(e - s, 1.0)))
                    break
            except Exception:
                pass

    if len(timings) < len(scene_ids):
        comment_timings = re.findall(r"//\s*Scene\s*\d+:\s*([0-9.]+)-([0-9.]+)s", script_body)
        if len(comment_timings) >= len(scene_ids):
            timings = [(float(s), max(float(e) - float(s), 1.0)) for s, e in comment_timings[:len(scene_ids)]]
        elif narration_duration > 0:
            step = narration_duration / max(len(scene_ids), 1)
            timings = [(i * step, step) for i in range(len(scene_ids))]
        else:
            timings = [(i * 10.0, 10.0) for i in range(len(scene_ids))]

    return timings


def repair_gsap_timeline(html: str, path: Path, narration_duration: float = 0.0) -> str:
    """Repair GSAP timeline syntax and guarantee continuous scene micro-motion."""
    def _patch_script_block(m: re.Match) -> str:
        open_tag = m.group(1)
        script_body = m.group(2)
        close_tag = m.group(3)
        if "src=" in open_tag.lower():
            return m.group(0)
        if "gsap" not in script_body and "__timelines" not in script_body and "tl" not in script_body:
            return m.group(0)

        # 1. Merge malformed tl.to(target, {vars1}, {vars2}, pos) calls
        pattern = r"tl\.to\s*\(\s*([\x27\x22][^\x27\x22]+[\x27\x22]|\w+)\s*,\s*\{([^{}]+)\}\s*,\s*\{([^{}]+)\}(?:,\s*((?:[^,()]|\([^()]*\))+))?\s*\)"
        script_body = re.sub(pattern, _fix_tl_to_signature, script_body)

        # 2. Identify scenes in the HTML
        scene_ids = re.findall(r"<[a-zA-Z0-9]+\b[^>]*\bid=[\x27\x22](scene-\d+)[\x27\x22][^>]*>", html)
        if not scene_ids:
            return f"{open_tag}{script_body}{close_tag}"

        timings = _resolve_scene_timings(scene_ids, script_body, path, narration_duration)

        # 3. Check for scenes lacking full-scene continuous motion
        injected_tweens: list[str] = []
        for i, s_id in enumerate(scene_ids):
            start_t, dur_t = timings[i] if i < len(timings) else (i * 10.0, 10.0)
            has_drift = re.search(rf"(?:fromTo|to)\s*\(\s*[\x27\x22]#{s_id}[\x27\x22][^)]*duration:\s*([3-9]|\d{{2,}})", script_body)
            has_generic_drift = re.search(r"scenes\.forEach[\s\S]*?fromTo\(scene", script_body)
            if not has_drift and not has_generic_drift:
                injected_tweens.append(
                    f"    tl.fromTo(\x27#{s_id}\x27, {{ scale: 1.0, y: 0 }}, {{ scale: 1.035, y: -8, duration: {dur_t:.3f}, ease: \x27none\x27 }}, {start_t:.3f});"
                )

        if injected_tweens:
            drift_code = "\n    // Injected continuous camera motion to ensure canvas is never static\n" + "\n".join(injected_tweens) + "\n"
            if re.search(r"window\.__timelines\s*\[\s*[\x27\x22]main[\x27\x22]\s*\]", script_body):
                script_body = re.sub(
                    r"(window\.__timelines\s*\[\s*[\x27\x22]main[\x27\x22]\s*\]\s*=)",
                    f"{drift_code}\n    \\1",
                    script_body,
                    count=1,
                )
            else:
                script_body = script_body.rstrip() + f"\n{drift_code}\n"

        return f"{open_tag}{script_body}{close_tag}"

    return re.sub(r"(<script\b[^>]*>)([\s\S]*?)(</script>)", _patch_script_block, html, flags=re.IGNORECASE)
