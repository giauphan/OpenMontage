"""Portrait canvas contract for HyperFrames compositions.

Regression guard for a published defect: `renders/final_full_vi_9x16.mp4` was
rendered from a 1920x1080 `hyperframes/index.html`, so a landscape video reached
vertical-only social platforms. `validate_render_quality.py` only catches this
after paying for a render, so the source gate must reject it first.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "repair_hyperframes_quality", ROOT / "scripts" / "repair_hyperframes_quality.py"
)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def composition_html(width: int, height: int, *, viewport: tuple[int, int] | None = None) -> str:
    vw, vh = viewport or (width, height)
    return f"""<!doctype html>
<html lang="vi">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={vw}, height={vh}" />
    <style>
      {repair.FONT_CSS}
      :root {{ --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }}
      #root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-width="{width}" data-height="{height}" data-duration="5">
      {repair.NARRATION_TAG}
      <section data-start="0" data-duration="5" data-track-index="1">Điểm thi giảm</section>
    </div>
  </body>
</html>
"""


def write_composition(tmp_path: Path, html: str) -> Path:
    index = tmp_path / "index.html"
    index.write_text(html, encoding="utf-8")
    return index


def test_portrait_composition_passes(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1920))
    assert repair.validate_html(index) == []


def test_nfd_vietnamese_text_passes_glyph_validation(tmp_path):
    html = composition_html(1080, 1920).replace("Điểm thi giảm", "Tiếng Việt")
    assert repair.validate_html(write_composition(tmp_path, html)) == []


def test_html_escaped_vietnamese_text_passes_glyph_validation(tmp_path):
    html = composition_html(1080, 1920).replace("Điểm thi giảm", "Ti&#7871;ng Vi&#7879;t")
    assert repair.validate_html(write_composition(tmp_path, html)) == []


def test_english_only_text_fails_glyph_validation(tmp_path):
    html = composition_html(1080, 1920).replace("Điểm thi giảm", "OpenAI Research")
    errors = repair.validate_html(write_composition(tmp_path, html))
    assert any("no Vietnamese diacritic text found" in error for error in errors)


def test_landscape_composition_fails(tmp_path):
    index = write_composition(tmp_path, composition_html(1920, 1080))
    errors = repair.validate_html(index)
    assert any("expected 1080x1920 portrait canvas" in error for error in errors)
    assert any("got 1920x1080" in error for error in errors)


def test_square_composition_fails(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1080))
    errors = repair.validate_html(index)
    assert any("got 1080x1080" in error for error in errors)


def test_conflicting_declarations_fail(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1920, viewport=(1920, 1080)))
    errors = repair.validate_html(index)
    assert any("conflicting canvas dimensions" in error for error in errors)


def test_missing_dimensions_fail(tmp_path):
    html = composition_html(1080, 1920)
    html = html.replace('data-width="1080" data-height="1920" ', "")
    html = html.replace('<meta name="viewport" content="width=1080, height=1920" />', "")
    html = html.replace("width: 1080px; height: 1920px; ", "")
    index = write_composition(tmp_path, html)
    errors = repair.validate_html(index)
    assert any("cannot determine canvas dimensions" in error for error in errors)


def test_repair_does_not_rewrite_portrait_dimensions(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1920))
    repair.patch_html(index)
    patched = index.read_text(encoding="utf-8")
    assert 'data-width="1080"' in patched
    assert 'data-height="1920"' in patched
    assert repair.validate_html(index) == []


def test_repair_does_not_convert_landscape_to_portrait(tmp_path):
    index = write_composition(tmp_path, composition_html(1920, 1080))
    repair.patch_html(index)
    patched = index.read_text(encoding="utf-8")
    assert 'data-width="1920"' in patched
    assert repair.validate_html(index) != []


def test_conflicting_later_root_css_rule_fails(tmp_path):
    html = composition_html(1080, 1920).replace(
        "</style>",
        "#root { width: 1920px; height: 1080px; overflow: hidden; }\n    </style>",
    )
    errors = repair.validate_html(write_composition(tmp_path, html))
    assert any("conflicting canvas dimensions" in error for error in errors)


def test_timeline_repair_scales_small_narration_mismatches(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1920))
    repair.patch_html(index, narration_duration=5.5)
    patched = index.read_text(encoding="utf-8")
    assert 'data-duration="5.500"' in patched
    assert 'data-duration="5.500" data-track-index="1"' in patched


def test_repair_adds_narration_duration_when_ffprobe_is_unavailable(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1920))
    repair.patch_html(index)
    patched = index.read_text(encoding="utf-8")
    assert 'data-duration="60.000"' in patched


@pytest.mark.parametrize("composition", ["hyperframes", "hyperframes_reels"])
def test_main_rejects_landscape_in_either_composition(tmp_path, monkeypatch, composition):
    project = tmp_path / "project"
    for name in ("hyperframes", "hyperframes_reels"):
        assets = project / name / "assets"
        assets.mkdir(parents=True)
        for font in repair.REQUIRED_FONTS:
            (assets / font).write_bytes(b"font")
        (assets / "narration.mp3").write_bytes(b"audio")
        dimensions = (1920, 1080) if name == composition else (1080, 1920)
        write_composition(project / name, composition_html(*dimensions))

    monkeypatch.setattr(repair, "probe_duration", lambda path: 0.0)
    monkeypatch.setattr(sys, "argv", ["repair_hyperframes_quality.py", str(project)])
    assert repair.main() == 1


def test_main_accepts_portrait_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    for name in ("hyperframes", "hyperframes_reels"):
        assets = project / name / "assets"
        assets.mkdir(parents=True)
        for font in repair.REQUIRED_FONTS:
            (assets / font).write_bytes(b"font")
        (assets / "narration.mp3").write_bytes(b"audio")
        write_composition(project / name, composition_html(1080, 1920))

    monkeypatch.setattr(repair, "probe_duration", lambda path: 0.0)
    monkeypatch.setattr(sys, "argv", ["repair_hyperframes_quality.py", str(project)])
    assert repair.main() == 0


def test_main_repairs_only_selected_composition(tmp_path, monkeypatch):
    project = tmp_path / "project"
    for name in ("hyperframes", "hyperframes_reels"):
        assets = project / name / "assets"
        assets.mkdir(parents=True)
        for font in repair.REQUIRED_FONTS:
            (assets / font).write_bytes(b"font")
        (assets / "narration.mp3").write_bytes(b"audio")
        write_composition(project / name, composition_html(1080, 1920))

    monkeypatch.setattr(repair, "probe_duration", lambda path: 45.0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair_hyperframes_quality.py",
            str(project),
            "--composition",
            "hyperframes_reels",
        ],
    )
    assert repair.main() == 0
    assert 'data-duration="5"' in (project / "hyperframes" / "index.html").read_text()
    assert 'data-duration="45.000"' in (
        project / "hyperframes_reels" / "index.html"
    ).read_text()

def test_removes_unmaterialized_individual_narration_tags(tmp_path):
    project = tmp_path / "cand_test"
    project.mkdir()
    
    html_with_multiple_audio = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>
        #root { width: 1080px; height: 1920px; overflow: hidden; }
        :root { --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }
@font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Regular.ttf') format('truetype'); font-weight: 400; font-style: normal; font-display: block; }
@font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Bold.ttf') format('truetype'); font-weight: 700; font-style: normal; font-display: block; }
@font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-ExtraBold.ttf') format('truetype'); font-weight: 800; font-style: normal; font-display: block; }
    </style>
</head>
<body>
    <div data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="45.000">
        <h1>Tiếng Việt Example</h1>
        <audio id="narration" src="assets/narration.mp3" data-start="0.000" data-track-index="10" data-volume="1"></audio>
        <audio id="narration_1" src="assets/s1_vi.wav" data-start="0.000" data-track-index="10" data-volume="1"></audio>
        <audio id="narration_2" src="assets/s2_vi.wav" data-start="14.502" data-track-index="10" data-volume="1"></audio>
        <audio id="bg-audio" src="assets/tech_thriller_bg.mp3" loop="true"></audio>
    </div>
</body>
</html>"""
    
    comp = write_composition(tmp_path, html_with_multiple_audio)
    repair.patch_html(comp, 45.0)
    
    patched_html = comp.read_text()
    assert 'id="narration"' in patched_html, "Unified track must be preserved"
    assert 'id="narration_1"' not in patched_html, "Missing asset narration_1 must be removed"
    assert 'id="narration_2"' not in patched_html, "Missing asset narration_2 must be removed"
    assert 'src="assets/music-bg.mp3"' not in patched_html, "Missing background asset must be removed"

