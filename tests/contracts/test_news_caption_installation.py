import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "news_caption_hyperframes_qa.html.fixture"
INSTALLER = ROOT / "scripts" / "install_news_captions.py"
spec = importlib.util.spec_from_file_location("news_caption_installer", INSTALLER)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def _inputs(tmp_path, words=None):
    composition = tmp_path / "index.html"
    composition.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"fixed audio bytes")
    timing_path = tmp_path / "word_timestamps.json"
    timing_path.write_text(json.dumps({
        "timing_source": "asr",
        "timing_verified": False,
        "audio_sha256": hashlib.sha256(b"fixed audio bytes").hexdigest(),
        "duration_seconds": 10,
        "word_timestamps": words or [
            {"word": "Xin", "start": 0.2, "end": 0.5},
            {"word": "chào", "start": 0.6, "end": 0.9},
            {"word": "bạn", "start": 1.0, "end": 1.3},
            {"word": "Việt", "start": 1.7, "end": 2.0},
        ],
    }), encoding="utf-8")
    return composition, audio, timing_path


def test_installs_escaped_timed_clips_without_changing_timeline_or_duration(tmp_path):
    composition, audio, timings = _inputs(tmp_path, [
        {"word": "Xin <b>chào", "start": 0.2, "end": 0.5},
        {"word": "bạn & tôi", "start": 0.6, "end": 0.9},
    ])
    original = composition.read_text(encoding="utf-8")

    assert installer.install_captions(composition, audio, timings) == 1
    updated = composition.read_text(encoding="utf-8")
    assert 'id="om-asr-caption-1"' in updated
    assert 'class="clip om-asr-caption"' in updated
    assert 'data-start="0.200" data-duration="0.700" data-track-index="1"' in updated
    assert "Xin &lt;b&gt;chào bạn &amp; tôi" in updated
    assert "data-duration=\"10\"" in updated
    assert "window.__timelines['main'] = tl" in updated
    assert "#main { position: relative; }" in updated
    assert '[data-composition-id="main"]' not in updated
    assert "setTimeout" not in updated
    assert "onUpdate" not in updated
    assert updated.count(installer.BEGIN_MARKER) == 1
    assert original.split("<script>")[1] in updated


def test_retry_replaces_exactly_one_owned_caption_block(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    assert installer.install_captions(composition, audio, timings) == 2
    first = composition.read_text(encoding="utf-8")

    data = json.loads(timings.read_text(encoding="utf-8"))
    data["word_timestamps"][0]["start"] = 0.35
    timings.write_text(json.dumps(data), encoding="utf-8")
    assert installer.install_captions(composition, audio, timings) == 2

    updated = composition.read_text(encoding="utf-8")
    assert updated.count(installer.BEGIN_MARKER) == 1
    assert updated.count(installer.END_MARKER) == 1
    assert updated.count('id="om-asr-caption-1"') == 1
    assert 'data-start="0.350"' in updated
    assert 'data-start="0.200"' not in updated
    old_start = first.index(installer.BEGIN_MARKER)
    old_end = first.index(installer.END_MARKER) + len(installer.END_MARKER)
    new_start = updated.index(installer.BEGIN_MARKER)
    new_end = updated.index(installer.END_MARKER) + len(installer.END_MARKER)
    assert updated[:new_start] == first[:old_start]
    assert updated[new_end:] == first[old_end:]


def test_malformed_owned_caption_block_fails_without_overwriting_html(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    installer.install_captions(composition, audio, timings)
    source = composition.read_text(encoding="utf-8").replace(
        'data-track-index="1"', 'data-track-index="invalid"', 1
    )
    composition.write_text(source, encoding="utf-8")
    before = composition.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="malformed OpenMontage ASR caption block"):
        installer.install_captions(composition, audio, timings)
    assert composition.read_text(encoding="utf-8") == before


def test_unpaired_owned_caption_marker_fails_without_overwriting_html(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = composition.read_text(encoding="utf-8") + installer.BEGIN_MARKER
    composition.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="expected one begin and one end"):
        installer.install_captions(composition, audio, timings)
    assert composition.read_text(encoding="utf-8") == source


def test_strict_repair_failure_is_not_hidden_by_caption_installation_loop():
    pipeline = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(encoding="utf-8")
    repair = '"$PY" "$ROOT/scripts/repair_hyperframes_quality.py" "$project_root" --strict || return 1'
    assert repair in pipeline
    assert pipeline.index(repair) < pipeline.index('"$ROOT/scripts/install_news_captions.py"')


def test_rejects_audio_hash_mismatch_without_modifying_composition(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    data = json.loads(timings.read_text(encoding="utf-8"))
    data["audio_sha256"] = "0" * 64
    timings.write_text(json.dumps(data), encoding="utf-8")
    before = composition.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        installer.install_captions(composition, audio, timings)
    assert composition.read_text(encoding="utf-8") == before


def test_rejects_unsupported_composition_without_modifying_it(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = composition.read_text(encoding="utf-8").replace('data-composition-id="main"', 'data-composition-id="other"')
    composition.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one main"):
        installer.install_captions(composition, audio, timings)
    assert installer.BEGIN_MARKER not in composition.read_text(encoding="utf-8")


def test_rejects_nonzero_composition_root_start(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = composition.read_text(encoding="utf-8").replace(
        'data-duration="10" data-start="0"',
        'data-duration="10" data-start="0.1"',
        1,
    )
    composition.write_text(source, encoding="utf-8")
    before = composition.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="must start at zero"):
        installer.install_captions(composition, audio, timings)
    assert composition.read_text(encoding="utf-8") == before


def test_rejects_root_without_main_id(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = composition.read_text(encoding="utf-8").replace('id="main"', 'id="other"', 1)
    composition.write_text(source, encoding="utf-8")
    before = composition.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match='must use id="main"'):
        installer.install_captions(composition, audio, timings)
    assert composition.read_text(encoding="utf-8") == before


def test_accepts_root_with_stage_id(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = composition.read_text(encoding="utf-8").replace('id="main"', 'id="stage"', 1)
    composition.write_text(source, encoding="utf-8")

    assert installer.install_captions(composition, audio, timings) == 2
    updated = composition.read_text(encoding="utf-8")
    assert "#stage { position: relative; }" in updated
    assert 'class="clip om-asr-caption"' in updated


def test_accepts_root_with_root_id_and_dot_notation_timeline(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = (
        composition.read_text(encoding="utf-8")
        .replace('id="main"', 'id="root"', 1)
        .replace("window.__timelines['main'] = tl", "window.__timelines.main = tl", 1)
    )
    composition.write_text(source, encoding="utf-8")

    assert installer.install_captions(composition, audio, timings) == 2
    updated = composition.read_text(encoding="utf-8")
    assert "#root { position: relative; }" in updated
    assert 'class="clip om-asr-caption"' in updated



def test_rejects_existing_caption_markup_instead_of_stacking_captions(tmp_path):
    composition, audio, timings = _inputs(tmp_path)
    source = composition.read_text(encoding="utf-8").replace(
        "CAPTION ADAPTER QA", '<span class="caption">legacy footer text</span>'
    )
    composition.write_text(source, encoding="utf-8")
    before = composition.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="existing caption markup"):
        installer.install_captions(composition, audio, timings)
    assert composition.read_text(encoding="utf-8") == before


def test_rejects_caption_timing_beyond_render_duration(tmp_path):
    composition, audio, timings = _inputs(tmp_path, [
        {"word": "trễ", "start": 9.9, "end": 10.1},
    ])

    with pytest.raises(ValueError, match="within composition duration"):
        installer.install_captions(composition, audio, timings)
