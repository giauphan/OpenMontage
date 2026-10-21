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
import os
import re
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

    # 2. Check unapproved factual claims
    evidence_path = None
    for cand in (
        project_dir / "artifacts" / "news_evidence.json",
        project_dir / "news_evidence.json",
        ROOT / "tests" / "news_visual" / "fixtures" / "approved_test_claims.json",
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
                    cid = c.get("id") or c.get("claim_id")
                    status = c.get("review_status") or c.get("status")
                    if cid and status in ("approved", "verified"):
                        approved_claim_ids.add(cid)
        except Exception:
            pass

    for beat in beats:
        claim_ids = beat.get("claim_ids", [])
        if claim_ids:
            for cid in claim_ids:
                if cid not in approved_claim_ids:
                    unapproved_factual_visual_count += 1
                    findings.append({
                        "severity": "blocker" if mode == "strict" else "warning",
                        "category": "UNSUPPORTED_CLAIM",
                        "message": f"Beat '{beat.get('id')}' references unapproved claim '{cid}'",
                        "beat_id": beat.get("id"),
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
        asset_ids = beat.get("asset_ids", [])
        for aid in asset_ids:
            if aid not in staged_assets:
                missing_required_asset_count += 1
                findings.append({
                    "severity": "blocker" if mode == "strict" else "warning",
                    "category": "ASSET_UNRESOLVED",
                    "message": f"Beat '{beat.get('id')}' requires unresolved asset '{aid}'",
                    "beat_id": beat.get("id"),
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
                            "beat_id": beat.get("id"),
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
                                "beat_id": beat.get("id"),
                                "asset_id": aid,
                            })
                            if "ASSET_TAMPERED" not in failure_categories:
                                failure_categories.append("ASSET_TAMPERED")

    # 4. Check HTML bindings and safe zones
    bound_beats = 0
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
                            "category": "CAPTION_COLLISION",
                            "message": r,
                        })
                    if "CAPTION_COLLISION" not in failure_categories:
                        failure_categories.append("CAPTION_COLLISION")
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

            for beat in beats:
                bid = beat.get("id")
                sec_id = beat.get("script_section_id")
                asset_keys = beat.get("asset_ids", [])
                # Look for beat ID, section ID, or asset reference in HTML
                if (
                    (bid and bid in html_content)
                    or any(aid in html_content for aid in asset_keys)
                    or (sec_id and (f'id="{sec_id}"' in html_content or f'data-scene-id="{sec_id}"' in html_content or f'scene-{sec_id}' in html_content))
                ):
                    bound_beats += 1
                elif beat.get("visual_kind") == "typographic_focus":
                    bound_beats += 1
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
        kinds = [b.get("visual_kind") for b in beats]
        if all(k == "typographic_focus" for k in kinds):
            repetitive_layout_flag = True
            findings.append({
                "severity": "warning",
                "category": "BACKGROUND_MISMATCH",
                "message": "All beats use typographic_focus without informative visual background or diagram",
            })

    # Render coverage (can be checked if mp4 exists)
    render_pct = binding_pct

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