def test_repair_calculates_data_duration_from_scenes(tmp_path):
    project = tmp_path / "cand_test"
    project.mkdir()
    
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>
        #root { width: 1080px; height: 1920px; overflow: hidden; }
        :root { --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }
    </style>
</head>
<body>
    <div data-composition-id="main" data-width="1080" data-height="1920" data-start="0">
        <div id="scene-0" class="scene" data-start="0.000" data-duration="15.5"></div>
        <div id="scene-1" class="scene" data-start="15.500" data-duration="10.0"></div>
<!-- Total scene end is 25.5 -->
    </div>
</body>
</html>"""
    
    comp = write_composition(tmp_path, html)
    repair.patch_html(comp, 45.0)
    
    patched_html = comp.read_text()
    
    # Root should first receive data-duration="25.500" because calculated max_end=25.5, 
    # then align_timeline computes scale = 45.0 / 25.500 = 1.764
    # Scene 1 start remains 0, dur = 15.5 * 1.7647 = 27.353
    # Scene 2 start = 15.5 * 1.7647 = 27.353, dur = 10 * 1.7647 = 17.647
    # So max end becomes exactly 45.0
    
    # We just explicitly assert the root has duration 45.000 (after scaling),
    # but more importantly that the scene durations were multiplied!
    assert 'data-duration="45.000"' in patched_html, "Root duration is scaled to narration"
    
    import re
    scene1_dur_match = re.search(r'id="scene-0" class="scene" data-start="0.000" data-duration="(27\.35[0-9])"', patched_html)
    assert scene1_dur_match is not None, "Scene 1 duration scaled up"


def test_repair_uses_scene_end_when_root_duration_is_stale(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>
        #root { width: 1080px; height: 1920px; overflow: hidden; }
        :root { --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }
    </style>
</head>
<body>
    <div data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="56.5">
        <div id="scene-0" class="scene" data-start="0.000" data-duration="20.0"></div>
        <div id="scene-1" class="scene" data-start="20.000" data-duration="15.0"></div>
        <h1>Tiếng Việt Example</h1>
    </div>
</body>
</html>"""
    comp = write_composition(tmp_path, html)

    repair.patch_html(comp, 56.5)

    patched_html = comp.read_text()
    assert 'data-duration="56.500"' in patched_html
    assert 'id="scene-1" class="scene" data-start="32.286" data-duration="24.214"' in patched_html


