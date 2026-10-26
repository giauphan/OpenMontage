"""Atelier (bespoke) composition mode and doctrine enforcement.

Atelier mode hand-authors compositions from scratch rather than assembling stock
scenes, providing a fresh visual language per deliverable.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.base_tool import ToolResult

# Source-file extensions that get staged into the composer tree at render time.
# Anything not in this set lives only under the real project dir (assets, renders,
# artifacts) and is referenced via --public-dir or absolute paths.
ATELIER_STAGE_EXTS = {".tsx", ".ts", ".jsx", ".js", ".css"}

# Stock-registry import patterns that violate the atelier doctrine.
# Any of these inside a bespoke project tree means a creative component
# was reused instead of hand-stitched. Engine knowledge (the `remotion`
# package, `@remotion/*`, project-local files) is fine.
ATELIER_STOCK_IMPORT_RE = (
    r"""from\s+["']("""
    # parent-traversed paths into the stock src/
    r"""(?:\.\./)+src/(?:components|Explainer|CinematicRenderer|"""
    r"""TitledVideo|TalkingHead|CollageBurst|LyricOverlay|cinematic|crucix|phantom)"""
    # or absolute-ish paths into the same
    r"""|remotion-composer/src/(?:components|Explainer|CinematicRenderer|"""
    r"""TitledVideo|TalkingHead|CollageBurst|LyricOverlay|cinematic|crucix|phantom)"""
    r""")"""
)


def stage_atelier_project(entry_path: Path, composer_dir: Path) -> Path:
    """Auto-stage a bespoke project under remotion-composer/projects/<slug>/.

    The source of truth lives under the repo-root `projects/<slug>/` (where
    artifacts/, assets/, renders/ already are). Remotion's webpack bundler,
    however, resolves modules (`remotion`, `@remotion/*`) by walking up from
    the entry's REAL location — so a directory junction/symlink would
    dereference and webpack would fail to find node_modules. We copy the
    source files into a sibling dir inside the composer tree instead.

    mtime-skip semantics make repeat renders cheap (typical project is a
    handful of small .tsx files). Non-source files (assets, renders, props
    JSON) stay only in the real project dir and are referenced via
    --public-dir or absolute paths in props.

    Resolves the slug as the first path segment under a `projects/` ancestor;
    falls back to the entry's parent directory name. Returns the staged entry
    path.
    """
    real_project_dir = entry_path.parent.resolve()

    # Derive a stable slug. Prefer the first segment under a `projects/` ancestor.
    slug = real_project_dir.name
    try:
        parts = real_project_dir.parts
        if "projects" in parts:
            i = parts.index("projects")
            if i + 1 < len(parts):
                slug = parts[i + 1]
    except Exception:
        pass

    staging_root = composer_dir / "projects"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_dir = staging_root / slug

    # If a stale junction/symlink is in the way from an earlier (failed) attempt,
    # remove it before creating a real staging directory.
    if staging_dir.is_symlink() or (
        staging_dir.exists()
        and staging_dir.is_dir()
        and staging_dir.resolve() != staging_dir
    ):
        try:
            staging_dir.unlink()
        except (OSError, PermissionError):
            subprocess.run(["cmd", "/c", "rmdir", str(staging_dir)], check=True)

    staging_dir.mkdir(parents=True, exist_ok=True)

    # mtime-skip copy of source files only. Mirrors directory structure so
    # relative imports work identically.
    for src in real_project_dir.rglob("*"):
        if not src.is_file():
            continue
        if src.suffix.lower() not in ATELIER_STAGE_EXTS:
            continue
        rel = src.relative_to(real_project_dir)
        dst = staging_dir / rel
        try:
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
        except OSError:
            pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return staging_dir / entry_path.name


def run_atelier_checks(entry_path: Path, bespoke: dict[str, Any]) -> dict[str, Any]:
    """Doctrine-enforcement checks specific to atelier mode.

    Returns a dict with two checks:
      - stock_reuse_detected (bool) + offending_imports (list) — CRITICAL,
        fails the render. Catches `import X from "../../src/components/..."`
        and similar reuse of stock creative components.
      - art_direction_declared (bool) + art_direction (str|None) — WARNING.
        Forces step 1 of the bespoke-composition skill (commit to a fresh
        art direction per video) to be written down rather than skipped.
    """
    issues: list[str] = []
    offending: list[dict[str, str]] = []
    project_dir = entry_path.parent
    pat = re.compile(ATELIER_STOCK_IMPORT_RE)

    try:
        for f in project_dir.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in {".tsx", ".ts", ".jsx", ".js"}:
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in pat.finditer(txt):
                offending.append({"file": str(f.relative_to(project_dir)), "import": m.group(1)})
    except Exception as e:
        issues.append(f"atelier stock-reuse scan errored: {e}")

    stock_reuse_detected = bool(offending)
    if stock_reuse_detected:
        issues.append(
            "atelier doctrine violation: bespoke project imports from the stock "
            "creative registry. Hand-author the scene instead — the registry is "
            "a mechanics codex, not a parts bin. Offending imports: "
            + ", ".join(f"{o['file']} → {o['import']}" for o in offending[:5])
            + ("…" if len(offending) > 5 else "")
        )

    art_direction = bespoke.get("art_direction") or bespoke.get("art_direction_note")
    art_direction_declared = bool(art_direction and str(art_direction).strip())
    if not art_direction_declared:
        issues.append(
            "atelier warning: no bespoke.art_direction declared. Per "
            "skills/meta/bespoke-composition.md step 1, every atelier piece must "
            "commit to a fresh art direction (palette, type, motion, signature "
            "device) before authoring. Pass edit_decisions.bespoke.art_direction "
            "as a short note or a path to art-direction.md."
        )

    return {
        "stock_reuse_detected": stock_reuse_detected,
        "offending_imports": offending,
        "art_direction_declared": art_direction_declared,
        "art_direction": str(art_direction) if art_direction else None,
        "issues": issues,
    }


