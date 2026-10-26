"""Remotion rendering engine adapter and media staging.

Manages React-based video composition rendering via npx remotion render,
including media staging into Remotion public directories, renderer family mapping,
and theme injection.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from tools.base_tool import ToolResult
from tools.video._compose.asset_resolution import cuts_to_cinematic_scenes
from tools.video._compose.atelier import build_theme_from_playbook

# Remotion scene types that trigger React-based rendering
REMOTION_COMPONENTS = [
    "text_card", "stat_card", "callout", "comparison",
    "progress", "chart", "bar_chart", "line_chart", "pie_chart", "kpi_grid",
]

REMOTION_SCENE_TYPES = {
    "text_card", "stat_card", "callout", "comparison", "progress", "chart",
}

# Maps renderer_family → Remotion composition ID.
RENDERER_FAMILY_MAP = {
    "explainer-data": "Explainer",
    "explainer-teacher": "Explainer",
    "cinematic-trailer": "CinematicRenderer",
    "documentary-montage": "CinematicRenderer",
    "product-reveal": "Explainer",
    "screen-demo": "Explainer",
    "presenter": "TalkingHead",
    "animation-first": "Explainer",
}


def get_composition_id(renderer_family: str) -> str:
    """Resolve renderer_family to Remotion composition ID."""
    comp = RENDERER_FAMILY_MAP.get(renderer_family)
    if comp is None:
        raise ValueError(
            f"Unknown renderer_family {renderer_family!r}. "
            f"Valid families: {sorted(RENDERER_FAMILY_MAP)}. "
            f"Set renderer_family at proposal stage."
        )
    return comp


def stage_remotion_media(value: Any, public_dir: Path) -> int:
    """Copy local media references into a Remotion public dir in-place."""
    staged_by_source: dict[Path, str] = {}
    media_keys = {"source", "src", "backgroundSrc"}

    def visit(node: Any, parent_key: str | None = None) -> Any:
        if isinstance(node, dict):
            for key, child in list(node.items()):
                node[key] = visit(child, key)
            return node
        if isinstance(node, list):
            for index, child in enumerate(node):
                node[index] = visit(child, parent_key)
            return node
        if not isinstance(node, str) or parent_key not in media_keys:
            return node
        if node.startswith(("http://", "https://", "data:")):
            return node

        if node.lower().startswith("file://"):
            parsed = urlsplit(node)
            decoded_path = unquote(parsed.path)
            if len(parsed.netloc) == 2 and parsed.netloc[1] == ":":
                raw_path = f"{parsed.netloc}{decoded_path}"
            elif parsed.netloc and parsed.netloc.lower() != "localhost":
                raw_path = f"//{parsed.netloc}{decoded_path}"
            else:
                raw_path = decoded_path
            if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
                raw_path = raw_path[1:]
        else:
            raw_path = node
        source = Path(raw_path).resolve()
        if not source.is_file():
            return node
        if source not in staged_by_source:
            digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
            name = f"{digest}-{source.name}"
            public_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, public_dir / name)
            staged_by_source[source] = name
        return staged_by_source[source]

    visit(value)
    return len(staged_by_source)


def needs_remotion(
    remotion_available: bool,
    cuts: list[dict],
    image_extensions: set[str],
    remotion_scene_types: set[str] | None = None,
) -> bool:
    """Determine whether Remotion should handle this composition."""
    if not remotion_available:
        return False

    scene_types = remotion_scene_types or REMOTION_SCENE_TYPES

    for cut in cuts:
        source = cut.get("source", "")
        if source and Path(source).suffix.lower() in image_extensions:
            return True
        if cut.get("type") in scene_types:
            return True
        if cut.get("animation") or cut.get("transition_in") or cut.get("transition_out"):
            return True
        transform = cut.get("transform", {})
        if transform and transform.get("animation"):
            return True

    return True


def remotion_render(tool: Any, inputs: dict[str, Any]) -> ToolResult:
    """Render via Remotion (requires Node.js + npx)."""
    if not shutil.which("npx"):
        return ToolResult(
            success=False,
            error="npx not found. Install Node.js to use Remotion rendering.",
        )

    composition_data = inputs.get("edit_decisions") or inputs.get("composition_data")
    if not composition_data:
        return ToolResult(
            success=False,
            error="edit_decisions or composition_data required for remotion_render",
        )

    output_path = Path(inputs.get("output_path", "renders/remotion_output.mp4"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path = output_path.resolve()

    props = json.loads(json.dumps(composition_data))

    if "themeConfig" not in props:
        playbook_name = (
            props.get("playbook")
            or props.get("theme")
            or props.get("metadata", {}).get("playbook")
        )
        theme_config = build_theme_from_playbook(playbook_name, composition_data)
        if theme_config:
            props["themeConfig"] = theme_config

    composer_dir = Path(__file__).resolve().parent.parent.parent.parent / "remotion-composer"
    if not composer_dir.exists():
        return ToolResult(
            success=False,
            error=f"Remotion composer project not found at {composer_dir}",
        )

    renderer_family = (composition_data or {}).get("renderer_family", "explainer-data")
    composition_id = get_composition_id(renderer_family)

    if composition_id == "CinematicRenderer":
        if not props.get("scenes") and props.get("cuts"):
            props["scenes"] = cuts_to_cinematic_scenes(props["cuts"])
        props.pop("cuts", None)
        if not props.get("scenes"):
            return ToolResult(
                success=False,
                error="CinematicRenderer received cuts but none could be adapted into scenes.",
            )

    requested_public_dir = inputs.get("public_dir")
    cleanup_public_dir = False
    public_dir: Path | None = None
    if requested_public_dir:
        public_dir = Path(requested_public_dir).resolve()
        if not public_dir.is_dir():
            return ToolResult(
                success=False,
                error=f"Remotion public_dir does not exist or is not a directory: {public_dir}",
            )
    else:
        public_dir = output_path.parent / f".remotion-public-{output_path.stem}"
        cleanup_public_dir = True

    staged_count = stage_remotion_media(props, public_dir)
    if not staged_count and cleanup_public_dir:
        public_dir = None

    props_path = output_path.parent / ".remotion_props.json"
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f)

    cmd = [
        "npx", "remotion", "render",
        str(composer_dir / "src" / "index.tsx"),
        composition_id,
        str(output_path),
        f"--props={props_path}",
    ]
    if public_dir is not None:
        cmd.append(f"--public-dir={public_dir}")

    profile_name = inputs.get("profile")
    if profile_name:
        try:
            from lib.media_profiles import get_profile
            p = get_profile(profile_name)
            cmd.extend(["--width", str(p.width), "--height", str(p.height)])
        except (ImportError, ValueError):
            pass

    remotion_timeout_ms = inputs.get("remotion_timeout_ms")
    scene_count = len(props.get("scenes") or props.get("cuts") or [])
    subprocess_timeout = max(600, scene_count * 15)
    if remotion_timeout_ms:
        try:
            ms = int(remotion_timeout_ms)
            cmd.append(f"--timeout={ms}")
            subprocess_timeout = max(subprocess_timeout, ms // 1000 + 60)
        except (TypeError, ValueError):
            pass

    try:
        tool.run_command(cmd, timeout=subprocess_timeout, cwd=composer_dir)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        tail = "\n".join(detail.splitlines()[-25:]) if detail else "(no output captured)"
        return ToolResult(
            success=False,
            error=f"Remotion render failed (exit {e.returncode}):\n{tail}",
        )
    except subprocess.TimeoutExpired as e:
        return ToolResult(
            success=False,
            error=(
                f"Remotion render timed out after {e.timeout}s. If the headless "
                "browser is slow to start, raise remotion_timeout_ms (ms)."
            ),
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Remotion render failed: {e}")
    finally:
        if props_path.exists():
            props_path.unlink()
        if cleanup_public_dir and public_dir is not None and public_dir.exists():
            shutil.rmtree(public_dir, ignore_errors=True)

    if not output_path.exists():
        return ToolResult(
            success=False,
            error=f"Remotion render completed but output file missing: {output_path}",
        )

    return ToolResult(
        success=True,
        data={
            "operation": "remotion_render",
            "output": str(output_path),
            "profile": profile_name,
            "staged_media_count": staged_count,
        },
        artifacts=[str(output_path)],
    )
