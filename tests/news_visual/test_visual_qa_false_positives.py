"""T07, T08: Verify visual QA false positives and content-aware coverage gate.

Baseline failure (RED):
1. Existing technical QA (validate_render_quality) passes text-only glassmorphic videos (R7).
2. Content-aware visual QA module (lib.news_visual.qa and scripts/validate_news_visuals.py) does not exist yet.
3. Safe zone collision validator between 9:16 bottom captions and source labels is missing.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_t07_visual_qa_module_exists():
    """T07: Content-aware visual QA module must exist (R7)."""
    try:
        import lib.news_visual.qa as news_visual_qa
    except ImportError:
        pytest.fail("FAIL: lib.news_visual.qa module is not implemented yet (R7).")


def test_t07_visual_qa_script_exists():
    """T07: scripts/validate_news_visuals.py must exist and have CLI entrypoint."""
    qa_script = ROOT / "scripts" / "validate_news_visuals.py"
    assert qa_script.is_file(), (
        "FAIL: scripts/validate_news_visuals.py does not exist (R7)."
    )


def test_t08_safe_zone_caption_collision_detection():
    """T08: Must detect overlay collision when source labels enter bottom 16% caption rail."""
    from lib.news_visual.qa import check_overlay_safe_zones

    # Unsafe case: source label placed at bottom: 5% (enters bottom 16% caption rail)
    unsafe_overlays = [
        {"id": "source_label_1", "bottom_pct": 5.0}
    ]
    ok, reasons = check_overlay_safe_zones(unsafe_overlays, variant="reels")
    assert not ok, "Expected collision detection for overlay in bottom 16% rail"
    assert any("safe rail" in r for r in reasons)

    # Safe case: source label placed at top or bottom: 25% (outside bottom 16% rail)
    safe_overlays = [
        {"id": "source_label_1", "top_pct": 5.0}
    ]
    ok, reasons = check_overlay_safe_zones(safe_overlays, variant="reels")
    assert ok, f"Safe overlay falsely flagged: {reasons}"


def test_t07_visual_qa_detects_missing_plan_in_strict_mode(tmp_path: Path):
    """T07: In strict mode, missing visual plan fails QA with blocker."""
    from lib.news_visual.qa import run_news_visual_qa
    import jsonschema

    project_dir = tmp_path / "cand_text_only"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    # Run in strict mode
    report_strict = run_news_visual_qa(project_dir, mode="strict")
    assert not report_strict["passed"]
    assert "NO_VISUAL_PLAN" in report_strict["failure_categories"]

    # Validate against report schema
    schema_path = ROOT / "schemas" / "news" / "news_visual_qa_report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=report_strict, schema=schema)

    # Run in flag_off mode: should not block
    report_off = run_news_visual_qa(project_dir, mode="flag_off")
    assert report_off["passed"]
