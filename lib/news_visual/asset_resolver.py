"""Asset resolution, local staging, checksumming, and security validation."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
ASSETS_SCHEMA_PATH = ROOT / "schemas" / "news" / "news_visual_assets.schema.json"


def load_assets_schema() -> Dict[str, Any]:
    if not ASSETS_SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Missing schema file: {ASSETS_SCHEMA_PATH}")
    return json.loads(ASSETS_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_asset_file(project_dir: Path, rel_file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Validate that asset file exists inside project, is regular file, not symlink or escaping."""
    posix_path = PurePosixPath(rel_file_path)
    if posix_path.is_absolute() or ".." in posix_path.parts:
        return False, "Asset path is absolute or attempts path traversal", None

    candidate = project_dir / rel_file_path
    try:
        resolved_proj = project_dir.resolve(strict=True)
        resolved_cand = candidate.resolve(strict=True)
        resolved_cand.relative_to(resolved_proj)
    except (OSError, ValueError):
        return False, f"Asset file missing or escapes project directory: {rel_file_path}", None

    if candidate.is_symlink():
        return False, f"Asset file traverses a symbolic link: {rel_file_path}", None

    if not candidate.is_file() or candidate.stat().st_size == 0:
        return False, f"Asset file is missing or empty: {rel_file_path}", None

    sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return True, None, sha256


