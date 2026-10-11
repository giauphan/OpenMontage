import pytest
from pathlib import Path

from scripts.repair_hyperframes_quality import REQUIRED_FONTS, patch_html

def test_source_badge_removal(tmp_path: Path):
    project_dir = tmp_path / "cand_test"
    project_dir.mkdir()

    html = """<!DOCTYPE html>
<html>
<head>
<style>
body { background: white; }
</style>
</head>
<body>
<div id="root" data-composition-id="test" data-width="1080" data-height="1920" data-duration="10.0">
  <h1>Test Title</h1>
  <div id="source-badge" class="source clip" data-start="0.000" data-duration="10.000">Nguồn: Hacker News</div>
  <div class="source-badge">Nguồn: Reuters.com</div>
</div>
</body>
</html>
"""
    index = project_dir / "index.html"
    index.write_text(html, encoding="utf-8")

    # Model a materialized composition; repair must not manufacture unrelated assets.
    assets = project_dir / "assets"
    assets.mkdir()
    for font_name in REQUIRED_FONTS:
        (assets / font_name).write_bytes(b"test-font")

    # Needs to match 10.0 duration
    patch_html(index, 10.0)

    result = index.read_text(encoding="utf-8")
    # Verify nodes are removed completely
    assert '<div id="source-badge"' not in result
    assert 'Nguồn:' not in result

    # Verify we DO NOT inject a global display: none hide rule anymore.
    # Blanket hiding sources violated Content Appropriateness.
    assert '#source-badge,' not in result
    assert "display: none !important;" not in result

