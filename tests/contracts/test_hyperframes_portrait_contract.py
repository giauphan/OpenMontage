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