def build_theme_from_playbook(
    playbook_name: str | None,
    composition_data: dict | None,
) -> dict[str, Any] | None:
    """Derive a Remotion ThemeConfig from a playbook's actual color values.

    Instead of passing a playbook name and hoping Remotion has a matching
    preset, we read the playbook YAML and extract concrete colors/fonts.
    This means custom playbooks, overridden palettes, and per-project
    styles all flow through to Remotion automatically.

    Falls back to extracting colors from edit_decisions metadata if
    no playbook is loadable.
    """
    theme: dict[str, Any] = {}

    # Try to load the playbook YAML
    playbook: dict[str, Any] = {}
    if playbook_name:
        try:
            from styles.playbook_loader import load_playbook
            playbook = load_playbook(playbook_name)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Could not load style playbook %r for Remotion theme: %s",
                playbook_name,
                exc,
            )

    if playbook:
        vl = playbook.get("visual_language", {})
        palette = vl.get("color_palette", {})
        typo = playbook.get("typography", {})

        primary_raw = palette.get("primary", ["#2563EB"])
        accent_raw = palette.get("accent", ["#F59E0B"])
        primary = primary_raw[0] if isinstance(primary_raw, list) else primary_raw
        accent = accent_raw[0] if isinstance(accent_raw, list) else accent_raw

        bg = palette.get("background", "#FFFFFF")
        text = palette.get("text", "#1F2937")
        surface = palette.get("surface", bg)
        muted = palette.get("muted_text", "#6B7280")

        chart_colors = []
        for key in ["primary", "accent", "secondary", "success", "warning", "info"]:
            val = palette.get(key)
            if val:
                chart_colors.append(val[0] if isinstance(val, list) else val)
        if len(chart_colors) < 3:
            chart_colors = [primary, accent, "#10B981", "#8B5CF6", "#EC4899", "#06B6D4"]

        theme = {
            "primaryColor": primary,
            "accentColor": accent,
            "backgroundColor": bg,
            "surfaceColor": surface,
            "textColor": text,
            "mutedTextColor": muted,
            "headingFont": typo.get("heading", {}).get("font", "Inter"),
            "bodyFont": typo.get("body", {}).get("font", "Inter"),
            "monoFont": typo.get("code", {}).get("font", "JetBrains Mono"),
            "chartColors": chart_colors[:6],
            "springConfig": {"damping": 20, "stiffness": 120, "mass": 1},
            "transitionDuration": 0.4,
        }

        theme["captionHighlightColor"] = primary
        theme["captionBackgroundColor"] = (
            f"rgba(255, 255, 255, 0.85)" if bg.upper() in ("#FFFFFF", "#FAFAFA", "#F9FAFB")
            else f"rgba(15, 23, 42, 0.75)"
        )

        motion = playbook.get("motion", {})
        pace = motion.get("pace", "moderate")
        if pace == "fast":
            theme["springConfig"] = {"damping": 12, "stiffness": 80, "mass": 1}
            theme["transitionDuration"] = 0.3
        elif pace == "slow":
            theme["springConfig"] = {"damping": 25, "stiffness": 150, "mass": 1}
            theme["transitionDuration"] = 0.6

    if not theme and composition_data:
        meta = composition_data.get("metadata", {})
        if meta.get("primary_color"):
            theme = {
                "primaryColor": meta["primary_color"],
                "accentColor": meta.get("accent_color", "#F59E0B"),
                "backgroundColor": meta.get("background_color", "#FFFFFF"),
                "surfaceColor": meta.get("surface_color", "#F9FAFB"),
                "textColor": meta.get("text_color", "#1F2937"),
                "mutedTextColor": "#6B7280",
                "headingFont": meta.get("heading_font", "Inter"),
                "bodyFont": meta.get("body_font", "Inter"),
                "monoFont": "JetBrains Mono",
                "chartColors": meta.get("chart_colors", ["#2563EB", "#F59E0B", "#10B981"]),
                "springConfig": {"damping": 20, "stiffness": 120, "mass": 1},
                "transitionDuration": 0.4,
                "captionHighlightColor": meta["primary_color"],
                "captionBackgroundColor": "rgba(255, 255, 255, 0.85)",
            }

    return theme if theme else None


