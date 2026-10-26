#!/usr/bin/env python3
"""Stage and resolve visual assets for the Daily News HyperFrames pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.news_visual.plan_contract import validate_visual_plan
from lib.news_visual.asset_resolver import resolve_visual_assets, validate_asset_file


def build_default_visual_plan(project_dir: Path, script_data: dict, script_sha: str) -> dict:
    """Construct a grounded, beat-aligned visual plan from script sections."""
    project_id = project_dir.name
    beats = []
    sections = script_data.get("sections", [])
    for i, sec in enumerate(sections):
        sec_id = sec.get("id", f"scene-{i+1}")
        start = float(sec.get("start_seconds", i * 12.0))
        end = float(sec.get("end_seconds", (i + 1) * 12.0))
        beats.append({
            "id": f"vb-{i+1:02d}",
            "script_section_id": str(sec_id),
            "start_seconds": start,
            "end_seconds": end,
            "story_function": sec.get("scene_type", sec_id),
            "visual_kind": "svg_diagram" if i in (1, 2, 3) else "illustration",
            "evidence_class": "conceptual_diagram" if i in (1, 2, 3) else "illustration",
            "claim_ids": [],
            "asset_ids": [f"diagram-{sec_id}"],
            "layout": "diagram_left_copy_right" if i in (1, 2, 3) else "hero_center",
            "background_preset": "technical_dark_gradient",
            "motion_preset": "node_flow_reveal",
            "fallback_policy": "use_builtin_verified_icon_diagram"
        })

    return {
        "version": "1.0",
        "project_id": project_id,
        "script_sha256": script_sha,
        "enabled": True,
        "beats": beats
    }


def stage_composition_visuals(project_dir: Path, assets_manifest: dict) -> None:
    """Stage resolved local visual files into hyperframes/ and hyperframes_reels/."""
    for comp in ("hyperframes", "hyperframes_reels"):
        comp_visuals = project_dir / comp / "assets" / "visuals"
        comp_visuals.mkdir(parents=True, exist_ok=True)
        for asset in assets_manifest.get("assets", []):
            src_rel = asset.get("file")
            if not src_rel:
                continue
            src_path = project_dir / src_rel
            if not src_path.is_file():
                raise FileNotFoundError(f"Source visual file not found: {src_path}")
            dest_path = comp_visuals / src_path.name
            shutil.copy2(src_path, dest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and stage news visual assets")
    parser.add_argument("project_dir", type=Path, help="Path to project directory")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    artifacts_dir = project_dir / "artifacts"
    if (artifacts_dir / "script_en_US.json").is_file():
        script_path = artifacts_dir / "script_en_US.json"
    elif (artifacts_dir / "script_vi.json").is_file():
        script_path = artifacts_dir / "script_vi.json"
    elif (artifacts_dir / "script.json").is_file():
        script_path = artifacts_dir / "script.json"
    else:
        script_path = artifacts_dir / "script_en_US.json"
    evidence_path = artifacts_dir / "news_evidence.json"
    plan_path = artifacts_dir / "news_visual_plan.json"
    assets_manifest_path = artifacts_dir / "news_visual_assets.json"

    if not script_path.is_file():
        print(f"ERROR: {script_path} missing; script stage must precede visuals", file=sys.stderr)
        return 1

    script_bytes = script_path.read_bytes()
    script_sha = hashlib.sha256(script_bytes).hexdigest()
    script_data = json.loads(script_bytes.decode("utf-8"))

    evidence_data = None
    if evidence_path.is_file():
        try:
            evidence_data = json.loads(evidence_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"WARN: Cannot parse news_evidence.json: {exc}", file=sys.stderr)

    # Load or generate plan
    from lib.news_visual.visual_planner import ClaimAwareVisualPlanner
    planner = ClaimAwareVisualPlanner()
    ledger_path = artifacts_dir / "claim_ledger.json"
    claim_ledger = None
    if ledger_path.is_file():
        try:
            claim_ledger = json.loads(ledger_path.read_text(encoding="utf-8")).get("claims", [])
        except Exception:
            claim_ledger = None

    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("script_sha256") != script_sha:
                # Try retiming existing authored plan first to preserve intent and asset bindings
                try:
                    plan = planner.retime_plan(plan, script_data)
                    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as retime_exc:
                    print(f"INFO: Retiming could not preserve plan ({retime_exc}); regenerating", file=sys.stderr)
                    if claim_ledger:
                        plan = planner.plan_visuals(project_dir.name, script_data, claim_ledger)
                    else:
                        plan = build_default_visual_plan(project_dir, script_data, script_sha)
                    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"ERROR: Malformed news_visual_plan.json: {exc}", file=sys.stderr)
            return 1
    else:
        if claim_ledger:
            try:
                plan = planner.plan_visuals(project_dir.name, script_data, claim_ledger)
            except Exception as plan_exc:
                print(f"WARN: Claim-aware planning fell back to default: {plan_exc}", file=sys.stderr)
                plan = build_default_visual_plan(project_dir, script_data, script_sha)
        else:
            plan = build_default_visual_plan(project_dir, script_data, script_sha)
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    # Validate plan contract
    plan_errors = validate_visual_plan(plan, script_bytes=script_bytes, evidence_data=evidence_data)
    if plan_errors:
        print("ERROR: news_visual_plan failed validation:\n" + "\n".join(f"  - {e}" for e in plan_errors), file=sys.stderr)
        return 2

    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()

    # Orchestrate assets before manifest resolution
    try:
        from lib.news_visual.visual_asset_orchestrator import VisualAssetOrchestrator
        brief_path = artifacts_dir / "research_brief.json"
        topic_info = {"candidate_id": project_dir.name}
        if brief_path.is_file():
            try:
                bdata = json.loads(brief_path.read_text(encoding="utf-8"))
                topic_info["title"] = bdata.get("topic") or project_dir.name
                topic_info["topic_family"] = bdata.get("topic_family", "context_memory")
            except Exception:
                pass
        orchestrator = VisualAssetOrchestrator()
        orch_res = orchestrator.orchestrate_plan_assets(project_dir, plan, topic_info, claim_ledger=claim_ledger)
        if orch_res.get("summary", {}).get("blocked_missing_proof", 0) > 0:
            print("ERROR: Visual orchestrator blocked: proof-bearing beat lacks authentic capture", file=sys.stderr)
            return 4
    except Exception as orch_exc:
        print(f"WARN: Visual asset orchestration encountered warning: {orch_exc}", file=sys.stderr)

    # Resolve and stage assets
    try:
        assets_manifest = resolve_visual_assets(project_dir, plan, script_sha, plan_sha)
        assets_manifest_path.write_text(json.dumps(assets_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        stage_composition_visuals(project_dir, assets_manifest)
    except Exception as exc:
        print(f"ERROR: Visual asset resolution failed: {exc}", file=sys.stderr)
        return 3

    print(f"Visual preparation OK: {len(assets_manifest.get('assets', []))} visual assets staged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
