"""Capability-aware multishot prompt compilation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib.multishot_prompt_builder import build_multishot_prompt
from lib.multishot_schemas import MultishotValidationError


@dataclass(frozen=True)
class PromptCompilation:
    prompt: str
    compiler_version: str


def compile_multishot_prompt(source: dict[str, Any], *, provider: str, model: str, settings: dict) -> PromptCompilation:
    if provider == "runway":
        operation = settings.get("operation", "image_to_video")
        if operation != "image_to_video":
            raise ValueError("Runway multishot prompt compiler currently supports image_to_video only")
        return PromptCompilation(prompt=_compile_runway_i2v(source), compiler_version="runway_i2v_v1")

    prompt = build_multishot_prompt(
        project_title=source["project_title"],
        request=source["request"],
        story=source["story"],
        character_bible=source["character_bible"],
        style_bible=source["style_bible"],
        shot=source["shot"],
        continuity_in=source["continuity_in"],
    )
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
