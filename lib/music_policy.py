"""Copyright and platform policy checks for video music."""

from __future__ import annotations

from typing import Any

SOCIAL_PLATFORMS = {"youtube", "tiktok", "instagram"}
SOCIAL_LOUDNESS_LUFS = -14.0

# Free-first provider order. Each entry is (tool_name, license, needs_key).
# pixabay_music is first because it is free, needs no API key, and its license
# permits commercial use with no attribution.
PROVIDER_PRIORITY = (
    ("music_library", "Commercial License", False),
    ("pixabay_music", "Pixabay Content License", False),
    ("music_gen", "AI Generated Original", True),
)

# Mood keywords mapped to a search query for stock providers. Keyed on the
# renderer_family / emotional tone already present in the pipeline artifacts so
# the agent does not need to invent a prompt.
MOOD_QUERIES = {
    "explainer-data": "corporate ambient background instrumental",
    "explainer-teacher": "calm soft piano background instrumental",
    "cinematic-trailer": "epic cinematic tension instrumental",
    "documentary-montage": "documentary reflective strings instrumental",
    "product-reveal": "upbeat modern tech instrumental",
    "screen-demo": "minimal light background instrumental",
    "presenter": "soft neutral background instrumental",
    "animation-first": "playful light electronic instrumental",
}
DEFAULT_MOOD_QUERY = "calm ambient background instrumental"

# Explicitly accepted license labels. Unknown licenses must stop a render.
ALLOWED_LICENSES = {
    "Pixabay Content License",
    "CC0",
    "CC BY",
    "AI Generated Original",
}

# Downloaded stock tracks need a source URL for later claim/dispute handling.
# Generated music has no source page; it carries license_url instead.
URL_LICENSES = {"Pixabay Content License", "CC BY"}


def target_platforms(edit_decisions: dict[str, Any]) -> set[str]:
    """Return normalized target platforms, defaulting to requested social set."""
    metadata = edit_decisions.get("metadata") or {}
    raw = metadata.get("target_platforms", metadata.get("target_platform"))
    if isinstance(raw, str):
        raw = [raw]
    platforms = {str(value).strip().lower() for value in (raw or SOCIAL_PLATFORMS)}
    return platforms & SOCIAL_PLATFORMS


def select_music_provider(available_tools: set[str] | None = None) -> tuple[str, str] | None:
    """Return the highest-priority free music provider available.

    ``available_tools`` is the set of tool names the stage may use (from the
    pipeline manifest ``tools_available``). Returns ``(tool_name, license)`` or
    ``None`` when no music source is configured, which the agent must surface to
    the user rather than rendering silently.
    """
    if available_tools is None:
        return None
    for tool_name, license_name, _needs_key in PROVIDER_PRIORITY:
        if tool_name in available_tools:
            return tool_name, license_name
    return None


def music_query_for(renderer_family: str | None) -> str:
    """Map a locked renderer_family to a stock-music search query."""
    if not renderer_family:
        return DEFAULT_MOOD_QUERY
    return MOOD_QUERIES.get(renderer_family, DEFAULT_MOOD_QUERY)


def validate_music_policy(
    asset_manifest: dict[str, Any] | None,
    edit_decisions: dict[str, Any],
) -> list[str]:
    """Return blocking music-policy errors for a manifest/edit pair."""
    if not asset_manifest:
        return []

    errors: list[str] = []
    music_assets = [
        asset for asset in asset_manifest.get("assets", [])
        if asset.get("type") == "music"
    ]
    for asset in music_assets:
        asset_id = asset.get("id", "<unnamed>")
        license_name = asset.get("license")
        if license_name not in ALLOWED_LICENSES:
            errors.append(
                f"Music asset {asset_id!r} has unsupported license "
                f"{license_name!r}; use an approved license or remove it."
            )
        if license_name in URL_LICENSES and not asset.get("original_url"):
            errors.append(
                f"Music asset {asset_id!r} requires original_url for "
                f"{license_name}."
            )
        if not asset.get("provider"):
            errors.append(f"Music asset {asset_id!r} is missing provider provenance.")
        if license_name == "CC BY" and not asset.get("attribution_text"):
            errors.append(f"Music asset {asset_id!r} requires attribution_text for CC BY.")
        if license_name == "AI Generated Original" and not asset.get("license_url"):
            errors.append(
                f"Music asset {asset_id!r} requires license_url with provider "
                "commercial-use terms."
            )

    if music_assets and target_platforms(edit_decisions):
        metadata = edit_decisions.get("metadata") or {}
        loudness = metadata.get("loudnorm_target", SOCIAL_LOUDNESS_LUFS)
        try:
            loudness = float(loudness)
        except (TypeError, ValueError):
            errors.append("metadata.loudnorm_target must be -14 LUFS for social platforms.")
        else:
            if loudness != SOCIAL_LOUDNESS_LUFS:
                errors.append(
                    "metadata.loudnorm_target must be -14 LUFS for YouTube, TikTok, "
                    "and Instagram."
                )

        music_config = (edit_decisions.get("audio") or {}).get("music") or {}
        ducking = music_config.get("ducking", True)
        if ducking is False or (isinstance(ducking, dict) and ducking.get("enabled") is False):
            errors.append("Music ducking must be enabled when social narration is present.")

    return errors
