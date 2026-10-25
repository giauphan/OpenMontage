import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "repair_hyperframes_quality", ROOT / "scripts" / "repair_hyperframes_quality.py"
)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)

def test_strict_repair_fails_closed_for_unregistered_subcompositions(tmp_path):
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
        const tl = gsap.timeline({ paused: true });
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
        window.__timelines['legit-sub'] = gsap.timeline({ paused: true });
    </script>
</body>
</html>"""
    comp = tmp_path / "index.html"
    comp.write_text(html, encoding="utf-8")
    with pytest.raises(ValueError, match="not registered for composition 'antspace-discovery'"):
        repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    assert 'data-composition-id="main"' in patched
    assert 'data-composition-id="legit-sub"' in patched
    assert 'data-composition-id="antspace-discovery"' in patched
    assert 'class="test"' in patched

def test_repair_binds_narration_to_fallback_root_when_composition_id_missing(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>body { font-family: 'BeVietnamPro'; }</style>
    <style>body { font-family: 'BeVietnamPro'; }</style>
</head>
<body>
    <div id="canvas">
        <h1>Content</h1>
    </div>
    <script>
        const tl = gsap.timeline({ paused: true });
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
    </script>
</body>
</html>"""
    comp = tmp_path / "index.html"
    comp.write_text(html, encoding="utf-8")
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    assert '<audio id="narration"' in patched
    assert 'data-composition-id="main"' in patched


def test_repair_accepts_dot_notation_timeline_registration_and_en_us_landscape_defaults(tmp_path):
    project_dir = tmp_path / "cand_en_test"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "script_en_US.json").write_text('{"locale": "en-US", "sections": []}', encoding="utf-8")
    comp_dir = project_dir / "hyperframes"
    comp_dir.mkdir(parents=True)
    assets_dir = comp_dir / "assets"
    assets_dir.mkdir(parents=True)
    for font_name in repair.REQUIRED_FONTS:
        (assets_dir / font_name).write_bytes(b"font")

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <style>body { font-family: 'BeVietnamPro'; overflow: hidden; }</style>
</head>
<body>
    <main id="stage">
        <section class="scene" data-scene="0" data-start="0" data-end="10"><h1>Test</h1></section>
    </main>
    <script>
        window.__timelines = window.__timelines || {};
        const tl = gsap.timeline({ paused: true });
        window.__timelines.main = tl;
    </script>
</body>
</html>"""
    comp = comp_dir / "index.html"
    comp.write_text(html, encoding="utf-8")
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text(encoding="utf-8")
    assert 'data-width="1920"' in patched
    assert 'data-height="1080"' in patched
    assert repair.validate_html(comp) == []


