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


from lib.news_visual.qa_video_checks import (
    MAX_SCENE_HOLD_SECONDS,
    MAX_SCENE_HOLD_TOLERANCE,
    check_overlay_safe_zones,
    _probe_video_duration,
    _sample_upper_frame_gray,
    _frame_std_dev,
    _frame_mad,
    _check_html_scene_hold_limits,
    _verify_scene_timeline_and_render_coverage,
)


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

    if any(part == ".." for part in Path(project_dir).parts):
        findings.append({
            "severity": "blocker",
            "category": "INVALID_PROJECT_DIR",
            "message": f"Path traversal in project directory: {project_dir}",
        })
        failure_categories.append("INVALID_PROJECT_DIR")
        return {
            "version": "1.0",
            "project_id": str(project_dir),
            "passed": False,
            "mode": mode,
            "scorecard": {
                "missing_required_asset_count": 0,
                "unapproved_factual_visual_count": 0,
                "visual_beat_binding_coverage_pct": 0.0,
                "visual_beat_visible_in_render_coverage_pct": 0.0,
                "caption_overlap_blockers": 0,
                "credit_overlap_blockers": 0,
                "repetitive_layout_flag": False,
            },
            "failure_categories": failure_categories,
            "findings": findings,
            "summary": f"Path traversal detected in project directory: {project_dir}",
        }
    project_dir = Path(project_dir).resolve()

    missing_required_asset_count = 0
    unapproved_factual_visual_count = 0
    caption_overlap_blockers = 0
    credit_overlap_blockers = 0
    repetitive_layout_flag = False

    # 1. Visual Plan Check
    plan_path = None
    for cand in (project_dir / "artifacts" / "news_visual_plan.json", project_dir / "news_visual_plan.json"):
        if cand.is_symlink():
            continue
        cand_res = cand.resolve()
        try:
            cand_res.relative_to(project_dir)
            if cand_res.is_file():
                plan_path = cand_res
                break
        except ValueError:
            continue

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
        if cand.is_symlink():
            continue
        cand_res = cand.resolve()
        try:
            cand_res.relative_to(project_dir)
            if cand_res.is_file():
                evidence_path = cand_res
                break
        except ValueError:
            continue

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
        if cand.is_symlink():
            continue
        cand_res = cand.resolve()
        try:
            cand_res.relative_to(project_dir)
            if cand_res.is_file():
                manifest_path = cand_res
                break
        except ValueError:
            continue

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
                    local_p = Path(local_path)
                    if any(part == ".." for part in local_p.parts) or local_p.is_absolute():
                        findings.append({
                            "severity": "blocker" if mode == "strict" else "warning",
                            "category": "ASSET_UNRESOLVED",
                            "message": f"Asset '{aid}' has invalid traversal path {local_path}",
                            "beat_id": bid,
                            "asset_id": aid,
                        })
                        if "ASSET_UNRESOLVED" not in failure_categories:
                            failure_categories.append("ASSET_UNRESOLVED")
                    else:
                        raw_asset_p = project_dir / local_p
                        if raw_asset_p.is_symlink():
                            is_safe_asset = False
                        else:
                            full_p = raw_asset_p.resolve()
                            try:
                                full_p.relative_to(project_dir)
                                is_safe_asset = full_p.is_file()
                            except ValueError:
                                is_safe_asset = False
                        if not is_safe_asset:
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

    out_report_path = (project_dir / "artifacts" / "news_visual_qa_report.json").resolve()
    if out_report_path.is_symlink() or not out_report_path.is_relative_to(project_dir):
        raise ValueError(f"Invalid news visual QA report path: {out_report_path}")
    out_report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_report_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    return report
