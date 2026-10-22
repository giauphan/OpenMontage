import pytest
import json
from pathlib import Path
from lib.artifact_paths import (
    resolve_project_locale,
    resolve_script_path,
    resolve_render_path,
    resolve_narration_text_path,
    resolve_captions_path,
    is_english_locale,
)

def test_resolve_project_locale_en_us(tmp_path: Path):
    project_json = tmp_path / "project.json"
    project_json.write_text(json.dumps({"locale": "en-US"}), encoding="utf-8")
    assert resolve_project_locale(tmp_path) == "en-US"
    assert is_english_locale("en-US") is True

def test_resolve_project_locale_vi_vn_default(tmp_path: Path):
    assert resolve_project_locale(tmp_path) == "vi-VN"
    assert is_english_locale("vi-VN") is False

def test_resolve_script_path(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    
    # en-US resolves script_en_US.json
    en_script = resolve_script_path(tmp_path, locale="en-US")
    assert en_script.name == "script_en_US.json"

    # vi-VN resolves script_vi.json
    vi_script = resolve_script_path(tmp_path, locale="vi-VN")
    assert vi_script.name == "script_vi.json"

def test_no_permissive_fallback_from_en_to_vi(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    vi_file = artifacts / "script_vi.json"
    vi_file.write_text("{}", encoding="utf-8")

    # If project is en-US and requires existing file, must not fallback to script_vi.json!
    with pytest.raises(FileNotFoundError):
        resolve_script_path(tmp_path, locale="en-US", must_exist=True)

def test_resolve_render_paths(tmp_path: Path):
    # en-US shorts
    p = resolve_render_path(tmp_path, format_type="short", locale="en-US")
    assert p.name == "final_short_en_US_9x16.mp4"

    # en-US longform
    p_long = resolve_render_path(tmp_path, format_type="longform", locale="en-US")
    assert p_long.name == "final_long_en_US_16x9.mp4"

    # vi-VN legacy reels
    p_vi = resolve_render_path(tmp_path, format_type="short", locale="vi-VN")
    assert p_vi.name == "final_reels_vi_9x16.mp4"

    # vi-VN full
    p_vi_full = resolve_render_path(tmp_path, format_type="longform", locale="vi-VN")
    assert p_vi_full.name == "final_full_vi_9x16.mp4"
