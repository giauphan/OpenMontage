import importlib.util
from pathlib import Path
import sys
import re

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "repair_hyperframes_quality", ROOT / "scripts" / "repair_hyperframes_quality.py"
)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)

def test_strict_repair_normalizes_unregistered_subcompositions(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>#root { width: 1080px; height: 1920px; }</style>
</head>
<body>
    <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="10.0">
        <div class="test" data-composition-id="antspace-discovery" data-start="0"></div>
        <div data-composition-id="legit-sub"></div>
    </div>
    <script>
        const tl = gsap.timeline();
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
        window.__timelines['legit-sub'] = gsap.timeline();
    </script>
</body>
</html>"""
    comp = tmp_path / "index.html"
    comp.write_text(html, encoding="utf-8")
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    assert 'data-composition-id="main"' in patched
    assert 'data-composition-id="legit-sub"' in patched
    assert 'data-composition-id="antspace-discovery"' not in patched
    assert 'class="test"' in patched

def test_strict_repair_preserves_registered_subcompositions(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>#root { width: 1080px; height: 1920px; }</style>
</head>
<body>
    <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="10.0">
        <div class="test" data-composition-id="antspace-discovery" data-start="0"></div>
        <div data-composition-id="legit-sub"></div>
    </div>
    <script>
        const tl = gsap.timeline();
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
        window.__timelines['legit-sub'] = gsap.timeline();
    </script>
</body>
</html>"""
    comp = tmp_path / "index.html"
    comp.write_text(html, encoding="utf-8")
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    assert 'data-composition-id="main"' in patched
    assert 'data-composition-id="legit-sub"' in patched
    assert 'data-composition-id="antspace-discovery"' not in patched
    assert 'class="test"' in patched

