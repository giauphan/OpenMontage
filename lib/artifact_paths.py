"""Locale- and rendition-aware canonical artifact path resolver for OpenMontage.

Eliminates hardcoded `script_vi.json` and `final_reels_vi_9x16.mp4` paths while
retaining strict backwards compatibility for legacy Vietnamese projects.
Enforces the safety invariant: no permissive fallback accepting a VN artifact as EN.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_LOCALE = "vi-VN"


def resolve_project_locale(
    project_dir: str | Path,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Identify the target content locale for a project workspace.

    Precedence:
    1. Explicit `locale` or `spoken_language` in passed `metadata`.
    2. Explicit profile marker (e.g. `audience_profile_id` starting with `en-us`).
    3. `project.json` in project directory.
    4. `publish_metadata.json` in project directory.
    5. Content presence: presence of `artifacts/script_en_US.json` resolves `en-US`.
    6. Presence of `artifacts/script_vi.json` resolves `vi-VN`.
    7. Environment variable `OPENMONTAGE_LOCALE` if set.
    8. Default to `vi-VN` for existing legacy projects.
    """
    if metadata:
        locale = metadata.get("locale") or metadata.get("spoken_language")
        if locale:
            return _normalize_locale(locale)
        profile_id = str(metadata.get("audience_profile_id") or metadata.get("profile_id") or "")
        if "en-us" in profile_id.lower():
            return "en-US"
        if "vi-vn" in profile_id.lower():
            return "vi-VN"

    try:
        root = Path(project_dir).resolve()
    except (ValueError, RuntimeError):
        return _default_or_env()

    # Check project.json
    project_json = (root / "project.json").resolve()
    if project_json.parent == root and project_json.is_file():
        try:
            with open(project_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                loc = data.get("locale") or data.get("spoken_language")
                if loc:
                    return _normalize_locale(loc)
                prof = str(data.get("audience_profile_id") or data.get("profile_id") or "")
                if "en-us" in prof.lower():
                    return "en-US"
                if "vi-vn" in prof.lower():
                    return "vi-VN"
        except Exception:
            pass

    # Check publish_metadata.json
    pub_meta = (root / "publish_metadata.json").resolve()
    if pub_meta.parent == root and pub_meta.is_file():
        try:
            with open(pub_meta, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                loc = data.get("locale") or data.get("spoken_language")
                if loc:
                    return _normalize_locale(loc)
        except Exception:
            pass

    # Inspect disk artifacts
    artifacts_dir = root / "artifacts"
    if (artifacts_dir / "script_en_US.json").is_file():
        return "en-US"
    if (artifacts_dir / "script_vi.json").is_file():
        return "vi-VN"

    env_locale = os.environ.get("OPENMONTAGE_LOCALE")
    if env_locale:
        return _normalize_locale(env_locale)

    return DEFAULT_LOCALE


def _normalize_locale(locale: str) -> str:
    cleaned = locale.strip()
    lower = cleaned.lower()
    if lower in ("en", "en-us", "en_us", "us"):
        return "en-US"
    if lower in ("vi", "vi-vn", "vi_vn", "vn"):
        return "vi-VN"
    return cleaned


def is_english_locale(locale: str) -> bool:
    return _normalize_locale(locale).startswith("en")


def resolve_script_path(
    project_dir: str | Path,
    locale: str | None = None,
    must_exist: bool = False,
) -> Path:
    """Return the canonical script JSON path for the specified or detected locale."""
    root = Path(project_dir)
    loc = _normalize_locale(locale) if locale else resolve_project_locale(root)
    artifacts = root / "artifacts"

    if is_english_locale(loc):
        candidate = artifacts / "script_en_US.json"
        if not candidate.is_file() and (artifacts / "script.json").is_file():
            # Standard agent canonical script is permitted if no script_en_US
            candidate = artifacts / "script.json"
    else:
        candidate = artifacts / "script_vi.json"
        if not candidate.is_file() and (artifacts / "script.json").is_file():
            candidate = artifacts / "script.json"

    if must_exist and not candidate.is_file():
        raise FileNotFoundError(
            f"Canonical script not found at {candidate} for locale {loc}. "
            f"(Permissive fallback to another language is strictly disallowed)."
        )
    return candidate


def resolve_narration_text_path(
    project_dir: str | Path,
    locale: str | None = None,
) -> Path:
    """Return the canonical flat narration text path."""
    root = Path(project_dir)
    loc = _normalize_locale(locale) if locale else resolve_project_locale(root)
    artifacts = root / "artifacts"
    if is_english_locale(loc):
        return artifacts / "narration_en_US_text.txt"
    return artifacts / "narration_vi_text.txt"


def resolve_render_paths(
    project_dir: str | Path,
    locale: str | None = None,
) -> tuple[Path, Path]:
    """Return tuple of (full_render_path, reels_render_path)."""
    full = resolve_render_path(project_dir, format_type="full", locale=locale)
    reels = resolve_render_path(project_dir, format_type="reels", locale=locale)
    return full, reels


def resolve_render_path(
    project_dir: str | Path,
    format_type: str = "short",
    locale: str | None = None,
) -> Path:
    """Return canonical output render path for format and locale."""
    root = Path(project_dir)
    loc = _normalize_locale(locale) if locale else resolve_project_locale(root)
    renders = root / "renders"

    fmt = format_type.lower()
    if is_english_locale(loc):
        if fmt in ("short", "shorts", "reels", "9x16"):
            return renders / "final_short_en_US_9x16.mp4"
        elif fmt in ("long", "longform", "16x9", "full"):
            return renders / "final_long_en_US_16x9.mp4"
        return renders / "final_short_en_US_9x16.mp4"
    else:
        if fmt in ("short", "shorts", "reels", "9x16"):
            return renders / "final_reels_vi_9x16.mp4"
        elif fmt in ("long", "longform", "16x9", "full"):
            return renders / "final_full_vi_9x16.mp4"
        return renders / "final_reels_vi_9x16.mp4"


def resolve_captions_path(
    project_dir: str | Path,
    format_type: str = "short",
    locale: str | None = None,
) -> Path:
    """Return canonical captions/subtitles path."""
    root = Path(project_dir)
    loc = _normalize_locale(locale) if locale else resolve_project_locale(root)
    captions = root / "assets" / "captions"

    if is_english_locale(loc):
        if format_type.lower() in ("long", "longform", "16x9"):
            return captions / "long_en_US.srt"
        return captions / "short_en_US.srt"
    else:
        if format_type.lower() in ("full", "longform", "16x9"):
            return captions / "full_vi.srt"
        return captions / "reels_vi.srt"