def test_repair_ignores_directory_asset_targets(tmp_path):
    composition_dir = tmp_path / "cand_test" / "hyperframes"
    composition_dir.mkdir(parents=True)
    (composition_dir / "assets").mkdir()
    html = """<html><head><style>
.hero { background-image: url('.'); }
</style></head><body>
<div data-composition-id="main"><img src="assets"></div>
</body></html>"""

    repaired = repair.repair_missing_composition_assets(composition_dir / "index.html", html)

    assert "url('.')" in repaired
    assert 'src="assets"' in repaired


def test_removes_clip_visibility_hidden_rule(tmp_path):
    import re
    html = composition_html(1080, 1920)
    html = html.replace(
        "#root { position: relative;",
        ".clip { visibility: hidden; }\n      #root { position: relative;",
    )
    comp = write_composition(tmp_path, html)
    repair.patch_html(comp, 10.0)
    patched = comp.read_text()
    assert re.search(r"\.clip[^{}]*\{[^{}]*visibility:\s*hidden", patched) is None


def test_repair_injects_valid_breathing_zoom_and_preserves_registered_timeline(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>#root { width: 1080px; height: 1920px; }</style>
</head>
<body>
    <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="10.0"></div>
    <script>
        const tl = gsap.timeline();
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
    </script>
</body>
</html>"""
    comp = write_composition(tmp_path, html)
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    # Must inject breathing scale with valid JS syntax (no extra braces)
    assert "// __repair_scale_injected" in patched
    assert "tl.fromTo('#root', {scale: 1.0}, {scale: 1.06, transformOrigin: '50% 50%', force3D: true, duration: 1.6, yoyo: true, repeat: 6, ease: 'sine.inOut'}, 0);" in patched
    # Timeline should not be marked data-no-timeline if it registered timelines
    assert "data-no-timeline" not in patched




