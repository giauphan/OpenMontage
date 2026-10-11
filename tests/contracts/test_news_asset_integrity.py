from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))

from scripts.repair_hyperframes_quality import patch_html, repair_missing_composition_assets

PIPELINE = ROOT / "scripts" / "run_daily_news_pipeline.sh"


def composition(tmp_path: Path) -> tuple[Path, Path]:
    comp_dir = tmp_path / "project" / "hyperframes"
    comp_dir.mkdir(parents=True)
    index = comp_dir / "index.html"
    index.write_text("<html></html>", encoding="utf-8")
    return comp_dir, index


def test_same_basename_elsewhere_is_not_copied_for_image_or_css(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    unrelated = tmp_path / "project" / "other" / "hero.png"
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"unrelated media")

    for markup in (
        '<img src="assets/hero.png">',
        '<style>.hero { background-image: url("assets/hero.png"); }</style>',
    ):
        with pytest.raises(ValueError, match="missing or empty local"):
            repair_missing_composition_assets(index, markup)
        assert not (comp_dir / "assets" / "hero.png").exists()
        assert unrelated.read_bytes() == b"unrelated media"


def test_missing_image_and_css_assets_fail_without_mutating_assets(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    assets = comp_dir / "assets"
    assets.mkdir()
    existing = assets / "unrelated.bin"
    existing.write_bytes(b"keep")
    original_html = '<img src="assets/missing.png"><style>.x{background:url(assets/missing.jpg)}</style>'

    with pytest.raises(ValueError, match="missing or empty local image"):
        repair_missing_composition_assets(index, original_html)

    assert not (assets / "missing.svg").exists()
    assert not (assets / "missing.png").exists()
    assert existing.read_bytes() == b"keep"
    assert original_html == '<img src="assets/missing.png"><style>.x{background:url(assets/missing.jpg)}</style>'


def test_patch_html_failure_preserves_original_html_and_assets(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    assets = comp_dir / "assets"
    assets.mkdir()
    retained = assets / "retained.bin"
    retained.write_bytes(b"keep")
    original = '''<!doctype html><html><head><style>
#root { position: relative; width: 1080px; height: 1920px; overflow: hidden; }
:root { --font-heading: 'BeVietnamPro', Arial, sans-serif; --font-body: 'BeVietnamPro', Arial, sans-serif; }
</style></head><body>
<div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-start="0" data-duration="10">
<img src="assets/missing.png">
</div></body></html>'''
    index.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="missing or empty local image"):
        patch_html(index, narration_duration=10)

    assert index.read_text(encoding="utf-8") == original
    assert retained.read_bytes() == b"keep"
    assert not (assets / "missing.png").exists()
    assert not (assets / "missing.svg").exists()


def test_css_missing_asset_raises_actionable_error(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    with pytest.raises(ValueError, match=r"missing or empty local CSS URL asset 'assets/background.webp'.*provide the intended file"):
        repair_missing_composition_assets(index, '<style>.x{background:url(assets/background.webp)}</style>')
    assert not (comp_dir / "assets" / "background.svg").exists()


def test_valid_local_assets_and_external_data_fragment_refs_are_unchanged_and_idempotent(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    (comp_dir / "assets").mkdir()
    (comp_dir / "assets" / "hero.png").write_bytes(b"image")
    (comp_dir / "assets" / "texture one.png").write_bytes(b"texture")
    (comp_dir / "assets" / "rock&roll.png").write_bytes(b"entity filename")
    markup = '''<img src="assets/hero.png?cache=1#preview">
<style>.x { background: url("assets/texture%20one.png"); }</style>
<img src="assets/rock&amp;roll.png">
<img src="data:image/png;base64,AAAA"><img src="https://example.test/remote.png">
<img src="#inline-fragment"><style>.y{background:url(#gradient)}</style>
<style>.remote{background:url(//cdn.example.test/a.png)}</style>'''

    first = repair_missing_composition_assets(index, markup)
    second = repair_missing_composition_assets(index, first)

    assert first == markup
    assert second == markup
    assert sorted(p.name for p in (comp_dir / "assets").iterdir()) == ["hero.png", "rock&roll.png", "texture one.png"]


def test_existing_directory_ignore_behavior_is_preserved(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    (comp_dir / "assets").mkdir()
    markup = '<img src="assets"><style>.x{background:url(.)}</style>'
    assert repair_missing_composition_assets(index, markup) == markup


@pytest.mark.parametrize("reference", ["../outside.png", "/tmp/outside.png", "C:\\temp\\outside.png"])
def test_unsafe_absolute_or_escaping_paths_are_rejected(tmp_path: Path, reference: str) -> None:
    _, index = composition(tmp_path)
    with pytest.raises(ValueError, match="relative to the composition|escapes the composition"):
        repair_missing_composition_assets(index, f'<img src="{reference}">')


def test_unsupported_protocols_and_ambiguous_css_entities_are_rejected(tmp_path: Path) -> None:
    _, index = composition(tmp_path)
    with pytest.raises(ValueError, match="unsupported image asset URL scheme 'ftp'"):
        repair_missing_composition_assets(index, '<img src="ftp://example.test/image.png">')
    with pytest.raises(ValueError, match="HTML-entity-encoded CSS URL is ambiguous"):
        repair_missing_composition_assets(index, '<style>.x{background:url(assets/rock&amp;roll.png)}</style>')


def test_symlink_asset_reference_is_rejected(tmp_path: Path) -> None:
    comp_dir, index = composition(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    try:
        (comp_dir / "linked.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    with pytest.raises(ValueError, match="symbolic link"):
        repair_missing_composition_assets(index, '<img src="linked.png">')


def _background_music_function() -> str:
    source = PIPELINE.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^validate_project_background_music\(\) \{\n.*?^\}\n", source)
    assert match is not None, "background music validation helper must remain extractable for offline tests"
    return match.group(0)


def _run_music_validation(
    tmp_path: Path,
    *,
    music: bytes | None,
    duration: str,
    probe_status: int = 0,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    project = tmp_path / "project"
    assets = project / "assets"
    assets.mkdir(parents=True)
    narration = assets / "narration.mp3"
    narration.write_bytes(b"narration")
    music_path = assets / "music-bg.mp3"
    if music is not None:
        music_path.write_bytes(music)
    qa_fixture = tmp_path / "tests" / "qa" / "output" / "music_calm.mp3"
    qa_fixture.parent.mkdir(parents=True)
    qa_fixture.write_bytes(b"QA fixture only")

    ffprobe = tmp_path / "ffprobe"
    ffprobe.write_text("#!/bin/sh\nprintf '%s' \"$TEST_DURATION\"\nexit \"$TEST_PROBE_STATUS\"\n", encoding="utf-8")
    ffprobe.chmod(0o755)
    command = (
        _background_music_function()
        + '\nvalidate_project_background_music "$PROJECT_ROOT" "test-project"\n'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PROJECT_ROOT": str(project),
            "FFPROBE_BIN": str(ffprobe),
            "TEST_DURATION": duration,
            "TEST_PROBE_STATUS": str(probe_status),
        },
        check=False,
    )
    assert qa_fixture.read_bytes() == b"QA fixture only"
    return result, music_path


def test_missing_project_music_fails_without_copying_qa_fixture(tmp_path: Path) -> None:
    result, music_path = _run_music_validation(tmp_path, music=None, duration="10")
    assert result.returncode != 0
    assert "background music asset missing" in result.stderr
    assert not music_path.exists()


def test_invalid_project_music_fails_and_preserves_supplied_bytes(tmp_path: Path) -> None:
    supplied = b"short supplied music"
    result, music_path = _run_music_validation(tmp_path, music=supplied, duration="4")
    assert result.returncode != 0
    assert "single finite numeric value greater than 5s" in result.stderr
    assert music_path.read_bytes() == supplied


@pytest.mark.parametrize("duration", ["NaN", "N/A", "", "12\n13", "Infinity", "1e999"])
def test_non_numeric_non_finite_or_multiline_duration_fails_and_preserves_music(
    tmp_path: Path, duration: str
) -> None:
    supplied = b"unchanged supplied music"
    result, music_path = _run_music_validation(tmp_path, music=supplied, duration=duration)
    assert result.returncode != 0
    assert "single finite numeric value greater than 5s" in result.stderr
    assert music_path.read_bytes() == supplied


def test_failed_ffprobe_fails_and_preserves_music(tmp_path: Path) -> None:
    supplied = b"unchanged supplied music"
    result, music_path = _run_music_validation(tmp_path, music=supplied, duration="12", probe_status=1)
    assert result.returncode != 0
    assert "could not probe background music duration" in result.stderr
    assert music_path.read_bytes() == supplied


def test_identical_narration_and_music_fails_without_mutating_music(tmp_path: Path) -> None:
    project = tmp_path / "project"
    assets = project / "assets"
    assets.mkdir(parents=True)
    narration = assets / "narration.mp3"
    narration.write_bytes(b"narration")
    music = assets / "music-bg.mp3"
    music.write_bytes(b"narration")
    ffprobe = tmp_path / "ffprobe"
    ffprobe.write_text("#!/bin/sh\nprintf '12'\n", encoding="utf-8")
    ffprobe.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", _background_music_function() + '\nvalidate_project_background_music "$PROJECT_ROOT" "test-project"\n'],
        capture_output=True,
        text=True,
        env={**os.environ, "PROJECT_ROOT": str(project), "FFPROBE_BIN": str(ffprobe)},
        check=False,
    )
    assert result.returncode != 0
    assert "byte-identical to narration" in result.stderr
    assert music.read_bytes() == b"narration"


def test_valid_project_music_is_preserved(tmp_path: Path) -> None:
    supplied = b"approved project music"
    result, music_path = _run_music_validation(tmp_path, music=supplied, duration="12")
    assert result.returncode == 0, result.stderr
    assert music_path.read_bytes() == supplied
