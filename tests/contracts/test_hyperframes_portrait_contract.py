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


def test_repair_preserves_authored_timing_when_narration_duration_differs(tmp_path):
    index = write_composition(tmp_path, composition_html(1080, 1920))
    repair.patch_html(index, narration_duration=5.5)
    patched = index.read_text(encoding="utf-8")
    assert '<section data-start="0" data-duration="5" data-track-index="1">' in patched


def test_repair_preserves_authored_root_duration(tmp_path):
    html = composition_html(1080, 1920).replace('data-duration="5"', 'data-duration="5"', 1)
    index = write_composition(tmp_path, html)
    repair.patch_html(index)
    assert 'data-duration="5"' in index.read_text(encoding="utf-8")


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
    assert 'data-duration="5"' in (
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

def test_repair_uses_scene_end_only_when_root_duration_is_missing(tmp_path):
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
    
    assert 'data-duration="25.500"' in patched_html
    assert 'id="scene-0" class="scene" data-start="0.000" data-duration="15.5"' in patched_html
    assert 'id="scene-1" class="scene" data-start="15.500" data-duration="10.0"' in patched_html


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
    assert 'data-duration="56.5"' in patched_html
    assert 'id="scene-1" class="scene" data-start="20.000" data-duration="15.0"' in patched_html


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


def test_repair_preserves_authored_clip_visibility_rule(tmp_path):
    import re
    html = composition_html(1080, 1920)
    html = html.replace(
        "#root { position: relative;",
        ".clip { visibility: hidden; }\n      #root { position: relative;",
    )
    comp = write_composition(tmp_path, html)
    repair.patch_html(comp, 10.0)
    patched = comp.read_text()
    assert re.search(r"\.clip[^{}]*\{[^{}]*visibility:\s*hidden", patched) is not None


def test_css_class_name_does_not_suppress_missing_dom_elements_or_inject_motion(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>#root { width: 1080px; height: 1920px; } .hf-grid-overlay { position: absolute; }</style>
</head>
<body>
    <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="10.0"></div>
    <script>
        const tl = gsap.timeline({ paused: true });
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
    </script>
</body>
</html>"""
    comp = write_composition(tmp_path, html)
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    dom = repair._CompositionDOM(patched)
    assert not any("hf-grid-overlay" in (attrs.get("class") or "").split() for _, attrs, _ in dom.nodes)
    assert not any("hf-motion-beam" in (attrs.get("class") or "").split() for _, attrs, _ in dom.nodes)
    assert ".hf-grid-overlay" in patched
    assert "hf-motion-beam" not in patched
    assert "data-no-timeline" not in patched
    repair.patch_html(comp, 10.0, strict=True)
    assert comp.read_text() == patched


def test_repair_promotes_stage_div_to_composition_root(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>#stage { width: 1080px; height: 1920px; overflow: hidden; }</style>
</head>
<body>
    <div id="stage"><section class="scene">Tiếng Việt</section></div>
</body>
</html>"""
    comp = write_composition(tmp_path, html)

    repair.patch_html(comp, 42.0, strict=True)

    patched = comp.read_text()
    assert '<div data-start="0" data-duration="42.000" data-height="1920" data-width="1080" data-composition-id="main" id="stage"' in patched


def test_strict_repair_preserves_css_semicolons_and_js_object_commas(tmp_path):
    html = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=1080, height=1920">
    <style>
        #root { width: 1080px; height: 1920px; }
        .scene { opacity: 0; visibility: hidden; }
    </style>
</head>
<body>
    <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="10.0"></div>
    <script>
        const tl = gsap.timeline({ paused: true });
        tl.set('#root', { opacity: 0, visibility: 'hidden' });
        window.__timelines = window.__timelines || {};
        window.__timelines['main'] = tl;
    </script>
</body>
</html>"""
    comp = write_composition(tmp_path, html)
    repair.patch_html(comp, 10.0, strict=True)
    patched = comp.read_text()

    assert ".scene { opacity: 0; visibility: hidden; }" in patched
    assert "{ opacity: 0, visibility: 'hidden' }" in patched
    assert "opacity: 1;," not in patched


def test_future_scene_visibility_and_timing_are_preserved(tmp_path):
    html = composition_html(1080, 1920).replace(
        "</style>", ".scene.future { opacity: 0; visibility: hidden; }\n    </style>"
    ).replace(
        '<section data-start="0" data-duration="5" data-track-index="1">',
        '<section class="scene future" data-start="4" data-duration="1" data-track-index="1">',
    )
    index = write_composition(tmp_path, html)
    repair.patch_html(index, narration_duration=9.0, strict=True)
    patched = index.read_text(encoding="utf-8")
    assert ".scene.future { opacity: 0; visibility: hidden; }" in patched
    assert 'data-start="4" data-duration="1"' in patched


def test_infinite_repeat_fails_with_actionable_error(tmp_path):
    html = composition_html(1080, 1920).replace(
        "</body>", "<script>tl.to('.pulse', { opacity: 0.5, repeat: -1 });</script></body>"
    )
    index = write_composition(tmp_path, html)
    with pytest.raises(ValueError, match="infinite GSAP repeat.*finite registered timeline"):
        repair.patch_html(index)


def test_javascript_comments_and_string_literals_do_not_trigger_unsafe_pattern_checks(tmp_path):
    html = composition_html(1080, 1920).replace(
        "</body>", "<script>// gsap.to('.x', { repeat: -1 });\nconst note = 'repeat: -1 gsap.to('; </script></body>"
    )
    index = write_composition(tmp_path, html)
    repair.patch_html(index)


def test_data_no_timeline_root_is_allowed_without_gsap_registration(tmp_path):
    html = composition_html(1080, 1920).replace(
        'data-composition-id="main"', 'data-composition-id="main" data-no-timeline'
    )
    index = write_composition(tmp_path, html)
    repair.patch_html(index, strict=True)
    assert 'data-no-timeline' in index.read_text(encoding="utf-8")


def test_unpaused_gsap_timeline_fails_with_actionable_error(tmp_path):
    html = composition_html(1080, 1920).replace(
        "</body>", "<script>const tl = gsap.timeline();</script></body>"
    )
    index = write_composition(tmp_path, html)
    with pytest.raises(ValueError, match="timelines must be created with paused: true"):
        repair.patch_html(index)


def test_standalone_gsap_tween_fails_with_actionable_error(tmp_path):
    html = composition_html(1080, 1920).replace(
        "</body>", "<script>gsap.to('.scene', { opacity: 1, duration: 1 });</script></body>"
    )
    index = write_composition(tmp_path, html)
    with pytest.raises(ValueError, match="standalone gsap animation.*registered to the paused HyperFrames timeline"):
        repair.patch_html(index)
