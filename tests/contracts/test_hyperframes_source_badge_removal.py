import pytest
from pathlib import Path

from scripts.repair_hyperframes_quality import patch_html

def test_source_badge_removal(tmp_path: Path):
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
    index = tmp_path / "index.html"
    index.write_text(html, encoding="utf-8")
    
    # Needs to match 10.0 duration
    patch_html(index, 10.0)
    
    result = index.read_text(encoding="utf-8")
    assert '<div id="source-badge"' not in result
    assert 'Nguồn:' not in result
    assert '#source-badge,' in result
    assert "display: none !important;" in result
    assert ".source," not in result
    assert ", .source" not in result

