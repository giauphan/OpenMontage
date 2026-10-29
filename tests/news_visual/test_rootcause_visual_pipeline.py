"""Root-cause regression tests documenting visual pipeline and provider gaps.

Reproduces:
1. prepare_news_visuals.py does not invoke image providers or ImageSelector.
2. asset_resolver.py falsely defaults non-SVG files to authentic_photo and fixed 960x540.
3. prepare_news_visuals.py wipes custom visual plans if script_sha256 changes.
4. muse_gateway_image is not yet available in tool registry.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.tool_registry import ToolRegistry
from lib.news_visual.asset_resolver import resolve_visual_assets


def test_muse_gateway_tool_registered_in_registry():
    """Documents that muse_gateway_image is successfully registered in ToolRegistry."""
    registry = ToolRegistry()
    registry.discover()
    assert "muse_gateway_image" in registry._tools, (
        "Expected muse_gateway_image to be registered in ToolRegistry."
    )


def test_asset_resolver_correctly_identifies_ai_illustration_and_dimensions(tmp_path: Path):
    """Verifies that non-SVG illustration files are correctly typed as illustration with ai_generated origin."""
    from PIL import Image
    import io

    project_dir = tmp_path / "proj"
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    # Create a valid 1080x1920 portrait PNG
    img_path = visuals_dir / "art_beat1.png"
    buf = io.BytesIO()
    test_img = Image.new("RGB", (1080, 1920), color=(10, 20, 30))
    test_img.save(buf, format="PNG")
    img_path.write_bytes(buf.getvalue())

    plan = {
        "version": "1.0",
        "project_id": "proj",
        "script_sha256": "0" * 64,
        "enabled": True,
        "beats": [
            {
                "id": "vb-01",
                "script_section_id": "sec-01",
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "story_function": "concept_art",
                "visual_kind": "illustration",
                "evidence_class": "illustration",
                "claim_ids": ["C1"],
                "asset_ids": ["art_beat1"],
                "layout": "hero_center",
            }
        ],
    }

    # 1. Without orchestration record: unattributed raster falls back to unknown_generated
    manifest_unattributed = resolve_visual_assets(project_dir, plan, "0" * 64, "0" * 64)
    asset_unattributed = manifest_unattributed["assets"][0]
    assert asset_unattributed["kind"] == "illustration"
    assert asset_unattributed["origin"] == "unknown_generated"
    assert asset_unattributed.get("ai_generated") is not True

    # 2. With authoritative orchestration record from Muse: gets verified AI provenance
    art_dir = project_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    orch_data = {
        "project_id": "proj",
        "assets": [
            {
                "id": "art_beat1",
                "file": "assets/visuals/art_beat1.png",
                "kind": "illustration",
                "origin": "ai_generated",
            }
        ],
    }
    (art_dir / "orchestrated_assets.json").write_text(json.dumps(orch_data), encoding="utf-8")

    manifest = resolve_visual_assets(project_dir, plan, "0" * 64, "0" * 64)
    assert len(manifest["assets"]) == 1
    asset = manifest["assets"][0]

    # Verified fix: resolver assigns illustration, ai_generated, and actual probed dimensions
    assert asset["kind"] == "illustration"
    assert asset["origin"] == "ai_generated"
    assert asset.get("ai_generated") is True
    assert asset.get("provider") == "muse"
    assert asset["width"] == 1080 and asset["height"] == 1920


def test_prepare_news_visuals_preserves_raw_script_sha_whitespace(tmp_path: Path):
    """Verifies that prepare_news_visuals matches the exact sha256 of script on disk regardless of formatting."""
    import hashlib
    import sys
    from scripts import prepare_news_visuals

    project_dir = tmp_path / "cand_test_hash"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Write script JSON with compact 4-space formatting and unique trailing space
    script_obj = {
        "version": "1.0",
        "title": "Test Title",
        "total_duration_seconds": 66.0,
        "sections": [
            {"id": "scene-1", "text": "Hook sentence.", "start_seconds": 0.0, "end_seconds": 11.0},
            {"id": "scene-2", "text": "Detail sentence.", "start_seconds": 11.0, "end_seconds": 22.0},
            {"id": "scene-3", "text": "Architecture point.", "start_seconds": 22.0, "end_seconds": 33.0},
            {"id": "scene-4", "text": "Benchmark metric.", "start_seconds": 33.0, "end_seconds": 44.0},
            {"id": "scene-5", "text": "Real world impact.", "start_seconds": 44.0, "end_seconds": 55.0},
            {"id": "scene-6", "text": "Final conclusion.", "start_seconds": 55.0, "end_seconds": 66.0},
        ],
    }
    raw_script_text = json.dumps(script_obj, indent=4) + "\n   \n"
    raw_script_bytes = raw_script_text.encode("utf-8")
    expected_sha = hashlib.sha256(raw_script_bytes).hexdigest()
    (artifacts_dir / "script_en_US.json").write_bytes(raw_script_bytes)

    # Run main()
    old_argv = sys.argv
    try:
        sys.argv = ["prepare_news_visuals.py", str(project_dir)]
        exit_code = prepare_news_visuals.main()
        assert exit_code == 0, f"Expected prepare_news_visuals to exit 0, got {exit_code}"

        plan_data = json.loads((artifacts_dir / "news_visual_plan.json").read_text(encoding="utf-8"))
        assert plan_data["script_sha256"] == expected_sha, (
            f"Expected plan script_sha256 to match disk bytes {expected_sha}, got {plan_data['script_sha256']}"
        )
    finally:
        sys.argv = old_argv
