"""Unit tests for Phase 5: Visual QA, AI proof boundaries, and semantic review."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import pytest
from PIL import Image

from lib.news_visual.qa import run_news_visual_qa


def make_test_png(color=(15, 23, 42)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (1080, 1920), color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def base_project(tmp_path: Path):
    proj = tmp_path / "qa_proj"
    artifacts = proj / "artifacts"
    artifacts.mkdir(parents=True)
    visuals = proj / "assets" / "visuals"
    visuals.mkdir(parents=True)

    # Valid claim ledger
    ledger = {
        "schema_version": "1.0",
        "claims": [
            {
                "claim_id": "C001",
                "statement": "Coding agents lose memory across session restarts.",
                "verdict": "APPROVED",
                "confidence": "verified",
                "source": {"canonical_url": "https://example.com/doc", "publisher": "Docs"},
            }
        ],
    }
    (artifacts / "claim_ledger.json").write_text(json.dumps(ledger))

    return proj


def test_qa_flags_prohibited_ai_proof_when_ai_image_assigned_to_proof_beat(base_project: Path):
    """A07: QA must block release if an AI-generated image is assigned to a proof-bearing beat."""
    artifacts = base_project / "artifacts"
    visuals = base_project / "assets" / "visuals"

    png_bytes = make_test_png()
    (visuals / "fake_proof.png").write_bytes(png_bytes)
    sha256 = hashlib.sha256(png_bytes).hexdigest()

    # Plan with proof-bearing beat assigned to fake_proof
    plan = {
        "version": "1.0",
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "render_strategy": "authentic_capture",
                "evidence_class": "approved_source_visual",
                "is_proof_bearing": True,
                "claim_ids": ["C001"],
                "asset_ids": ["fake_proof"],
            }
        ],
    }
    (artifacts / "news_visual_plan.json").write_text(json.dumps(plan))

    # Manifest claiming fake_proof is ai_generated
    manifest = {
        "version": "1.0",
        "assets": [
            {
                "asset_id": "fake_proof",
                "file": "assets/visuals/fake_proof.png",
                "kind": "illustration",
                "ai_generated": True,
                "origin": "ai_generated",
                "sha256": sha256,
            }
        ],
    }
    (artifacts / "news_visual_assets.json").write_text(json.dumps(manifest))

    report = run_news_visual_qa(base_project, mode="strict")
    assert not report["passed"]
    assert "PROHIBITED_AI_PROOF" in report["failure_categories"]


def test_qa_flags_tampered_asset_hash(base_project: Path):
    """A08: QA must block release if local asset file does not match signed sha256."""
    artifacts = base_project / "artifacts"
    visuals = base_project / "assets" / "visuals"

    png_bytes = make_test_png()
    (visuals / "art_beat1.png").write_bytes(png_bytes)

    plan = {
        "version": "1.0",
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "render_strategy": "ai_illustration_eligible",
                "evidence_class": "illustration",
                "claim_ids": ["C001"],
                "asset_ids": ["art_beat1"],
            }
        ],
    }
    (artifacts / "news_visual_plan.json").write_text(json.dumps(plan))

    manifest = {
        "version": "1.0",
        "assets": [
            {
                "asset_id": "art_beat1",
                "file": "assets/visuals/art_beat1.png",
                "kind": "illustration",
                "ai_generated": True,
                "origin": "ai_generated",
                "sha256": "f" * 64,  # Mismatched SHA
            }
        ],
    }
    (artifacts / "news_visual_assets.json").write_text(json.dumps(manifest))

    report = run_news_visual_qa(base_project, mode="strict")
    assert not report["passed"]
    assert "ASSET_TAMPERED" in report["failure_categories"]


def test_qa_passes_valid_conceptual_ai_and_proof_separation(base_project: Path):
    """QA passes cleanly when AI illustration is on non-proof conceptual beat and proof beat uses SVG."""
    artifacts = base_project / "artifacts"
    visuals = base_project / "assets" / "visuals"

    png_bytes = make_test_png()
    (visuals / "art_concept.png").write_bytes(png_bytes)
    png_sha = hashlib.sha256(png_bytes).hexdigest()

    svg_content = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540"><rect width="960" height="540" fill="#0f172a"/></svg>'
    (visuals / "diag_proof.svg").write_text(svg_content)
    svg_sha = hashlib.sha256(svg_content.encode("utf-8")).hexdigest()

    plan = {
        "version": "1.0",
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "render_strategy": "ai_illustration_eligible",
                "evidence_class": "illustration",
                "claim_ids": ["C001"],
                "asset_ids": ["art_concept"],
            },
            {
                "id": "vb-02",
                "script_section_id": "sec_1",
                "start_seconds": 10.0,
                "end_seconds": 20.0,
                "render_strategy": "deterministic_svg",
                "evidence_class": "conceptual_diagram",
                "claim_ids": ["C001"],
                "asset_ids": ["diag_proof"],
            },
        ],
    }
    (artifacts / "news_visual_plan.json").write_text(json.dumps(plan))

    manifest = {
        "version": "1.0",
        "assets": [
            {
                "asset_id": "art_concept",
                "file": "assets/visuals/art_concept.png",
                "kind": "illustration",
                "ai_generated": True,
                "origin": "ai_generated",
                "sha256": png_sha,
            },
            {
                "asset_id": "diag_proof",
                "file": "assets/visuals/diag_proof.svg",
                "kind": "svg_diagram",
                "origin": "project-generated-verified-diagram",
                "sha256": svg_sha,
            },
        ],
    }
    (artifacts / "news_visual_assets.json").write_text(json.dumps(manifest))

    report = run_news_visual_qa(base_project, mode="strict")
    # No blockers for assets, unapproved claims, or prohibited proof
    assert "PROHIBITED_AI_PROOF" not in report["failure_categories"]
    assert "ASSET_UNRESOLVED" not in report["failure_categories"]
    assert "ASSET_TAMPERED" not in report["failure_categories"]