def render_via_atelier(
    tool: Any,
    inputs: dict[str, Any],
    edit_decisions: dict[str, Any],
) -> ToolResult:
    """Render a hand-authored, project-local Remotion composition ("atelier" mode)."""
    bespoke = edit_decisions.get("bespoke") or {}
    entry = bespoke.get("entry")
    comp_id = bespoke.get("composition_id")
    if not entry or not comp_id:
        return ToolResult(
            success=False,
            error=(
                "atelier mode requires edit_decisions.bespoke.entry (path to the "
                "project-local Remotion entry .tsx) and edit_decisions.bespoke."
                "composition_id (the id registered in that entry's Root)."
            ),
        )

    composer_dir = Path(__file__).resolve().parent.parent.parent.parent / "remotion-composer"
    if not composer_dir.exists() or not (composer_dir / "node_modules").exists():
        return ToolResult(
            success=False,
            error=(
                f"remotion-composer or its node_modules is missing at {composer_dir}. "
                f"Run `cd remotion-composer && npm install` first."
            ),
        )

    entry_path = Path(entry)
    if not entry_path.is_absolute():
        repo_root = composer_dir.parent
        cand = (repo_root / entry).resolve()
        entry_path = cand if cand.exists() else (composer_dir / entry).resolve()
    entry_path = entry_path.resolve()
    if not entry_path.exists():
        return ToolResult(success=False, error=f"atelier entry not found: {entry_path}")

    try:
        entry_path.relative_to(composer_dir)
        effective_entry = entry_path
    except ValueError:
        try:
            effective_entry = stage_atelier_project(entry_path, composer_dir)
        except Exception as e:
            return ToolResult(
                success=False,
                error=(
                    f"atelier auto-stage failed for entry {entry_path}: {e}. "
                    f"Either place the entry under {composer_dir}/projects/<slug>/ "
                    f"directly, or fix the staging permission issue."
                ),
            )

    output_path = Path(inputs.get("output_path", "renders/output.mp4")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["npx", "remotion", "render", str(effective_entry), str(comp_id), str(output_path)]

    props_path = bespoke.get("props_path")
    if props_path:
        pp = Path(props_path).resolve()
        if not pp.exists():
            return ToolResult(success=False, error=f"atelier props_path not found: {pp}")
        cmd.append(f"--props={pp}")

    public_dir = bespoke.get("public_dir")
    if public_dir:
        pd = Path(public_dir).resolve()
        if pd.exists():
            cmd.append(f"--public-dir={pd}")

    if bespoke.get("scale"):
        cmd.append(f"--scale={bespoke['scale']}")
    if bespoke.get("crf") is not None:
        cmd.append(f"--crf={bespoke['crf']}")
    if bespoke.get("concurrency"):
        cmd.append(f"--concurrency={bespoke['concurrency']}")

    try:
        tool.run_command(cmd, timeout=1800, cwd=composer_dir)
    except Exception as e:
        return ToolResult(success=False, error=f"Atelier (bespoke) Remotion render failed: {e}")

    if not output_path.exists():
        return ToolResult(
            success=False,
            error=f"Atelier render completed but output file missing: {output_path}",
        )

    if inputs.get("audio_path"):
        mux_result = tool._mux_external_audio(output_path, inputs["audio_path"])
        if not mux_result.success:
            return mux_result

    final_review = tool._run_final_review(
        output_path=output_path,
        edit_decisions=edit_decisions,
        proposal_packet=inputs.get("proposal_packet"),
        narration_transcript_path=inputs.get("narration_transcript_path"),
        script_text=inputs.get("script_text"),
    )

    atelier_checks = run_atelier_checks(entry_path, bespoke)
    final_review.setdefault("checks", {})["atelier"] = atelier_checks
    final_review["issues_found"] = list(final_review.get("issues_found", [])) + atelier_checks.get("issues", [])

    if atelier_checks.get("stock_reuse_detected"):
        final_review["status"] = "fail"
        final_review["recommended_action"] = "re_author"

    data: dict[str, Any] = {
        "operation": "render",
        "composition_mode": "atelier",
        "entry": str(entry_path),
        "effective_entry": str(effective_entry) if effective_entry != entry_path else None,
        "composition_id": comp_id,
        "output": str(output_path),
        "final_review": final_review,
        "final_review_status": final_review.get("status"),
    }

    if final_review.get("status") == "fail":
        return ToolResult(
            success=False,
            error=(
                "Atelier render produced an invalid output:\n"
                + "\n".join(f"  • {i}" for i in final_review.get("issues_found", []))
            ),
            data=data,
            artifacts=[str(output_path)],
        )

    return ToolResult(success=True, data=data, artifacts=[str(output_path)])
