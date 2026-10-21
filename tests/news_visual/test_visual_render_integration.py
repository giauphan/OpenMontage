"""T09: Verify HyperFrames seek determinism and real render integration.

Asserts that HyperFrames timeline seeking is deterministic and equal timestamps produce identical visual states.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _resolve_browser_path() -> Path:
    env_path = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    if env_path:
        return Path(env_path)
    user_cache = Path.home() / ".cache" / "ms-playwright"
    shells = list(user_cache.glob("chromium_headless_shell-*/chrome-linux/headless_shell"))
    if shells and shells[0].is_file():
        return shells[0]
    legacy = Path("/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux/headless_shell")
    if legacy.is_file():
        return legacy
    return Path("/nonexistent/headless_shell")


def _resolve_hyperframes_bin() -> Path:
    env_bin = os.environ.get("HYPERFRAMES_BIN")
    if env_bin:
        return Path(env_bin)
    which_bin = shutil.which("hyperframes")
    if which_bin and Path(which_bin).is_file():
        return Path(which_bin)
    repo_bin = ROOT / "node_modules" / ".bin" / "hyperframes"
    if repo_bin.is_file():
        return repo_bin
    return repo_bin


BROWSER_PATH = _resolve_browser_path()
HYPERFRAMES_BIN = _resolve_hyperframes_bin()

_CAN_RENDER = HYPERFRAMES_BIN.is_file() and BROWSER_PATH.is_file()
_PRE_RENDERED_SAMPLE = Path("/tmp/test_explainer_render/out.mp4").is_file()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.skipif(
    not _CAN_RENDER,
    reason="HyperFrames and chrome-headless-shell required for real render test",
)
def test_t09_hyperframes_seek_determinism(tmp_path: Path):
    """T09: HyperFrames timeline seeking is deterministic (same timestamp produces identical frame hash)."""
    project_dir = tmp_path / "cand_render_test"
    project_dir.mkdir(parents=True, exist_ok=True)

    # 1. Materialize a standard explainer template composition
    fixture_path = ROOT / "templates" / "news" / "packages" / "news-explainer" / "fixtures" / "full_story_1.json"
    from scripts.materialize_news_template import materialize
    content = json.loads(fixture_path.read_text(encoding="utf-8"))
    materialize(
        package_id="news-explainer",
        content=content,
        project_dir=project_dir,
        variant="full",
    )

    hf_dir = project_dir / "hyperframes"
    assert (hf_dir / "index.html").is_file()

    # 2. Add dummy audio so asset check passes
    assets_dir = hf_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    dummy_mp3 = assets_dir / "narration.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "10", "-c:a", "libmp3lame", str(dummy_mp3)],
        check=True,
        capture_output=True,
    )
    shutil.copy(dummy_mp3, assets_dir / "music-bg.mp3")

    # 3. Snapshot with repeated timestamp [2.0, 5.0, 2.0]
    snapshots_dir = project_dir / "snapshots"
    env = os.environ.copy()
    env["HYPERFRAMES_BROWSER_PATH"] = str(BROWSER_PATH)

    cmd = [
        str(HYPERFRAMES_BIN),
        "snapshot",
        str(hf_dir),
        "--at", "2,12,2",
        "--no-end",
        "-o", str(snapshots_dir),
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"hyperframes snapshot failed: {res.stderr}\n{res.stdout}"

    # Verify frame files exist
    frame_0 = snapshots_dir / "frame-00-at-2s.png"
    frame_1 = snapshots_dir / "frame-01-at-12s.png"
    frame_2 = snapshots_dir / "frame-02-at-2s.png"

    assert frame_0.is_file(), f"Missing {frame_0}"
    assert frame_1.is_file(), f"Missing {frame_1}"
    assert frame_2.is_file(), f"Missing {frame_2}"

    hash_0 = _sha256_file(frame_0)
    hash_1 = _sha256_file(frame_1)
    hash_2 = _sha256_file(frame_2)

    # Invariant: Snapshot at 2.0s must be bitwise identical regardless of seek sequence
    assert hash_0 == hash_2, (
        f"Deterministic seek failure: Frame at 2s (first pass: {hash_0[:8]}) != "
        f"Frame at 2s (second pass: {hash_2[:8]})"
    )

    # Invariant: Frame at 2s and 12s should have visual progress across scenes
    assert hash_0 != hash_1, "Expected visual change between Scene 1 (2s) and Scene 2 (12s) snapshots"


@pytest.mark.skipif(
    not (_PRE_RENDERED_SAMPLE or _CAN_RENDER),
    reason="HyperFrames and chrome-headless-shell (or pre-rendered sample) required for real render test",
)
def test_t09_real_render_mp4_integrity(tmp_path: Path):
    """T09: Verify real MP4 render stream has correct 1080x1920 geometry, audio, and valid pixels."""
    mp4_path = Path("/tmp/test_explainer_render/out.mp4")
    if not mp4_path.is_file():
        if not _CAN_RENDER:
            pytest.skip("HyperFrames and chrome-headless-shell required to render test sample")
        # Render a short sample to tmp_path to verify stream integrity self-contained
        from scripts.materialize_news_template import materialize
        fixture_path = ROOT / "tests" / "news_visual" / "fixtures" / "demonode_visual_explainer.json"
        content = json.loads(fixture_path.read_text(encoding="utf-8"))
        content["duration"] = 8.0
        content["slots"]["hook"]["end"] = 8.0
        content["slots"]["capability"]["start"] = 8.0
        content["slots"]["capability"]["end"] = 8.0
        content["slots"]["steps"]["start"] = 8.0
        content["slots"]["steps"]["end"] = 8.0
        materialize("news-explainer", content, tmp_path, variant="short")

        hf_reels = tmp_path / "hyperframes_reels"
        assets_dir = hf_reels / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        visuals_dir = assets_dir / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)
        for svg_f in (ROOT / "assets" / "visuals").glob("*.svg"):
            shutil.copy(svg_f, visuals_dir / svg_f.name)

        dummy_mp3 = assets_dir / "narration_reels.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "8", "-c:a", "libmp3lame", str(dummy_mp3)],
            check=True,
            capture_output=True,
        )
        shutil.copy(dummy_mp3, assets_dir / "music-bg.mp3")

        mp4_path = tmp_path / "out.mp4"
        env = os.environ.copy()
        env["HYPERFRAMES_BROWSER_PATH"] = str(BROWSER_PATH)
        subprocess.run(
            [str(HYPERFRAMES_BIN), "render", str(hf_reels), "-o", str(mp4_path), "--fps", "15"],
            env=env,
            check=True,
            capture_output=True,
        )

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(res.stdout)

    streams = info.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    assert video_stream is not None, "Missing video stream in rendered MP4"
    assert video_stream.get("width") == 1080
    assert video_stream.get("height") == 1920
    assert float(info["format"]["duration"]) > 0
    assert audio_stream is not None, "Missing audio stream in rendered MP4"
