"""Phase 5: Content-aware visual QA tests.

Tests:
1. Seeded poor-quality OWN1-like text-only video fails the visual coverage gate in strict mode.
2. Seeded invalid 78% evidence card (referencing rejected claim) blocks release.
3. Genuinely relevant background+icon+diagram video passes visual QA.
4. Generated report matches schemas/news/news_visual_qa_report.schema.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import jsonschema

from lib.news_visual.qa import run_news_visual_qa

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "tests" / "news_visual" / "fixtures"
QA_SCHEMA_PATH = ROOT / "schemas" / "news" / "news_visual_qa_report.schema.json"


@pytest.fixture
def qa_schema() -> dict:
    return json.loads(QA_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_text_only_fixture_fails_visual_coverage_gate_in_strict_mode(tmp_path: Path, qa_schema: dict):
    """OWN1-style text-only candidate without visual plan fails strict visual QA."""
    project_dir = tmp_path / "cand_own1_text_only"
    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Empty text-only project
    report = run_news_visual_qa(project_dir, mode="strict")

    assert not report["passed"], "Text-only project without visual plan must fail strict visual QA"
    assert "NO_VISUAL_PLAN" in report["failure_categories"]
    jsonschema.validate(instance=report, schema=qa_schema)


def test_unapproved_78_percent_claim_blocks_release(tmp_path: Path, qa_schema: dict):
    """Visual referencing unapproved 78% claim must fail closed with UNSUPPORTED_CLAIM."""
    project_dir = tmp_path / "cand_unapproved_claim"
    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Copy rejected claims as news_evidence.json
    rejected_fixture = FIXTURES_DIR / "rejected_test_claims.json"
    (artifacts_dir / "news_evidence.json").write_text(
        rejected_fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Visual plan referencing unapproved claim-unapproved-01
    plan = {
        "version": "1.0",
        "project_id": "cand_unapproved_claim",
        "script_sha256": "0" * 64,
        "enabled": True,
        "beats": [
            {
                "id": "vb-stat",
                "script_section_id": "context",
                "start_seconds": 0,
                "end_seconds": 10,
                "story_function": "statistic",
                "visual_kind": "source_chart",
                "evidence_class": "approved_data_chart",
                "claim_ids": ["claim-unapproved-01"],  # The 78% claim
                "asset_ids": [],
                "layout": "source_chart"
            }
        ]
    }
    (artifacts_dir / "news_visual_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    report = run_news_visual_qa(project_dir, mode="strict")

    assert not report["passed"], "Unapproved 78% claim visual must not pass release gate"
    assert "UNSUPPORTED_CLAIM" in report["failure_categories"]
    assert report["scorecard"]["unapproved_factual_visual_count"] > 0
    jsonschema.validate(instance=report, schema=qa_schema)


def test_fully_grounded_visual_project_passes_visual_qa(tmp_path: Path, qa_schema: dict):
    """Project with resolved assets, approved claims, and safe overlay passes visual QA."""
    project_dir = tmp_path / "cand_grounded_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    hf_dir = project_dir / "hyperframes"
    hf_dir.mkdir(parents=True, exist_ok=True)
    reels_dir = project_dir / "hyperframes_reels"
    reels_dir.mkdir(parents=True, exist_ok=True)

    # Approved claims
    approved_fixture = FIXTURES_DIR / "approved_test_claims.json"
    (artifacts_dir / "news_evidence.json").write_text(
        approved_fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Staged asset
    diagram_img = visuals_dir / "diagram.svg"
    diagram_img.write_text("<svg><rect width='100' height='100'/></svg>", encoding="utf-8")

    manifest = {
        "version": "1.0",
        "project_id": "cand_grounded_project",
        "assets": [
            {
                "id": "asset-diagram-01",
                "kind": "svg_diagram",
                "mime": "image/svg+xml",
                "local_path": "assets/visuals/diagram.svg",
                "sha256": "dummy",
                "rights_status": "in_house",
                "reviewed_by": "editorial_board"
            }
        ]
    }
    (visuals_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Visual plan referencing approved claim and staged asset
    plan = {
        "version": "1.0",
        "project_id": "cand_grounded_project",
        "script_sha256": "0" * 64,
        "enabled": True,
        "beats": [
            {
                "id": "vb-concept",
                "script_section_id": "concept",
                "start_seconds": 0,
                "end_seconds": 15,
                "story_function": "architecture",
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "claim_ids": ["claim-01"],
                "asset_ids": ["asset-diagram-01"],
                "layout": "chip_flow"
            }
        ]
    }
    (artifacts_dir / "news_visual_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    # HTML files containing beat ID and safe overlay
    html_content = (
        '<html><body>'
        '<div id="vb-concept"><img src="assets/visuals/diagram.svg" /></div>'
        '<div class="source-label" style="top: 5%;">Nguồn: Benchmark</div>'
        '<div class="caption">Đoạn tường thuật.</div>'
        '</body></html>'
    )
    (hf_dir / "index.html").write_text(html_content, encoding="utf-8")
    (reels_dir / "index.html").write_text(html_content, encoding="utf-8")

    report = run_news_visual_qa(project_dir, mode="strict")

    assert report["passed"], f"Expected grounded project to pass visual QA: {report.get('findings')}"
    assert report["scorecard"]["missing_required_asset_count"] == 0
    assert report["scorecard"]["unapproved_factual_visual_count"] == 0
    assert report["scorecard"]["caption_overlap_blockers"] == 0
    jsonschema.validate(instance=report, schema=qa_schema)


def test_schema_compliant_news_visual_assets_manifest_passes_qa(tmp_path: Path, qa_schema: dict):
    """Manifest using schema-compliant 'asset_id' and 'file' passes strict visual QA without unresolved asset blockers."""
    project_dir = tmp_path / "cand_schema_manifest"
    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    hf_dir = project_dir / "hyperframes"
    hf_dir.mkdir(parents=True, exist_ok=True)

    diagram_svg = visuals_dir / "diagram-intro.svg"
    diagram_svg.write_text("<svg><circle r='50'/></svg>", encoding="utf-8")
    diagram_sha = hashlib.sha256(diagram_svg.read_bytes()).hexdigest()

    # Schema-compliant news_visual_assets.json
    assets_manifest = {
        "version": "1.0",
        "script_sha256": "0" * 64,
        "visual_plan_sha256": "0" * 64,
        "assets": [
            {
                "asset_id": "diagram-intro",
                "beat_ids": ["vb-01"],
                "kind": "svg_diagram",
                "file": "assets/visuals/diagram-intro.svg",
                "sha256": diagram_sha,
                "mime": "image/svg+xml",
                "width": 960,
                "height": 540,
                "origin": "project-generated-verified-diagram",
                "rights_status": "cleared_for_use",
                "credit": None,
                "claim_ids": []
            }
        ]
    }
    (artifacts_dir / "news_visual_assets.json").write_text(json.dumps(assets_manifest), encoding="utf-8")

    plan = {
        "version": "1.0",
        "project_id": "cand_schema_manifest",
        "script_sha256": "0" * 64,
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "intro",
                "start_seconds": 0,
                "end_seconds": 12,
                "story_function": "intro",
                "visual_kind": "svg_diagram",
                "evidence_class": "conceptual_diagram",
                "claim_ids": [],
                "asset_ids": ["diagram-intro"],
                "layout": "hero_center"
            }
        ]
    }
    (artifacts_dir / "news_visual_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    html_content = (
        '<html><body>'
        '<div id="intro" data-scene-id="intro"><img src="assets/visuals/diagram-intro.svg" /></div>'
        '<div class="caption">Tiêu điểm công nghệ.</div>'
        '</body></html>'
    )
    (hf_dir / "index.html").write_text(html_content, encoding="utf-8")

    report = run_news_visual_qa(project_dir, mode="strict")
    assert report["passed"], f"Expected schema manifest to pass visual QA: {report.get('findings')}"
    assert report["scorecard"]["missing_required_asset_count"] == 0
    assert report["scorecard"]["visual_beat_binding_coverage_pct"] == 100.0
    jsonschema.validate(instance=report, schema=qa_schema)
