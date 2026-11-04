"""Tests for metric period stripping and emoji-to-SVG sanitization in repair_hyperframes_quality."""

from __future__ import annotations

from pathlib import Path
from scripts.repair_hyperframes_quality import (
    _sanitize_emojis_to_vector_svg,
    _sanitize_metrics_and_symbols,
    patch_html,
)


def test_sanitize_metrics_and_symbols_removes_trailing_periods():
    html = """
    <div class="metric-value green" style="font-size:80px;">SOTA.</div>
    <div class="metric-value" style="color:#fbbf24;">Higher ↑.</div>
    <div class="metric-value accent">38.3% vs 33.3%.</div>
    <div class="flow-arrow">↓.</div>
    <div class="flow-arrow">→.</div>
    <span class="date-pill">NOV 4, 2026.</span>
    <div class="badge">AI AGENT // SCENE 1.</div>
    <h2>SpecPilot <span class="green">Surpasses.</span> EAGLE-2</h2>
    <h2>Joint <span class="highlight">Algorithm<br/>+ Systems.</span> Search</h2>
    <div class="flow-box">Define Search Space.</div>
    """
    cleaned = _sanitize_metrics_and_symbols(html)

    assert '<div class="metric-value green" style="font-size:80px;">SOTA</div>' in cleaned
    assert '<div class="metric-value" style="color:#fbbf24;">Higher ↑</div>' in cleaned
    assert '<div class="metric-value accent">38.3% vs 33.3%</div>' in cleaned
    assert '<div class="flow-arrow">↓</div>' in cleaned
    assert '<div class="flow-arrow">→</div>' in cleaned
    assert '<span class="date-pill">NOV 4, 2026</span>' in cleaned
    assert '<div class="badge">AI AGENT // SCENE 1</div>' in cleaned
    assert '<h2>SpecPilot <span class="green">Surpasses</span> EAGLE-2</h2>' in cleaned
    assert '<h2>Joint <span class="highlight">Algorithm<br/>+ Systems</span> Search</h2>' in cleaned
    assert '<div class="flow-box">Define Search Space</div>' in cleaned


def test_sanitize_emojis_converts_known_emojis_to_inline_svg():
    html = """
    <div class="flow-box">🔍 Define Search Space</div>
    <div class="flow-box">🤖 Auto Discovery</div>
    <div class="flow-box">🚀 New SOTA Deployed</div>
    <div class="flow-box">⚡ Optimal Config</div>
    """
    cleaned = _sanitize_emojis_to_vector_svg(html)

    assert "🔍" not in cleaned
    assert "🤖" not in cleaned
    assert "🚀" not in cleaned
    assert "<svg" in cleaned
    assert "circle cx=" in cleaned
    assert "Define Search Space" in cleaned
    assert "Auto Discovery" in cleaned
    assert "New SOTA Deployed" in cleaned


def test_sanitize_emojis_strips_unknown_smp_characters():
    # SMP emoji that lacks font on Linux containers should be stripped rather than render as tofu []
    html = "<div>Testing alien emoji 👾 in container</div>"
    cleaned = _sanitize_emojis_to_vector_svg(html)
    assert "👾" not in cleaned
    assert "<div>Testing alien emoji  in container</div>" == cleaned


def test_patch_html_integration_removes_sota_dot_and_emojis(tmp_path: Path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for font in ("BeVietnamPro-Regular.ttf", "BeVietnamPro-Bold.ttf", "BeVietnamPro-ExtraBold.ttf"):
        (assets_dir / font).write_bytes(b"mock font")

    html_content = """<!doctype html>
<html>
<head>
<style>
body { margin: 0; overflow: hidden; }
#stage { width: 1080px; height: 1920px; position: relative; }
</style>
</head>
<body>
<div id="stage" class="composition" data-composition-id="main" data-start="0" data-duration="60" data-width="1080" data-height="1920">
  <div id="scene-1" class="scene" data-start="0" data-duration="30">
    <div class="metric-card">
      <div class="metric-value">SOTA.</div>
    </div>
    <div class="flow-box">🔍 Define Search Space.</div>
    <div class="flow-arrow">↓.</div>
  </div>
</div>
</body>
</html>"""
    index_file = tmp_path / "index.html"
    index_file.write_text(html_content, encoding="utf-8")

    patch_html(index_file, narration_duration=60.0)

    result = index_file.read_text(encoding="utf-8")
    assert '<div class="metric-value">SOTA</div>' in result
    assert "SOTA." not in result
    assert "↓." not in result
    assert "🔍" not in result
    assert "<svg" in result
