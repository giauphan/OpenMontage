"""Unit tests for lib.news_visual.visual_asset_orchestrator."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from lib.news_visual.asset_cache import VisualAssetCache
from lib.news_visual.visual_asset_orchestrator import VisualAssetOrchestrator


def make_test_png(width: int = 100, height: int = 177) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(30, 41, 59))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_plan():
    return {
        "version": "1.0",
        "project_id": "test_proj",
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec_0",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "render_strategy": "ai_illustration_eligible",
                "evidence_class": "illustration",
                "visual_intent": "Metaphor of ephemeral session loss",
                "asset_ids": ["art_vb01"],
                "fallback_policy": "typographic_card",
            },
            {
                "id": "vb-02",
                "script_section_id": "sec_1",
                "start_seconds": 10.0,
                "end_seconds": 20.0,
                "render_strategy": "authentic_capture",
                "evidence_class": "approved_source_visual",
                "visual_intent": "Terminal capture proving error",
                "asset_ids": ["cap_vb02"],
                "fallback_policy": "block",
            },
            {
                "id": "vb-03",
                "script_section_id": "sec_2",
                "start_seconds": 20.0,
                "end_seconds": 30.0,
                "render_strategy": "deterministic_svg",
                "evidence_class": "conceptual_diagram",
                "visual_intent": "Architecture blueprint diagram",
                "asset_ids": ["diag_vb03"],
                "fallback_policy": "use_builtin_verified_icon_diagram",
            },
        ],
    }


@pytest.fixture
def sample_topic():
    return {
        "candidate_id": "test_proj",
        "topic_family": "context_memory",
        "title": "Why Agents Forget Rules",
    }


def test_orchestrator_blocks_when_proof_capture_is_missing(tmp_path: Path, sample_plan, sample_topic):
    """When a proof-bearing beat requires authentic_capture but file is missing, status is BLOCKED_MISSING_PROOF."""
    project_dir = tmp_path / "proj"
    orchestrator = VisualAssetOrchestrator(cache=VisualAssetCache(cache_dir=tmp_path / "cache"))

    manifest = orchestrator.orchestrate_plan_assets(project_dir, sample_plan, sample_topic)
    assert manifest["summary"]["blocked_missing_proof"] == 1
    assert manifest["beat_results"]["vb-02"]["status"] == VisualAssetOrchestrator.STATUS_BLOCKED_MISSING_PROOF


def test_orchestrator_finds_authentic_capture(tmp_path: Path, sample_plan, sample_topic):
    """When authentic capture is present in news_source_capture/, it stages as READY_CAPTURE."""
    project_dir = tmp_path / "proj"
    cap_dir = project_dir / "artifacts" / "news_source_capture"
    cap_dir.mkdir(parents=True)
    cap_file = cap_dir / "cap_vb02.png"
    cap_file.write_bytes(make_test_png(width=500, height=500))

    orchestrator = VisualAssetOrchestrator(cache=VisualAssetCache(cache_dir=tmp_path / "cache"))
    manifest = orchestrator.orchestrate_plan_assets(project_dir, sample_plan, sample_topic)

    assert manifest["beat_results"]["vb-02"]["status"] == VisualAssetOrchestrator.STATUS_READY_CAPTURE
    staged_cap = project_dir / "assets" / "visuals" / "cap_vb02.png"
    assert staged_cap.is_file()


def test_orchestrator_deterministic_svg_generation(tmp_path: Path, sample_plan, sample_topic):
    """Deterministic SVG strategy generates high-contrast SVG diagram."""
    project_dir = tmp_path / "proj"
    orchestrator = VisualAssetOrchestrator(cache=VisualAssetCache(cache_dir=tmp_path / "cache"))

    manifest = orchestrator.orchestrate_plan_assets(project_dir, sample_plan, sample_topic)
    assert manifest["beat_results"]["vb-03"]["status"] == VisualAssetOrchestrator.STATUS_READY_SVG
    staged_svg = project_dir / "assets" / "visuals" / "diag_vb03.svg"
    assert staged_svg.is_file()
    assert "<svg" in staged_svg.read_text(encoding="utf-8")


def test_orchestrator_ai_visual_disabled_falls_back_to_svg(tmp_path: Path, sample_plan, sample_topic, monkeypatch):
    """When AI_VISUAL_ENABLED=0, ai_illustration_eligible beat falls back to contextual SVG."""
    monkeypatch.setenv("AI_VISUAL_ENABLED", "0")
    project_dir = tmp_path / "proj"
    orchestrator = VisualAssetOrchestrator(cache=VisualAssetCache(cache_dir=tmp_path / "cache"))

    manifest = orchestrator.orchestrate_plan_assets(project_dir, sample_plan, sample_topic)
    assert manifest["beat_results"]["vb-01"]["status"] == VisualAssetOrchestrator.STATUS_FALLBACK_CONTEXTUAL
    staged_fallback = project_dir / "assets" / "visuals" / "art_vb01.svg"
    assert staged_fallback.is_file()


def test_orchestrator_ai_visual_enabled_generates_and_caches(tmp_path: Path, sample_plan, sample_topic, monkeypatch):
    """When AI_VISUAL_ENABLED=1 and generation succeeds, stages READY_AI and hits cache on replay."""
    monkeypatch.setenv("AI_VISUAL_ENABLED", "1")
    project_dir = tmp_path / "proj"
    cache_dir = tmp_path / "cache"
    orchestrator = VisualAssetOrchestrator(cache=VisualAssetCache(cache_dir=cache_dir))

    fake_png = make_test_png()

    def mock_dispatch(dest_file, prompt, key):
        dest_file.write_bytes(fake_png)
        return {"success": True, "data": {"provider": "muse", "model": "muse-image"}}

    with patch.object(orchestrator, "_dispatch_muse_generation", side_effect=mock_dispatch):
        manifest1 = orchestrator.orchestrate_plan_assets(project_dir, sample_plan, sample_topic)
        assert manifest1["beat_results"]["vb-01"]["status"] == VisualAssetOrchestrator.STATUS_READY_AI
        assert manifest1["beat_results"]["vb-01"]["cache_hit"] is False

        # Re-run orchestrator: should be cache hit!
        manifest2 = orchestrator.orchestrate_plan_assets(project_dir, sample_plan, sample_topic)
        assert manifest2["beat_results"]["vb-01"]["status"] == VisualAssetOrchestrator.STATUS_READY_AI
        assert manifest2["beat_results"]["vb-01"]["cache_hit"] is True


def test_orchestrator_preserves_existing_rasters_without_render_strategy(tmp_path: Path, sample_topic):
    """Beats without explicit render_strategy leave existing rasters untouched for resolver."""
    project_dir = tmp_path / "proj"
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True)
    custom_raster = visuals_dir / "custom_raster.png"
    custom_raster.write_bytes(make_test_png(100, 100))

    plan = {
        "version": "1.0",
        "beats": [
            {
                "id": "vb-legacy",
                "asset_id": "custom_raster",
                "visual_intent": "Hand-authored diagram",
            }
        ]
    }
    orchestrator = VisualAssetOrchestrator(cache=VisualAssetCache(cache_dir=tmp_path / "cache"))
    manifest = orchestrator.orchestrate_plan_assets(project_dir, plan, sample_topic)

    assert custom_raster.is_file(), "Existing custom raster must not be deleted when render_strategy is absent"
    assert "vb-legacy" not in manifest["beat_results"]

