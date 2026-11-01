"""HyperFrames composition materializer and CLI renderer for Fixed Niche videos.

Handles directory creation, asset copying, composition materialization,
and invoking `npx hyperframes render`.
Enforces Clean Architecture module sizing (< 450 lines).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NARRATION_MP3_FILENAME = "narration.mp3"
DEFAULT_AUDIO_SRC = f"assets/{NARRATION_MP3_FILENAME}"

EXT_WEBP = ".webp"
EXT_PNG = ".png"
EXT_JPG = ".jpg"
EXT_JPEG = ".jpeg"
EXT_SVG = ".svg"
ALL_SUPPORTED_MEDIA_EXTS = (EXT_SVG, EXT_PNG, EXT_JPG, EXT_JPEG, EXT_WEBP, ".mp4", ".webm")
COPYABLE_MEDIA_EXTS = (EXT_PNG, EXT_JPG, EXT_JPEG, EXT_WEBP, ".mp4", ".webm")


def load_diagram_plan(project_dir: Path) -> Optional[Any]:
    """Load and validate animated diagram sidecar plan if present."""
    sidecar_file = project_dir / "artifacts" / "diagram_animation_plan.json"
    if not sidecar_file.is_file():
        return None
    try:
        from lib.visual_style.spec import DiagramAnimationPlan
        from lib.visual_style.validation import validate_diagram_plan_data
        plan_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        errs = validate_diagram_plan_data(plan_data)
        if errs:
            raise ValueError(f"Sidecar failed validation ({len(errs)} errors): {errs}")
        return DiagramAnimationPlan.from_dict(plan_data)
    except Exception as exc:
        logger.warning(f"Could not load sidecar {sidecar_file}: {exc}")
        return None


def copy_composition_visuals(visuals_src: Optional[Path], comp_vis: Path) -> None:
    """Ensure composition visuals directory has no static diagram SVGs in progressive mode."""
    is_legacy = os.environ.get("OPENMONTAGE_VISUAL_STYLE") == "legacy"
    if not is_legacy and comp_vis.is_dir():
        for existing_svg in comp_vis.glob("*.svg"):
            try:
                existing_svg.unlink()
            except OSError:
                pass
    if not visuals_src or not visuals_src.is_dir():
        return
    copy_exts = ALL_SUPPORTED_MEDIA_EXTS if is_legacy else COPYABLE_MEDIA_EXTS
    for vis_file in visuals_src.iterdir():
        if vis_file.is_file() and vis_file.suffix.lower() in copy_exts:
            comp_vis.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vis_file, comp_vis / vis_file.name)


def copy_composition_vendor(comp_dir: Path) -> None:
    """Copy vendor assets such as GSAP into composition directory."""
    repo_root = Path(__file__).resolve().parents[2]
    local_gsap = repo_root / "assets" / "vendor" / "gsap.min.js"
    if not local_gsap.is_file():
        local_gsap = Path("assets/vendor/gsap.min.js")
    if local_gsap.is_file():
        comp_vendor = comp_dir / "assets" / "vendor"
        comp_vendor.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_gsap, comp_vendor / "gsap.min.js")


def copy_composition_audio(audio_src: Path, comp_dir: Path) -> None:
    """Copy narration, BGM, and sound effect assets into composition directory."""
    comp_assets = comp_dir / "assets"
    comp_assets.mkdir(parents=True, exist_ok=True)
    if audio_src.is_file():
        shutil.copy2(audio_src, comp_assets / NARRATION_MP3_FILENAME)

    repo_root = Path(__file__).resolve().parents[2]
    parent_assets = comp_dir.parent / "assets"

    # Copy background music bed
    for bgm_cand in (
        parent_assets / "music-bg.mp3",
        audio_src.parent / "music-bg.mp3",
        repo_root / "assets" / "audio" / "music-bg.mp3",
    ):
        if bgm_cand.is_file():
            shutil.copy2(bgm_cand, comp_assets / "music-bg.mp3")
            if not (parent_assets / "music-bg.mp3").is_file():
                parent_assets.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bgm_cand, parent_assets / "music-bg.mp3")
            break

    # Copy sound effects library
    for sfx_dir in (
        parent_assets / "sfx",
        audio_src.parent / "sfx",
        repo_root / "assets" / "audio" / "sfx",
    ):
        if sfx_dir.is_dir():
            comp_sfx = comp_assets / "sfx"
            comp_sfx.mkdir(parents=True, exist_ok=True)
            for f in sfx_dir.glob("*.mp3"):
                shutil.copy2(f, comp_sfx / f.name)
            parent_sfx = parent_assets / "sfx"
            if not parent_sfx.is_dir():
                parent_sfx.mkdir(parents=True, exist_ok=True)
                for f in sfx_dir.glob("*.mp3"):
                    shutil.copy2(f, parent_sfx / f.name)
            break


def _materialize_single_composition(
    comp_name: str,
    project_dir: Path,
    title: str,
    duration: float,
    beats: List[Dict[str, Any]],
    visuals_src: Path,
    audio_src: Path,
    diagram_plan: Optional[Any],
    topic: Optional[Dict[str, Any]] = None,
) -> Path:
    from lib.fixed_niche.hyperframes_composer import compose_hyperframes_html

    comp_dir = project_dir / comp_name
    comp_dir.mkdir(parents=True, exist_ok=True)
    copy_composition_visuals(visuals_src, comp_dir / "assets" / "visuals")
    copy_composition_vendor(comp_dir)
    copy_composition_audio(audio_src, comp_dir)
    is_vertical = "reels" in comp_name or "short" in comp_name
    html_content = compose_hyperframes_html(
        title=title,
        duration=duration,
        beats=beats,
        is_vertical=is_vertical,
        audio_src=DEFAULT_AUDIO_SRC,
        visuals_src=visuals_src,
        diagram_plan=diagram_plan,
        topic=topic,
        project_dir=project_dir,
    )
    index_file = comp_dir / "index.html"
    index_file.write_text(html_content, encoding="utf-8")
    return index_file


def materialize_hyperframes_project(
    project_dir: Path,
    topic: Dict[str, Any],
    visual_plan: Dict[str, Any],
    duration: float,
    composition_names: tuple[str, ...] = ("hyperframes", "hyperframes_reels"),
) -> Dict[str, Path]:
    """Materialize HyperFrames composition directories and valid index.html entrypoints."""
    project_dir = Path(project_dir).resolve()
    visuals_src = project_dir / "assets" / "visuals"
    audio_src = project_dir / "assets" / NARRATION_MP3_FILENAME
    beats = visual_plan.get("beats", [])
    title = topic.get("title", "Practical AI Agent Engineering")
    diagram_plan = load_diagram_plan(project_dir)

    result_paths: Dict[str, Path] = {}
    for comp_name in composition_names:
        result_paths[comp_name] = _materialize_single_composition(
            comp_name=comp_name,
            project_dir=project_dir,
            title=title,
            duration=duration,
            beats=beats,
            visuals_src=visuals_src,
            audio_src=audio_src,
            diagram_plan=diagram_plan,
            topic=topic,
        )
    return result_paths


def render_hyperframes_composition(
    comp_dir: Path,
    output_mp4: Path,
    *,
    quality: str = "draft",
    timeout_seconds: float = 600.0,
    burn_captions: bool = False,
    ass_path: Optional[Path] = None,
) -> Path:
    """Render HyperFrames composition using `npx hyperframes render`.

    If burn_captions is True and ass_path exists, burns subtitles into output.
    """
    comp_dir = Path(comp_dir).resolve()
    output_mp4 = Path(output_mp4).resolve()
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    # Ensure narration and audio assets exist in comp_dir/assets
    copy_composition_audio(comp_dir.parent / "assets" / NARRATION_MP3_FILENAME, comp_dir)

    raw_mp4 = output_mp4 if not burn_captions else output_mp4.with_suffix(".raw.mp4")
    cmd = [
        "npx", "hyperframes", "render",
        str(comp_dir),
        "-o", str(raw_mp4),
        "--quality", quality,
    ]
    env = dict(os.environ)
    if "HYPERFRAMES_BROWSER_PATH" not in env:
        playwright_shell = Path("/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux/headless_shell")
        brave_sh = Path("/tmp/brave_headless.sh")
        if playwright_shell.is_file():
            env["HYPERFRAMES_BROWSER_PATH"] = str(playwright_shell)
        elif not brave_sh.is_file() and Path("/opt/brave.com/brave/brave").is_file():
            brave_sh.write_text(
                "#!/bin/bash\nexec /opt/brave.com/brave/brave --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage \"$@\"\n",
                encoding="utf-8",
            )
            brave_sh.chmod(0o755)
            env["HYPERFRAMES_BROWSER_PATH"] = str(brave_sh)
        elif brave_sh.is_file():
            env["HYPERFRAMES_BROWSER_PATH"] = str(brave_sh)

    logger.info("Executing HyperFrames render: %s", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"HyperFrames render failed (exit {res.returncode}): {res.stderr or res.stdout}")

    if burn_captions and ass_path and ass_path.is_file():
        esc_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        burn_cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(raw_mp4),
            "-vf", f"ass='{esc_ass}'",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "copy",
            str(output_mp4),
        ]
        subprocess.run(burn_cmd, check=True)
        raw_mp4.unlink(missing_ok=True)

    return output_mp4
