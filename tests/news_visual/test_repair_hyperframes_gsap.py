"""Tests for GSAP timeline repair and continuous scene drift injection."""

from pathlib import Path
import json
import pytest

from scripts.repair_hyperframes_gsap import repair_gsap_timeline


def test_fix_malformed_tl_to(tmp_path: Path):
    html = """
    <html>
    <body>
      <div id="stage">
        <div id="scene-1" class="scene"></div>
      </div>
      <script>
        const tl = gsap.timeline({ paused: true });
        tl.to('#scene-1', { opacity: 1, scale: 1.035, y: -8 }, { duration: 0.6, delay: 0.2, ease: 'back.out(1.4)' }, 0);
        window.__timelines['main'] = tl;
      </script>
    </body>
    </html>
    """
    file_path = tmp_path / "hyperframes" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(html, encoding="utf-8")

    fixed = repair_gsap_timeline(html, file_path, narration_duration=10.0)
    assert "duration: 0.6" in fixed
    assert "tl.to('#scene-1', {opacity: 1, duration: 0.6" in fixed
    assert "tl.fromTo('#scene-1', { scale: 1.0, y: 0 }, { scale: 1.035, y: -8" in fixed


def test_inject_continuous_drift_with_script_json(tmp_path: Path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    script_data = {
        "sections": [
            {"id": "sec-1", "start_seconds": 0.0, "end_seconds": 12.0},
            {"id": "sec-2", "start_seconds": 12.0, "end_seconds": 24.0},
        ]
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script_data), encoding="utf-8")

    html = """
    <html>
    <body>
      <div id="stage">
        <div id="scene-1" class="scene"></div>
        <div id="scene-2" class="scene"></div>
      </div>
      <script>
        window.__timelines = window.__timelines || {};
        const tl = gsap.timeline({ paused: true });
        tl.set('#scene-1', { opacity: 1 }, 0);
        tl.set('#scene-2', { opacity: 1 }, 12.0);
        window.__timelines['main'] = tl;
      </script>
    </body>
    </html>
    """
    file_path = tmp_path / "hyperframes" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(html, encoding="utf-8")

    fixed = repair_gsap_timeline(html, file_path, narration_duration=24.0)
    assert "tl.fromTo('#scene-1', { scale: 1.0, y: 0 }, { scale: 1.035, y: -8, duration: 12.000, ease: 'none' }, 0.000);" in fixed
    assert "tl.fromTo('#scene-2', { scale: 1.0, y: 0 }, { scale: 1.035, y: -8, duration: 12.000, ease: 'none' }, 12.000);" in fixed


def test_skip_when_drift_already_present(tmp_path: Path):
    html = """
    <html>
    <body>
      <div id="stage">
        <div id="scene-1" class="scene"></div>
      </div>
      <script>
        const tl = gsap.timeline({ paused: true });
        tl.fromTo('#scene-1', { scale: 1.0, y: 0 }, { scale: 1.035, y: -8, duration: 11.5, ease: 'none' }, 0);
        window.__timelines['main'] = tl;
      </script>
    </body>
    </html>
    """
    file_path = tmp_path / "hyperframes" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(html, encoding="utf-8")

    fixed = repair_gsap_timeline(html, file_path, narration_duration=11.5)
    # Count occurrences of fromTo('#scene-1'
    assert fixed.count("fromTo('#scene-1'") == 1


def test_fix_malformed_tl_to_complex_selectors(tmp_path: Path):
    html = """
    <html>
    <body>
      <div id="stage"><div id="scene-1" class="scene"></div></div>
      <script>
        const tl = gsap.timeline({ paused: true });
        tl.to('#scene-1 .card', { opacity: 1 }, { duration: 0.5, ease: 'power2.out' }, 2);
        tl.to(".a, .b", { x: 100 }, { duration: 1.0 });
        tl.to(cardEl, { y: 50 }, { duration: 0.8 });
        window.__timelines['main'] = tl;
      </script>
    </body>
    </html>
    """
    file_path = tmp_path / "hyperframes" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(html, encoding="utf-8")

    fixed = repair_gsap_timeline(html, file_path, narration_duration=10.0)
    assert "tl.to('#scene-1 .card', {opacity: 1, duration: 0.5, ease: 'power2.out'}, 2)" in fixed
    assert 'tl.to(".a, .b", {x: 100, duration: 1.0})' in fixed
    assert "tl.to(cardEl, {y: 50, duration: 0.8})" in fixed


def test_fix_malformed_tl_to_nested_position_and_chained_call(tmp_path: Path):
    html = """
    <html>
    <body>
      <div id="stage"><div id="scene-1" class="scene"></div></div>
      <script>
        const tl = gsap.timeline({ paused: true });
        tl.to(targetEl, { opacity: 1 }, { duration: 0.4 }, getPosition());
        tl.to(a, { x: 1 }, 0).to(b, { y: 2 }, 1);
        window.__timelines['main'] = tl;
      </script>
    </body>
    </html>
    """
    file_path = tmp_path / "hyperframes" / "index.html"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(html, encoding="utf-8")

    fixed = repair_gsap_timeline(html, file_path, narration_duration=10.0)
    assert "tl.to(targetEl, {opacity: 1, duration: 0.4}, getPosition())" in fixed
    assert "tl.to(a, { x: 1 }, 0).to(b, { y: 2 }, 1)" in fixed