def resolve_visual_assets(
    project_dir: Path,
    visual_plan: Dict[str, Any],
    script_sha256: str = "",
    visual_plan_sha256: str = "",
    enforce_meaningful_visuals: bool = False,
) -> Dict[str, Any]:
    """Resolve, validate, and build news_visual_assets.json manifest from plan and local files."""
    assets_manifest: Dict[str, Any] = {
        "version": "1.0",
        "script_sha256": script_sha256 or "0" * 64,
        "visual_plan_sha256": visual_plan_sha256 or "0" * 64,
        "assets": []
    }
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    ai_generated_asset_ids = set()
    orch_path = project_dir / "artifacts" / "orchestrated_assets.json"
    if orch_path.is_file():
        try:
            orch_data = json.loads(orch_path.read_text(encoding="utf-8"))
            for item in orch_data.get("assets", []):
                if item.get("origin") == "ai_generated":
                    ai_generated_asset_ids.add(item.get("id"))
        except Exception:
            pass

    seen_asset_ids = set()
    fallback_asset_ids = set()
    for beat in visual_plan.get("beats", []):
        beat_id = beat.get("id") or beat.get("beat_id")
        asset_ids = beat.get("asset_ids", [])
        if not asset_ids and beat.get("asset_id"):
            asset_ids = [beat["asset_id"]]

        is_proof_bearing = bool(
            beat.get("is_proof_bearing")
            or beat.get("evidence_class") in ("authentic_proof", "conceptual_diagram", "primary_proof")
        )

        for asset_id in asset_ids:
            if asset_id in seen_asset_ids:
                if (enforce_meaningful_visuals or os.environ.get("FIXED_NICHE_MODE") == "1") and is_proof_bearing and asset_id in fallback_asset_ids:
                    from lib.fixed_niche.storyboard import MeaningfulVisualError
                    raise MeaningfulVisualError(
                        f"Placeholder SVG fallback forbidden for proof-bearing beat {beat_id!r} ({asset_id}). "
                        "A concrete explanatory graphic is required."
                    )
                # Update existing asset beat_ids
                for a in assets_manifest["assets"]:
                    if a["asset_id"] == asset_id and beat_id not in a["beat_ids"]:
                        a["beat_ids"].append(beat_id)
                continue

            # Look for local candidate in assets/visuals/
            found_file = None
            ext_order = (
                (".png", ".webp", ".jpg", ".jpeg", ".svg", ".mp4")
                if (beat.get("render_strategy") == "ai_illustration_eligible" or beat.get("visual_kind") == "illustration")
                else (".svg", ".png", ".jpg", ".jpeg", ".webp", ".mp4")
            )
            for ext in ext_order:
                cand_name = f"{asset_id}{ext}"
                cand_path = visuals_dir / cand_name
                if cand_path.is_file():
                    found_file = f"assets/visuals/{cand_name}"
                    break

            if not found_file:
                if (enforce_meaningful_visuals or os.environ.get("FIXED_NICHE_MODE") == "1") and is_proof_bearing:
                    from lib.fixed_niche.storyboard import MeaningfulVisualError
                    raise MeaningfulVisualError(
                        f"Placeholder SVG fallback forbidden for proof-bearing beat {beat_id!r} ({asset_id}). "
                        "A concrete explanatory graphic is required."
                    )

                # If diagram or icon, generate built-in deterministic fallback if allowed
                kind = beat.get("visual_kind", "svg_diagram")
                fallback_policy = beat.get("fallback_policy", "use_builtin_verified_icon_diagram")
                if fallback_policy == "use_builtin_verified_icon_diagram" and kind in ("svg_diagram", "contextual_icon", "illustration"):
                    cand_name = f"{asset_id}.svg"
                    cand_path = visuals_dir / cand_name
                    # Write deterministic fallback SVG
                    svg_content = (
                        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540">\n'
                        f'  <rect width="960" height="540" rx="24" fill="#0f172a" stroke="#38bdf8" stroke-width="3"/>\n'
                        f'  <text x="480" y="270" fill="#38bdf8" font-family="BeVietnamPro, sans-serif" font-size="36" '
                        f'font-weight="bold" text-anchor="middle" dominant-baseline="middle">'
                        f'{beat.get("story_function", asset_id).upper()}'
                        f'</text>\n'
                        f'</svg>'
                    )
                    cand_path.write_text(svg_content, encoding="utf-8")
                    found_file = f"assets/visuals/{cand_name}"
                    fallback_asset_ids.add(asset_id)
                else:
                    raise FileNotFoundError(
                        f"Asset {asset_id!r} required by beat {beat_id!r} not found in {visuals_dir}"
                    )

            ok, err, sha256 = validate_asset_file(project_dir, found_file)
            if not ok or sha256 is None:
                raise ValueError(f"Asset validation failed for {asset_id}: {err}")

            # Probe actual image dimensions and MIME
            real_width = 960
            real_height = 540
            if found_file.endswith((".png", ".jpg", ".jpeg", ".webp")):
                try:
                    from PIL import Image
                    with Image.open(project_dir / found_file) as img:
                        real_width, real_height = img.size
                except Exception:
                    pass

            # Determine MIME
            mime, _ = mimetypes.guess_type(found_file)
            if not mime:
                if found_file.endswith(".svg"):
                    mime = "image/svg+xml"
                elif found_file.endswith(".png"):
                    mime = "image/png"
                elif found_file.endswith(".jpg") or found_file.endswith(".jpeg"):
                    mime = "image/jpeg"
                elif found_file.endswith(".webp"):
                    mime = "image/webp"
                else:
                    mime = "application/octet-stream"

            # Determine kind and origin
            beat_kind = beat.get("visual_kind")
            beat_ev_class = beat.get("evidence_class")
            beat_strategy = beat.get("render_strategy")

            if orch_path.is_file():
                is_ai_art = (asset_id in ai_generated_asset_ids) and not found_file.endswith(".svg")
            else:
                is_ai_art = (
                    asset_id.startswith("art_")
                    or (beat_kind == "illustration" and beat_ev_class == "illustration")
                    or beat_strategy == "ai_illustration_eligible"
                ) and not found_file.endswith(".svg")

            if is_ai_art:
                kind = "illustration"
                origin = "ai_generated"
                rights_status = "in_house_illustration"
            elif found_file.endswith(".svg"):
                kind = "svg_diagram" if beat_kind not in ("svg_diagram", "contextual_icon") else beat_kind
                origin = "project-generated-verified-diagram"
                rights_status = "cleared_for_use"
            else:
                kind = beat_kind if beat_kind in ("authentic_photo", "source_screenshot", "chart") else "authentic_photo"
                origin = "local_authorized_source"
                rights_status = "cleared_for_use"

            asset_record = {
                "asset_id": asset_id,
                "beat_ids": [beat_id],
                "kind": kind,
                "file": found_file,
                "sha256": sha256,
                "mime": mime,
                "width": real_width,
                "height": real_height,
                "origin": origin,
                "rights_status": rights_status,
                "credit": None,
                "claim_ids": beat.get("claim_ids", []),
            }
            if is_ai_art:
                asset_record["ai_generated"] = True
                asset_record["provider"] = "muse"
                asset_record["model"] = "muse-image"

            assets_manifest["assets"].append(asset_record)
            seen_asset_ids.add(asset_id)

    # Validate against schema
    schema = load_assets_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(assets_manifest), key=lambda e: list(e.path))
    if errors:
        msg = "; ".join(f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors)
        raise ValueError(f"Visual assets manifest failed schema validation: {msg}")

    return assets_manifest


# Alias for compatibility with fixed niche pipeline
resolve_assets_for_plan = resolve_visual_assets

