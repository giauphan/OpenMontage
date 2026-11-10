"""T01: Verify that direct-mode HTML repair preserves scene-specific backgrounds.

Baseline failure (RED): scripts/repair_hyperframes_quality.py injects
/* Visual Quality Enhancement */ with .scene { background: transparent !important; }
and #stage { background: radial-gradient(...) !important; }, destroying intended distinct scene styling.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from scripts.repair_hyperframes_quality import patch_html


def test_t01_patch_preserves_distinct_scene_backgrounds(tmp_path: Path):
    """Direct-mode repair must not flatten scene-specific backgrounds with !important."""
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "visuals").mkdir(parents=True, exist_ok=True)

    # Required font assets that patch_html injects
    for font in ("BeVietnamPro-Regular.ttf", "BeVietnamPro-Bold.ttf", "BeVietnamPro-ExtraBold.ttf"):
        (assets_dir / font).write_bytes(b"mock font data")
    (assets_dir / "visuals" / "bg_npu.png").write_bytes(b"mock png data")

    html_content = """<!doctype html>
<html>
<head>
<style>
body { margin: 0; overflow: hidden; }
#stage { width: 1080px; height: 1920px; position: relative; }
.scene-alpha { background: linear-gradient(135deg, #102a43, #243b53); }
.scene-beta { background: url('assets/visuals/bg_npu.png') center/cover no-repeat; }
</style>
</head>
<body>
<div id="stage" class="composition" data-composition-id="main" data-start="0" data-duration="60" data-width="1080" data-height="1920">
  <div id="scene-1" class="scene scene-alpha" data-start="0" data-duration="30">
    <div class="card"><h1>Tiêu đề 1.</h1></div>
  </div>
  <div id="scene-2" class="scene scene-beta" data-start="30" data-duration="30">
    <div class="card"><h1>Tiêu đề 2.</h1></div>
  </div>
</div>
</body>
</html>"""
    test_html_path = tmp_path / "index.html"
    test_html_path.write_text(html_content, encoding="utf-8")

    # Run the patcher
    patch_html(test_html_path, narration_duration=60.0, strict=True)
    repaired_html = test_html_path.read_text(encoding="utf-8")

    # Invariant: Distinct scene styling should NOT be overridden by global .scene { background: transparent !important }
    assert ".scene {\n    background: transparent !important;" not in repaired_html, (
        "FAIL: repair_hyperframes_quality unconditionally injected .scene { background: transparent !important; }, "
        "flattening scene-specific backgrounds."
    )


def test_t02_visual_mode_preserves_authored_scene_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Visual mode repair must not force display:flex/justify-content:center when .scene layout is already authored."""
    monkeypatch.setenv("NEWS_VISUAL_MODE", "1")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for font in ("BeVietnamPro-Regular.ttf", "BeVietnamPro-Bold.ttf", "BeVietnamPro-ExtraBold.ttf"):
        (assets_dir / font).write_bytes(b"mock font data")

    html_content = """<!doctype html>
<html>
<head>
<style>
body { margin: 0; overflow: hidden; }
#stage { width: 1080px; height: 1920px; position: relative; }
.scene { position: absolute; inset: 0; padding: 70px 70px 360px; opacity: 0; }
</style>
</head>
<body>
<div id="stage" class="composition" data-composition-id="main" data-start="0" data-duration="60" data-width="1080" data-height="1920">
  <div id="scene-1" class="scene" data-start="0" data-duration="60">
    <h1>Headline.</h1>
  </div>
</div>
</body>
</html>"""
    test_html_path = tmp_path / "index.html"
    test_html_path.write_text(html_content, encoding="utf-8")

    patch_html(test_html_path, narration_duration=60.0, strict=True)
    repaired_html = test_html_path.read_text(encoding="utf-8")

    assert "justify-content: center" not in repaired_html
    assert "align-items: center" not in repaired_html


def test_t03_normalize_mobile_readable_css_stage_card():
    """Verify that .stage-card is upscaled, h1/metrics use correct floors, and token boundaries prevent false matches."""
    from scripts.repair_hyperframes_quality import _normalize_mobile_readable_css

    html = """<style>
.stage-card { font-size: 16px; color: #fff; }
.badge { font-size: 12px; }
.card-tag { font-size: 14px; }
h1 { font-size: 24px; }
.metric { font-size: 20px; }
.geometric-card { font-size: 18px; }
</style>"""
    normalized = _normalize_mobile_readable_css(html)
    assert ".stage-card { font-size: 28px; color: #fff; }" in normalized
    assert ".badge { font-size: 12px; }" in normalized
    assert ".card-tag { font-size: 14px; }" in normalized
    assert "h1 { font-size: 50px; }" in normalized
    assert ".metric { font-size: 54px; }" in normalized
    assert ".geometric-card { font-size: 28px; }" in normalized


