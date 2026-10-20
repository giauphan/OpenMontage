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
    script_sha256: str,
    visual_plan_sha256: str,
) -> Dict[str, Any]:
    """Resolve, validate, and build news_visual_assets.json manifest from plan and local files."""
    assets_manifest: Dict[str, Any] = {
        "version": "1.0",
        "script_sha256": script_sha256,
        "visual_plan_sha256": visual_plan_sha256,
        "assets": []
    }
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    seen_asset_ids = set()
    for beat in visual_plan.get("beats", []):
        beat_id = beat.get("id")
        for asset_id in beat.get("asset_ids", []):
            if asset_id in seen_asset_ids:
                # Update existing asset beat_ids
                for a in assets_manifest["assets"]:
                    if a["asset_id"] == asset_id and beat_id not in a["beat_ids"]:
                        a["beat_ids"].append(beat_id)
                continue

            # Look for local candidate in assets/visuals/
            found_file = None
            for ext in (".svg", ".png", ".jpg", ".jpeg", ".webp", ".mp4"):
                cand_name = f"{asset_id}{ext}"
                cand_path = visuals_dir / cand_name
                if cand_path.is_file():
                    found_file = f"assets/visuals/{cand_name}"
                    break

            if not found_file:
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
                else:
                    raise FileNotFoundError(
                        f"Asset {asset_id!r} required by beat {beat_id!r} not found in {visuals_dir}"
                    )

            ok, err, sha256 = validate_asset_file(project_dir, found_file)
            if not ok or sha256 is None:
                raise ValueError(f"Asset validation failed for {asset_id}: {err}")

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

            asset_record = {
                "asset_id": asset_id,
                "beat_ids": [beat_id],
                "kind": "svg_diagram" if found_file.endswith(".svg") else "authentic_photo",
                "file": found_file,
                "sha256": sha256,
                "mime": mime,
                "width": 960,
                "height": 540,
                "origin": "project-generated-verified-diagram" if found_file.endswith(".svg") else "local_authorized_source",
                "rights_status": "cleared_for_use",
                "credit": None,
                "claim_ids": beat.get("claim_ids", [])
            }
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
