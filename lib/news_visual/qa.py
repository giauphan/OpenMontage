"""Content-aware visual QA module for OpenMontage news videos.

Verifies:
1. Visual beat coverage against script sections.
2. Asset resolution and provenance integrity.
3. Overlay safe zone compliance (avoiding collisions with captions in bottom rail).
4. Unapproved claim prevention on evidence visuals.
5. Visual layout repetition and text-only fallback detection.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.news import template_provenance


def check_overlay_safe_zones(
    overlays_or_html: Any,
    variant: str = "reels",
    total_height: float = 1920.0,
) -> Tuple[bool, List[str]]:
    """Check whether overlays (source labels, badges) collide with the caption safe zone.
    
    In Reels 9:16 (1080x1920), bottom 16% (Y > 1612.8px or bottom < 16%) is reserved
    exclusively for captions and platform controls. Overlays in this area trigger collisions.
    """
    reasons: List[str] = []
    bottom_limit_pct = 16.0 if variant == "reels" else 12.0
    y_threshold = total_height * (1.0 - (bottom_limit_pct / 100.0))

    if isinstance(overlays_or_html, str):
        html = overlays_or_html
        # Scan for inline styles or CSS rules placing source labels or credits in bottom rail
        # Look for source-label, source-credit, credit-badge with bottom: X% or bottom: Xpx
        source_label_matches = re.finditer(
            r'class="[^"]*\b(source-label|source-credit|credit-overlay|evidence-badge)\b[^"]*"[^>]*style="([^"]*)"',
            html,
            re.IGNORECASE,
        )
        for m in source_label_matches:
            style = m.group(2)
            # Check bottom offset
            bot_match = re.search(r'bottom:\s*([0-9.]+)(%|px)', style)
            if bot_match:
                val = float(bot_match.group(1))
                unit = bot_match.group(2)
                if unit == "%" and val < bottom_limit_pct:
                    reasons.append(
                        f"{variant}: {m.group(1)} positioned at bottom: {val}% enters caption safe rail (<{bottom_limit_pct}%)"
                    )
                elif unit == "px" and val < (total_height * bottom_limit_pct / 100.0):
                    reasons.append(
                        f"{variant}: {m.group(1)} positioned at bottom: {val}px enters caption safe rail"
                    )
            top_match = re.search(r'top:\s*([0-9.]+)(%|px)', style)
            if top_match:
                val = float(top_match.group(1))
                unit = top_match.group(2)
                if unit == "%" and val > (100.0 - bottom_limit_pct):
                    reasons.append(
                        f"{variant}: {m.group(1)} positioned at top: {val}% enters caption safe rail"
                    )
                elif unit == "px" and val > y_threshold:
                    reasons.append(
                        f"{variant}: {m.group(1)} positioned at top: {val}px enters caption safe rail"
                    )

        # Check for CSS rule blocks like .source-label { bottom: ... }
        css_rules = re.finditer(
            r'\.(source-label|source-credit|credit-overlay|evidence-badge)\s*\{([^}]+)\}',
            html,
            re.IGNORECASE,
        )
        for m in css_rules:
            rule_body = m.group(2)
            bot_match = re.search(r'bottom:\s*([0-9.]+)(%|px)', rule_body)
            if bot_match:
                val = float(bot_match.group(1))
                unit = bot_match.group(2)
                if unit == "%" and val < bottom_limit_pct:
                    reasons.append(
                        f"{variant}: .{m.group(1)} CSS rule bottom: {val}% enters caption safe rail"
                    )
                elif unit == "px" and val < (total_height * bottom_limit_pct / 100.0):
                    reasons.append(
                        f"{variant}: .{m.group(1)} CSS rule bottom: {val}px enters caption safe rail"
                    )

    elif isinstance(overlays_or_html, list):
        for item in overlays_or_html:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id") or item.get("name") or "overlay"
            # Support multiple key naming conventions
            bot_pct = item.get("bottom_pct") or item.get("bottom_percent")
            top_pct = item.get("top_pct") or item.get("top_percent")
            y_pos = item.get("y") or item.get("top")

            if bot_pct is not None and float(bot_pct) < bottom_limit_pct:
                reasons.append(
                    f"{variant}: overlay '{item_id}' bottom_pct={bot_pct}% enters caption safe rail (<{bottom_limit_pct}%)"
                )
            elif top_pct is not None and float(top_pct) > (100.0 - bottom_limit_pct):
                reasons.append(
                    f"{variant}: overlay '{item_id}' top_pct={top_pct}% enters caption safe rail"
                )
            elif y_pos is not None and float(y_pos) > y_threshold:
                reasons.append(
                    f"{variant}: overlay '{item_id}' y={y_pos}px enters caption safe rail (> {y_threshold}px)"
                )

    return (len(reasons) == 0, reasons)


MAX_SCENE_HOLD_SECONDS = 12.0
MAX_SCENE_HOLD_TOLERANCE = 12.05


def _probe_video_duration(mp4_path: Path) -> float:
    try:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(res.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _sample_upper_frame_gray(mp4_path: Path, timestamp_s: float) -> Optional[bytes]:
    """Sample upper 80% of the video frame (excluding bottom 20% caption rail) at 160x160 gray."""
    try:
        res = subprocess.run(
            [
                "ffmpeg", "-v", "error",
                "-ss", f"{max(0.0, timestamp_s):.3f}",
                "-i", str(mp4_path),
                "-vf", "crop=iw:trunc(ih*0.80/2)*2:0:0,scale=160:160",
                "-frames:v", "1",
                "-f", "rawvideo",
                "-pix_fmt", "gray",
                "-",
            ],
            capture_output=True,
            check=True,
        )
        if len(res.stdout) == 160 * 160:
            return res.stdout
    except Exception:
        pass
    return None


def _frame_std_dev(gray_bytes: bytes) -> float:
    if not gray_bytes:
        return 0.0
    n = len(gray_bytes)
    mean = sum(gray_bytes) / n
    var = sum((b - mean) ** 2 for b in gray_bytes) / n
    return math.sqrt(var)


def _frame_mad(a: bytes, b: bytes) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _check_html_scene_hold_limits(
    html_text: str,
    variant_name: str,
    require_min_six_scenes: bool,
) -> List[str]:
    errors: List[str] = []
    stage_m = re.search(r'id=["\']stage["\'][^>]*data-duration=["\']([0-9.]+)["\']', html_text)
    if not stage_m:
        stage_m = re.search(r'data-composition-id=["\']main["\'][^>]*data-duration=["\']([0-9.]+)["\']', html_text)
    stage_dur = float(stage_m.group(1)) if stage_m else 0.0

    scene_tags = re.findall(r'<[a-zA-Z0-9]+\b[^>]*class=["\'][^"\']*\bscene\b[^"\']*["\'][^>]*>', html_text)
    scene_count = len(scene_tags)
    if require_min_six_scenes and scene_count < 6:
        errors.append(f"{variant_name}: HTML composition has {scene_count} scenes (< 6 minimum required)")

    starts_m = re.search(r'\bstarts\s*=\s*\[([0-9.,\s]+)\]', html_text)
    if starts_m:
        try:
            starts = [float(x.strip()) for x in starts_m.group(1).split(",") if x.strip()]
        except ValueError:
            starts = []
        if starts:
            if require_min_six_scenes and len(starts) < 6:
                errors.append(f"{variant_name}: HTML starts array has {len(starts)} entries (< 6 minimum required)")
            for i in range(len(starts) - 1):
                hold = starts[i + 1] - starts[i]
                if hold > MAX_SCENE_HOLD_TOLERANCE:
                    errors.append(
                        f"{variant_name}: HTML scene {i + 1} held for {hold:.2f}s (>{MAX_SCENE_HOLD_SECONDS:.1f}s max policy)"
                    )
            if stage_dur > starts[-1]:
                final_hold = stage_dur - starts[-1]
                if final_hold > MAX_SCENE_HOLD_TOLERANCE:
                    errors.append(
                        f"{variant_name}: final HTML scene held for {final_hold:.2f}s from {starts[-1]:.2f}s to {stage_dur:.2f}s (>{MAX_SCENE_HOLD_SECONDS:.1f}s max policy)"
                    )
    else:
        step_m = re.search(r'\b(?:index|idx|i)\s*\*\s*([0-9]+(?:\.[0-9]+)?)', html_text)
        if step_m:
            step_val = float(step_m.group(1))
            if step_val > MAX_SCENE_HOLD_TOLERANCE:
                errors.append(
                    f"{variant_name}: HTML scene step {step_val:.2f}s exceeds {MAX_SCENE_HOLD_SECONDS:.1f}s max policy"
                )
            if stage_dur > 0 and scene_count > 0:
                last_start = (scene_count - 1) * step_val
                final_hold = stage_dur - last_start
                if final_hold > MAX_SCENE_HOLD_TOLERANCE:
                    errors.append(
                        f"{variant_name}: final HTML scene held for {final_hold:.2f}s (from {last_start:.2f}s to {stage_dur:.2f}s, >{MAX_SCENE_HOLD_SECONDS:.1f}s max)"
                    )

    return errors


def _verify_scene_timeline_and_render_coverage(
    project_dir: Path,
    beats: List[Dict[str, Any]],
    bound_beat_indices: set[int],
    binding_pct: float,
    mode: str,
    findings: List[Dict[str, Any]],
    failure_categories: List[str],
) -> float:
    if not beats:
        return 100.0 if mode != "strict" else 0.0

    is_en_project = (project_dir / "artifacts" / "script_en_US.json").is_file()
    max_beat_end = max((float(b.get("end_seconds", 0.0)) for b in beats), default=0.0)
    require_min_six = is_en_project or max_beat_end >= 60.0

    def _add_visual_not_rendered(msg: str, beat_id: Optional[str] = None) -> None:
        item: Dict[str, Any] = {
            "severity": "blocker" if mode == "strict" else "warning",
            "category": "VISUAL_NOT_RENDERED",
            "message": msg,
        }
        if beat_id:
            item["beat_id"] = beat_id
        findings.append(item)
        if "VISUAL_NOT_RENDERED" not in failure_categories:
            failure_categories.append("VISUAL_NOT_RENDERED")

    if require_min_six and len(beats) < 6:
        _add_visual_not_rendered(
            f"Visual plan has {len(beats)} beats; at least 6 visual beats are required so no scene holds >12s across a 65-75s Short"
        )

    valid_timing_indices: set[int] = set()
    for idx, beat in enumerate(beats):
        bid = str(beat.get("id") or beat.get("beat_id") or f"beat-{idx + 1}")
        b_start = float(beat.get("start_seconds") if beat.get("start_seconds") is not None else beat.get("start_s", 0.0))
        b_end = float(beat.get("end_seconds") if beat.get("end_seconds") is not None else beat.get("end_s", 0.0))
        b_dur = b_end - b_start
        if b_dur <= 0.0:
            _add_visual_not_rendered(f"Beat '{bid}' has non-positive duration ({b_dur:.2f}s)", bid)
        elif b_dur > MAX_SCENE_HOLD_TOLERANCE:
            _add_visual_not_rendered(
                f"Beat '{bid}' duration {b_dur:.2f}s exceeds {MAX_SCENE_HOLD_SECONDS:.1f}s maximum hold policy",
                bid,
            )
        else:
            valid_timing_indices.add(idx)

    # Check HTML scene timeline hold durations
    for variant_name, html_p in (
        ("full", project_dir / "hyperframes" / "index.html"),
        ("reels", project_dir / "hyperframes_reels" / "index.html"),
    ):
        if html_p.is_file():
            try:
                html_text = html_p.read_text(encoding="utf-8")
                for err in _check_html_scene_hold_limits(html_text, variant_name, require_min_six):
                    _add_visual_not_rendered(err)
            except Exception:
                pass

    # Locate all rendered MP4s for post-render frame verification
    candidate_list = [
        project_dir / "renders" / "final_short_en_US_9x16.mp4",
        project_dir / "renders" / "final_reels_vi_9x16.mp4",
        project_dir / "renders" / "final_long_en_US_16x9.mp4",
        project_dir / "renders" / "final_full_vi_9x16.mp4",
    ]
    render_mp4s = [p for p in candidate_list if p.is_file() and p.stat().st_size > 0]
    if not render_mp4s and (project_dir / "renders").is_dir():
        render_mp4s = sorted(p for p in (project_dir / "renders").glob("*.mp4") if p.stat().st_size > 0)
    if not render_mp4s:
        for fallback_cand in (project_dir / "renders" / "final.mp4", project_dir / "final_render.mp4"):
            if fallback_cand.is_file() and fallback_cand.stat().st_size > 0:
                render_mp4s.append(fallback_cand)

    if not render_mp4s:
        if is_en_project:
            _add_visual_not_rendered(
                "Rendered MP4 missing; post-render visual beat verification cannot fall back to HTML binding"
            )
            return 0.0
        # Pre-render synthetic unit test fallback: require both HTML binding and valid <=12s beat duration
        verified_indices = bound_beat_indices & valid_timing_indices
        return round((len(verified_indices) / len(beats)) * 100.0, 1)

    min_render_pct = 100.0
    for render_mp4 in render_mp4s:
        video_dur = _probe_video_duration(render_mp4)
        if video_dur <= 0.0:
            _add_visual_not_rendered(f"Cannot probe positive duration from rendered video {render_mp4.name}")
            return 0.0

        # Check if the final beat holds for > 12s until the end of the rendered video
        last_beat = beats[-1]
        last_beat_start = float(last_beat.get("start_seconds") if last_beat.get("start_seconds") is not None else last_beat.get("start_s", 0.0))
        if video_dur - last_beat_start > MAX_SCENE_HOLD_TOLERANCE:
            _add_visual_not_rendered(
                f"Final visual beat '{last_beat.get('id') or last_beat.get('beat_id')}' holds for {video_dur - last_beat_start:.2f}s in {render_mp4.name} (from {last_beat_start:.2f}s to {video_dur:.2f}s, >{MAX_SCENE_HOLD_SECONDS:.1f}s max)",
                str(last_beat.get('id') or last_beat.get('beat_id') or ""),
            )

        visible_beats = 0
        prev_frame: Optional[bytes] = None
        for idx, beat in enumerate(beats):
            bid = str(beat.get("id") or beat.get("beat_id") or f"beat-{idx + 1}")
            b_start = float(beat.get("start_seconds") if beat.get("start_seconds") is not None else beat.get("start_s", 0.0))
            b_end = float(beat.get("end_seconds") if beat.get("end_seconds") is not None else beat.get("end_s", 0.0))
            if idx not in bound_beat_indices or idx not in valid_timing_indices:
                prev_frame = None
                continue
            if b_start >= video_dur:
                _add_visual_not_rendered(
                    f"Beat '{bid}' starts at {b_start:.2f}s beyond rendered video duration {video_dur:.2f}s in {render_mp4.name}",
                    bid,
                )
                prev_frame = None
                continue

            clamped_end = min(b_end, video_dur)
            mid_ts = min(max(0.1, (b_start + clamped_end) / 2.0), max(0.1, video_dur - 0.1))
            frame_bytes = _sample_upper_frame_gray(render_mp4, mid_ts)
            if frame_bytes is None:
                _add_visual_not_rendered(f"Failed to sample rendered frame for beat '{bid}' at {mid_ts:.2f}s in {render_mp4.name}", bid)
                prev_frame = None
                continue

            std_val = _frame_std_dev(frame_bytes)
            if std_val < 5.0:
                _add_visual_not_rendered(
                    f"Beat '{bid}' rendered frame at {mid_ts:.2f}s in {render_mp4.name} is visually blank or low-contrast (std_dev={std_val:.2f} < 5.0)",
                    bid,
                )
                prev_frame = frame_bytes
                continue

            if prev_frame is not None:
                mad_val = _frame_mad(frame_bytes, prev_frame)
                if mad_val < 0.25:
                    _add_visual_not_rendered(
                        f"Beat '{bid}' at {mid_ts:.2f}s shows no visual transition from previous beat in {render_mp4.name} (upper-frame MAD={mad_val:.3f} < 0.25)",
                        bid,
                    )
                    prev_frame = frame_bytes
                    continue

            visible_beats += 1
            prev_frame = frame_bytes

        render_pct = round((visible_beats / len(beats)) * 100.0, 1)
        if render_pct < 100.0:
            _add_visual_not_rendered(
                f"Rendered visual beat coverage is {render_pct:.1f}% ({visible_beats}/{len(beats)} beats verified in {render_mp4.name})"
            )
        if render_pct < min_render_pct:
            min_render_pct = render_pct

    return min_render_pct


def run_news_visual_qa(
    project_dir: Path,
    mode: str = "auto",
) -> Dict[str, Any]:
    """Run full content-aware visual quality assurance on a news video project directory.
    
    Generates and returns news_visual_qa_report dict adhering to schema.
    """
    project_dir = Path(project_dir)
    if mode == "auto":
        is_visual_mode_enabled = os.environ.get("NEWS_VISUAL_MODE", "0") in ("1", "true", "True")
        mode = "strict" if is_visual_mode_enabled else "flag_off"

    findings: List[Dict[str, Any]] = []
    failure_categories: List[str] = []

    missing_required_asset_count = 0
    unapproved_factual_visual_count = 0
    caption_overlap_blockers = 0
    credit_overlap_blockers = 0
    repetitive_layout_flag = False

    # 1. Visual Plan Check
    plan_path = None
    for cand in (project_dir / "artifacts" / "news_visual_plan.json", project_dir / "news_visual_plan.json"):
        if cand.is_file():
            plan_path = cand
            break

    plan_data: Optional[Dict[str, Any]] = None
    if plan_path:
        try:
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception as e:
            findings.append({
                "severity": "blocker" if mode == "strict" else "warning",
                "category": "NO_VISUAL_PLAN",
                "message": f"Malformed visual plan {plan_path}: {e}",
            })
            failure_categories.append("NO_VISUAL_PLAN")
    else:
        if mode == "strict":
            findings.append({
                "severity": "blocker",
                "category": "NO_VISUAL_PLAN",
                "message": "news_visual_plan.json is missing in project",
            })
            failure_categories.append("NO_VISUAL_PLAN")
        else:
            findings.append({
                "severity": "info",
                "category": "NO_VISUAL_PLAN",
                "message": "news_visual_plan.json not present (flag_off mode)",
            })

    beats = plan_data.get("beats", []) if plan_data else []

    # 2. Check unapproved factual claims (project-scoped only; never fall back to test fixtures)
    evidence_path = None
    for cand in (
        project_dir / "artifacts" / "news_evidence.json",
        project_dir / "news_evidence.json",
    ):
        if cand.is_file():
            evidence_path = cand
            break

    approved_claim_ids = set()
    if evidence_path and evidence_path.is_file():
        try:
            ev_data = json.loads(evidence_path.read_text(encoding="utf-8"))
            claims_list = ev_data if isinstance(ev_data, list) else ev_data.get("claims", [])
            for c in claims_list:
                if isinstance(c, dict):
                    cid = c.get("id") or c.get("claim_id") or c.get("section_id")
                    status = c.get("review_status") or c.get("status")
                    if cid and status in ("approved", "verified"):
                        approved_claim_ids.add(str(cid))
        except Exception:
            pass

    ledger_path = project_dir / "artifacts" / "claim_ledger.json"
    if ledger_path.is_file():
        try:
            l_data = json.loads(ledger_path.read_text(encoding="utf-8"))
            for c in l_data.get("claims", []):
                if isinstance(c, dict):
                    cid = c.get("claim_id") or c.get("id")
                    if cid and c.get("verdict") == "APPROVED" and c.get("confidence") == "verified":
                        approved_claim_ids.add(str(cid))
        except Exception:
            pass

    for beat in beats:
        claim_ids = beat.get("claim_ids", [])
        bid = beat.get("id") or beat.get("beat_id")
        if claim_ids:
            for cid in claim_ids:
                if cid not in approved_claim_ids:
                    unapproved_factual_visual_count += 1
                    findings.append({
                        "severity": "blocker" if mode == "strict" else "warning",
                        "category": "UNSUPPORTED_CLAIM",
                        "message": f"Beat '{bid}' references unapproved claim '{cid}'",
                        "beat_id": bid,
                    })
                    if "UNSUPPORTED_CLAIM" not in failure_categories:
                        failure_categories.append("UNSUPPORTED_CLAIM")

    # 3. Check Asset Resolution
    manifest_path = None
    for cand in (project_dir / "assets" / "visuals" / "manifest.json", project_dir / "artifacts" / "news_visual_assets.json"):
        if cand.is_file():
            manifest_path = cand
            break

    staged_assets = {}
    if manifest_path and manifest_path.is_file():
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for a in m_data.get("assets", []):
                aid = a.get("asset_id") or a.get("id")
                if aid:
                    staged_assets[aid] = a
        except Exception:
            pass

    for beat in beats:
        asset_ids = beat.get("asset_ids") or ([beat.get("asset_id")] if beat.get("asset_id") else [])
        bid = beat.get("id") or beat.get("beat_id")
        for aid in asset_ids:
            if aid not in staged_assets:
                missing_required_asset_count += 1
                findings.append({
                    "severity": "blocker" if mode == "strict" else "warning",
                    "category": "ASSET_UNRESOLVED",
                    "message": f"Beat '{bid}' requires unresolved asset '{aid}'",
                    "beat_id": bid,
                    "asset_id": aid,
                })
                if "ASSET_UNRESOLVED" not in failure_categories:
                    failure_categories.append("ASSET_UNRESOLVED")
            else:
                asset_info = staged_assets[aid]
                local_path = asset_info.get("file") or asset_info.get("local_path") or asset_info.get("path")
                if local_path:
                    full_p = project_dir / local_path
                    if not full_p.is_file():
                        missing_required_asset_count += 1
                        findings.append({
                            "severity": "blocker" if mode == "strict" else "warning",
                            "category": "ASSET_UNRESOLVED",
                            "message": f"Staged asset '{aid}' file not found on disk at {local_path}",
                            "beat_id": bid,
                            "asset_id": aid,
                        })
                        if "ASSET_UNRESOLVED" not in failure_categories:
                            failure_categories.append("ASSET_UNRESOLVED")
                    elif asset_info.get("sha256") and asset_info.get("sha256") != "dummy":
                        actual_sha = hashlib.sha256(full_p.read_bytes()).hexdigest()
                        if actual_sha != asset_info["sha256"]:
                            findings.append({
                                "severity": "blocker" if mode == "strict" else "warning",
                                "category": "ASSET_TAMPERED",
                                "message": f"Asset '{aid}' hash mismatch (tampered or corrupt): expected {asset_info['sha256']}, got {actual_sha}",
                                "beat_id": bid,
                                "asset_id": aid,
                            })
                            if "ASSET_TAMPERED" not in failure_categories:
                                failure_categories.append("ASSET_TAMPERED")

                    # Check proof vs AI generation boundary (A07: No fake proof)
                    is_ai_asset = asset_info.get("ai_generated") is True or asset_info.get("kind") == "illustration"
                    beat_strategy = beat.get("render_strategy")
                    beat_ev_class = beat.get("evidence_class")
                    is_proof_beat = (
                        beat_strategy in ("authentic_capture", "deterministic_svg")
                        or beat_ev_class in ("authentic_photo", "approved_source_visual", "approved_data_chart", "primary_proof")
                        or beat.get("is_proof_bearing") is True
                    )
                    if is_ai_asset and is_proof_beat:
                        findings.append({
                            "severity": "blocker" if mode == "strict" else "warning",
                            "category": "PROHIBITED_AI_PROOF",
                            "message": f"AI-generated asset '{aid}' assigned to proof-bearing beat '{bid}'; fake proof is strictly forbidden",
                            "beat_id": bid,
                            "asset_id": aid,
                        })
                        if "PROHIBITED_AI_PROOF" not in failure_categories:
                            failure_categories.append("PROHIBITED_AI_PROOF")

    # 4. Check HTML bindings and safe zones
    bound_beats = 0
    bound_beat_indices: set[int] = set()
    full_html_p = project_dir / "hyperframes" / "index.html"
    reels_html_p = project_dir / "hyperframes_reels" / "index.html"

    for variant_name, html_p in (("full", full_html_p), ("reels", reels_html_p)):
        if html_p.is_file():
            try:
                html_text = html_p.read_text(encoding="utf-8")
                safe_ok, safe_reasons = check_overlay_safe_zones(html_text, variant=variant_name)
                if not safe_ok:
                    caption_overlap_blockers += len(safe_reasons)
                    for r in safe_reasons:
                        findings.append({
                            "severity": "blocker" if mode == "strict" else "warning",
                            "category": "CAPTION_UI_COLLISION",
                            "message": r,
                        })
                    if "CAPTION_UI_COLLISION" not in failure_categories:
                        failure_categories.append("CAPTION_UI_COLLISION")
            except Exception:
                pass

    if beats:
        # Check beat binding coverage in HTML
        if full_html_p.is_file() or reels_html_p.is_file():
            html_content = ""
            if full_html_p.is_file():
                html_content += full_html_p.read_text(encoding="utf-8")
            if reels_html_p.is_file():
                html_content += reels_html_p.read_text(encoding="utf-8")

            script_path = next(
                (p for p in (
                    project_dir / "artifacts" / "script_en_US.json",
                    project_dir / "artifacts" / "script_vi.json",
                    project_dir / "artifacts" / "script.json",
                ) if p.is_file()),
                None,
            )
            script_sections: dict[str, Any] = {}
            if script_path:
                try:
                    s_data = json.loads(script_path.read_text(encoding="utf-8"))
                    for s in s_data.get("sections", []):
                        sid = s.get("id")
                        if sid:
                            script_sections[sid] = s
                except Exception:
                    pass

            for idx, beat in enumerate(beats):
                bid = beat.get("id") or beat.get("beat_id")
                sec_id = beat.get("script_section_id")
                asset_keys = beat.get("asset_ids") or ([beat.get("asset_id")] if beat.get("asset_id") else [])
                bid_str = str(bid).lower() if bid else ""
                bid_orig = str(bid) if bid else ""
                is_proof_beat = (
                    beat.get("render_strategy") == "authentic_capture"
                    or beat.get("evidence_class") in ("approved_source_visual", "authentic_photo")
                )
                proof_bound = any(aid in html_content for aid in asset_keys)
                if is_proof_beat and not proof_bound:
                    findings.append({
                        "severity": "blocker" if mode == "strict" else "warning",
                        "category": "VISUAL_NOT_RENDERED",
                        "message": f"Proof beat '{bid}' asset {asset_keys} is not referenced in HTML DOM",
                        "beat_id": bid,
                    })
                    if mode == "strict" and "VISUAL_NOT_RENDERED" not in failure_categories:
                        failure_categories.append("VISUAL_NOT_RENDERED")

                # Look for beat ID, section ID, scene index, or asset reference in HTML
                if (
                    (bid and (bid_orig in html_content or bid_str in html_content))
                    or proof_bound
                    or (sec_id and (f'id="{sec_id}"' in html_content or f'data-scene-id="{sec_id}"' in html_content or f'scene-{sec_id}' in html_content))
                    or f'id="scene-{idx + 1}"' in html_content
                    or f'id="scene{idx + 1}"' in html_content
                    or (bid and (f'id="scene-{bid_str}"' in html_content or f'id="badge-{bid_str}"' in html_content or f'id="scene-{bid_orig}"' in html_content))
                    or (f'class="scene' in html_content and (f'#scene-{idx + 1}' in html_content or f'#scene{idx + 1}' in html_content or (bid and (f'#scene-{bid_orig}' in html_content or f'#scene-{bid_str}' in html_content))))
                ):
                    if not is_proof_beat or proof_bound:
                        bound_beats += 1
                        bound_beat_indices.add(idx)
                elif beat.get("visual_kind") == "typographic_focus":
                    bound_beats += 1
                    bound_beat_indices.add(idx)

                # Visual-semantic verification: verify the scene in HTML relates to the script section
                sec_data = script_sections.get(sec_id) if sec_id else None
                if sec_data and mode == "strict":
                    sec_text = (sec_data.get("text") or sec_data.get("text_vi") or "").lower()
                    sec_keywords = [
                        w for w in re.findall(r'[a-zA-Z0-9àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]{4,}', sec_text)
                        if w not in {"this", "that", "with", "from", "have", "were", "been", "about", "when", "more", "into", "their"}
                    ]
                    has_semantic_match = (
                        any(w in html_content.lower() for w in sec_keywords[:5])
                        or any(aid in html_content for aid in asset_keys)
                        or beat.get("visual_kind") == "typographic_focus"
                    )
                    if not has_semantic_match and sec_keywords:
                        findings.append({
                            "severity": "blocker" if mode == "strict" else "warning",
                            "category": "CLAIM_VISUAL_MISMATCH",
                            "message": f"Beat '{bid}' (section '{sec_id}') visual elements in HTML do not reflect script semantic keywords: {sec_keywords[:3]}",
                            "beat_id": bid,
                        })
                        if mode == "strict" and "CLAIM_VISUAL_MISMATCH" not in failure_categories:
                            failure_categories.append("CLAIM_VISUAL_MISMATCH")
        binding_pct = round((bound_beats / len(beats)) * 100.0, 1)
    else:
        binding_pct = 100.0 if mode != "strict" else 0.0

    # 5. Provenance check
    prov_result = template_provenance.verify_project_provenance(project_dir)
    if not prov_result.get("ok"):
        # If provenance file exists and failed, or strict mode requires it
        if (project_dir / "template_provenance.json").is_file():
            for r in prov_result.get("reasons", []):
                findings.append({
                    "severity": "blocker" if mode == "strict" else "warning",
                    "category": "TEMPLATE_PROVENANCE_MISMATCH",
                    "message": f"Provenance integrity failure: {r}",
                })
            if "TEMPLATE_PROVENANCE_MISMATCH" not in failure_categories:
                failure_categories.append("TEMPLATE_PROVENANCE_MISMATCH")

    # 6. Repetitive layout check
    if len(beats) >= 3:
        layouts = [b.get("layout") for b in beats if b.get("layout")]
        kinds = [b.get("visual_kind") for b in beats]
        if layouts and len(beats) >= 4 and len(set(layouts)) == 1:
            repetitive_layout_flag = True
            findings.append({
                "severity": "blocker" if mode == "strict" else "warning",
                "category": "REPEATED_LAYOUT_NO_INFORMATION_GAIN",
                "message": f"All {len(beats)} beats use identical layout '{layouts[0]}' without functional variation",
            })
            if "REPEATED_LAYOUT_NO_INFORMATION_GAIN" not in failure_categories:
                failure_categories.append("REPEATED_LAYOUT_NO_INFORMATION_GAIN")
        elif all(k == "typographic_focus" for k in kinds):
            repetitive_layout_flag = True
            findings.append({
                "severity": "warning",
                "category": "BACKGROUND_MISMATCH",
                "message": "All beats use typographic_focus without informative visual background or diagram",
            })

    # 7. Scene hold policy (<= 12s max per scene/beat, >= 6 beats for Shorts) & Post-Render Frame Verification
    render_pct = _verify_scene_timeline_and_render_coverage(
        project_dir=project_dir,
        beats=beats,
        bound_beat_indices=bound_beat_indices,
        binding_pct=binding_pct,
        mode=mode,
        findings=findings,
        failure_categories=failure_categories,
    )

    # Determine overall pass
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    passed = (len(blockers) == 0)

    report = {
        "version": "1.0",
        "project_id": project_dir.name,
        "passed": passed,
        "mode": mode,
        "scorecard": {
            "missing_required_asset_count": missing_required_asset_count,
            "unapproved_factual_visual_count": unapproved_factual_visual_count,
            "visual_beat_binding_coverage_pct": binding_pct,
            "visual_beat_visible_in_render_coverage_pct": render_pct,
            "caption_overlap_blockers": caption_overlap_blockers,
            "credit_overlap_blockers": credit_overlap_blockers,
            "repetitive_layout_flag": repetitive_layout_flag,
        },
        "failure_categories": failure_categories,
        "findings": findings,
    }

    out_report_path = project_dir / "artifacts" / "news_visual_qa_report.json"
    out_report_path.parent.mkdir(parents=True, exist_ok=True)
    out_report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
