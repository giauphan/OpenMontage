"""Provider-specific prompt compilers for multi-shot video generation.

Translates canonical shot plans and multi-shot context into optimized,
provider-compliant prompt payloads without mutating core pipeline state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from lib.multishot_schemas import MultishotValidationError


@dataclass(frozen=True)
class PromptCompilation:
    prompt: str
    compiler_version: str


def compile_kling_prompt(context: dict[str, Any]) -> str:
    """Compile a prompt optimized for Kling official (Classic/Omni)."""
    from lib.multishot_prompt_builder import build_multishot_prompt
    # Kling expects clear narrative action, character locks, and formal structure
    return build_multishot_prompt(**context)


def compile_runway_prompt(context: dict[str, Any]) -> str:
    """Compile a prompt optimized for Runway (Seedance 2.0 / Gen-4).

    Runway Gen-4 / Seedance I2V models focus on camera movement, action, and
    temporal continuity while relying on reference images for character identity.
    """
    from lib.multishot_prompt_builder import build_multishot_prompt
    # Use base build_multishot_prompt with Runway-tuned negative constraints
    runway_negatives = [
        "no morphing",
        "no jitter",
        "no sudden character swaps",
        "stable cinematic motion",
    ]
    return build_multishot_prompt(
        provider_specific_negative_constraints=runway_negatives,
        **context,
    )


def compile_prompt(provider: str, context: dict[str, Any]) -> str:
    """Compile a prompt tailored to the requested video generation provider."""
    if provider == "kling_official":
        return compile_kling_prompt(context)
    elif provider in {"runway", "seedance_video"}:
        return compile_runway_prompt(context)
    else:
        from lib.multishot_prompt_builder import build_multishot_prompt
        return build_multishot_prompt(**context)


def compile_multishot_prompt(source: dict[str, Any], *, provider: str, model: str, settings: dict) -> PromptCompilation:
    if provider == "runway":
        operation = settings.get("operation", "image_to_video")
        if operation != "image_to_video":
            raise ValueError("Runway multishot prompt compiler currently supports image_to_video only")
        return PromptCompilation(prompt=_compile_runway_i2v(source), compiler_version="runway_i2v_v1")

    prompt = compile_prompt(provider, {
        "project_title": source["project_title"],
        "request": source["request"],
        "story": source["story"],
        "character_bible": source["character_bible"],
        "style_bible": source["style_bible"],
        "shot": source["shot"],
        "continuity_in": source["continuity_in"],
    })
    return PromptCompilation(prompt=prompt, compiler_version="generic_multishot_v1")


def _compile_runway_i2v(source: dict[str, Any]) -> str:
    shot = source["shot"]
    style = source["style_bible"]
    character_bible = source["character_bible"]
    continuity = source.get("continuity_in") or {}

    characters = []
    for char_id in shot.get("characters", []):
        match = next((c for c in character_bible.get("characters", []) if c.get("id") == char_id), None)
        if match:
            identity = match.get("locked_identity", {})
            characters.append(
                ", ".join(str(v) for v in identity.values() if isinstance(v, str))
            )
    identity_text = "; ".join(filter(None, characters)) or "preserve the reference character identity"
    visual_style = style.get("visual_style") or "cinematic animation"
    action = shot.get("action") or "continue the planned action"
    camera = shot.get("camera") or ", ".join(style.get("camera_language", [])[:1]) or "natural camera movement"
    end_state = shot.get("end_state") or {}
    end_text = end_state if isinstance(end_state, str) else ", ".join(str(v) for v in end_state.values())
    continuity_text = continuity.get("accepted_end_state") or continuity.get("character_state") or "match the provided reference frame"
    if isinstance(continuity_text, dict):
        continuity_text = ", ".join(str(v) for v in continuity_text.values())

    prompt = (
        f"{visual_style}. "
        f"Preserve identity: {identity_text}. "
        f"Motion: {action}; continue naturally from {continuity_text}. "
        f"Camera: {camera}. "
        f"End frame: {end_text or 'clean readable pose for the next shot'}."
    )
    if "no " in prompt.lower() or "negative" in prompt.lower():
        raise MultishotValidationError("Runway prompt compiler produced negative wording")
    words = prompt.split()
    if len(words) > 90:
        prompt = " ".join(words[:90]).rstrip(" ,;") + "."
    return prompt


def prompt_hash_for_provider(
    provider: str,
    prompt: str,
    *,
    model: str = "",
    settings: dict | None = None,
    reference_hashes: list[str] | None = None,
) -> str:
    """Return the exact prompt_hash representation required by the provider."""
    if provider == "kling_official":
        return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    from lib.multishot_jobs import canonical_input_hash
    return canonical_input_hash(
        provider=provider,
        model=model,
        settings=settings if settings is not None else {},
        prompt=prompt,
        reference_hashes=reference_hashes if reference_hashes is not None else [],
    )
