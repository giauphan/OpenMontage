"""Self-contained continuity-aware prompts for multi-shot video shots.

Unlike ``lib.shot_prompt_builder``, which builds cinematography snippets from
scene plans, this module emits the complete stateless provider prompt required
by the multi-shot contract. Every shot carries its own project, identity,
style, environment, continuity input, action, ending state, and negatives.

The builder has no provider/API calls and does not mutate inputs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from lib.multishot_schemas import MultishotValidationError


_REQUIRED_SECTIONS = (
    "PROJECT:",
    "TOPIC:",
    "STORY SUMMARY:",
    "VISUAL STYLE:",
    "CHARACTER LOCK:",
    "ENVIRONMENT LOCK:",
    "CONSISTENCY RULES:",
    "CURRENT CONTINUITY STATE:",
    "CURRENT SHOT:",
    "ENDING FRAME / REQUIRED END STATE:",
    "NEGATIVE CONSTRAINTS:",
)
_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")

_DEFAULT_NEGATIVES = [
    "no character redesign",
    "no costume changes unless explicitly scripted",
    "no eye-color changes",
    "no duplicated limbs",
    "no extra fingers or paws",
    "no morphing",
    "no flicker",
    "no watermark",
    "no logos",
    "no unrelated background changes",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _character_entry(char_id: str, character_bible: dict) -> dict:
    for character in character_bible.get("characters", []):
        if character.get("id") == char_id:
            return character
    raise MultishotValidationError(
        f"Cannot build prompt: unknown character reference {char_id!r}"
    )


def _format_character_lock(characters: list[dict]) -> str:
    lines: list[str] = []
    for character in characters:
        identity = character["locked_identity"]
        lines.extend([
            f"Character ID: {character['id']}",
            f"Name: {character['name']}",
            f"Role: {character.get('role', 'supporting')}",
            f"Identity type: {identity['type']}",
            f"Body: {identity.get('body', '')}",
            f"Face: {identity.get('face', '')}",
            f"Eyes: {identity.get('eyes', '')}",
            f"Fur/skin: {identity.get('fur', '')}",
            f"Markings: {identity.get('markings', '')}",
            f"Clothing: {', '.join(identity.get('clothing', []))}",
            f"Personality: {', '.join(character.get('personality', []))}",
            f"Movement style: {', '.join(character.get('motion_style', []))}",
            f"Forbidden changes: {', '.join(character.get('forbidden_changes', []))}",
        ])
    return "\n".join(lines)


def _format_environment_lock(shot: dict, continuity: dict) -> str:
    location = shot.get("location", "unspecified location")
    environment_state = continuity.get("environment_state", {})
    return (
        f"Location: {location}\n"
        f"Established environment state: {_json(environment_state)}\n"
        "Preserve established layout, lighting direction, scale, and set dressing."
    )


def _format_continuity(continuity: dict) -> str:
    previous = continuity.get("accepted_through_shot")
    return (
        f"Continuity version: {continuity.get('version')}\n"
        f"Previous accepted shot: {previous if previous is not None else 'INITIAL STATE'}\n"
        f"Character state: {_json(continuity.get('character_state', {}))}\n"
        f"Environment state: {_json(continuity.get('environment_state', {}))}\n"
        f"Object state: {_json(continuity.get('object_state', {}))}"
    )


def build_multishot_prompt(
    *,
    project_title: str,
    request: dict[str, Any],
    story: dict[str, Any],
    character_bible: dict[str, Any],
    style_bible: dict[str, Any],
    shot: dict[str, Any],
    continuity_in: dict[str, Any],
    provider_specific_negative_constraints: list[str] | None = None,
) -> str:
    """Build one complete stateless prompt for one planned shot.

    Raises ``MultishotValidationError`` when a character lock is absent,
    continuity state is missing, required shot fields are absent, or the
    resulting prompt contains an unresolved template placeholder.
    """
    if not project_title.strip():
        raise MultishotValidationError("Prompt requires a non-empty project title")
    if not request.get("topic"):
        raise MultishotValidationError("Prompt requires request.topic")
    if not story.get("summary"):
        raise MultishotValidationError("Prompt requires story.summary")
    if not style_bible.get("visual_style"):
        raise MultishotValidationError("Prompt requires style_bible.visual_style")
    if not continuity_in:
        raise MultishotValidationError("Prompt requires explicit continuity_in state")

    shot_id = shot.get("id")
    duration = shot.get("duration_sec")
    if not shot_id or duration is None or duration <= 0:
        raise MultishotValidationError(
            "Prompt requires shot.id and positive shot.duration_sec"
        )
    if "start_state" not in shot or "end_state" not in shot:
        raise MultishotValidationError(
            f"Prompt requires start_state and end_state for {shot_id}"
        )

    char_ids = shot.get("characters", [])
    if not char_ids:
        raise MultishotValidationError(
            f"Prompt cannot be built without a character lock for {shot_id}"
        )
    characters = [_character_entry(char_id, character_bible) for char_id in char_ids]

    negatives = list(_DEFAULT_NEGATIVES)
    negatives.extend(style_bible.get("render_rules", []))
    negatives.extend(provider_specific_negative_constraints or [])
    negative_lines = "\n".join(f"- {item}" for item in dict.fromkeys(negatives))

    prompt = "\n\n".join([
        f"PROJECT:\n{project_title}",
        f"TOPIC:\n{request['topic']}",
        f"STORY SUMMARY:\n{story['summary']}",
        (
            "VISUAL STYLE:\n"
            f"{style_bible['visual_style']}\n"
            f"Lighting: {style_bible.get('lighting', '')}\n"
            f"Camera language: {', '.join(style_bible.get('camera_language', []))}\n"
            f"Motion: {', '.join(style_bible.get('motion', []))}\n"
            f"Color: {style_bible.get('color', '')}"
        ),
        f"CHARACTER LOCK:\n{_format_character_lock(characters)}",
        f"ENVIRONMENT LOCK:\n{_format_environment_lock(shot, continuity_in)}",
        "CONSISTENCY RULES:\n"
        "- Keep the exact same character identity.\n"
        "- Preserve body proportions, colors, face, eyes, markings, and clothing.\n"
        "- Preserve the established environment layout.\n"
        "- Preserve continuity state from previous accepted shots.\n"
        "- Do not introduce new characters or major props unless explicitly listed.\n"
        "- Do not silently repair or reset damage or mess from prior shots.",
        f"CURRENT CONTINUITY STATE:\n{_format_continuity(continuity_in)}",
        (
            "CURRENT SHOT:\n"
            f"Shot ID: {shot_id}\n"
            f"Order: {shot.get('order')}\n"
            f"Duration: {duration} seconds\n"
            f"Location: {shot.get('location', '')}\n"
            f"Action: {shot.get('action', '')}\n"
            f"Expression: {shot.get('expression', '')}\n"
            f"Camera: {shot.get('camera', '')}\n"
            f"Motion: {shot.get('motion', '')}\n"
            f"Props: {', '.join(shot.get('props', []))}\n"
            f"Start state: {_json(shot['start_state'])}"
        ),
        f"ENDING FRAME / REQUIRED END STATE:\n{_json(shot['end_state'])}",
        f"NEGATIVE CONSTRAINTS:\n{negative_lines}",
    ])

    missing = [section for section in _REQUIRED_SECTIONS if section not in prompt]
    unresolved = _PLACEHOLDER.findall(prompt)
    if missing:
        raise MultishotValidationError(
            f"Prompt missing required sections for {shot_id}: {missing}"
        )
    if unresolved:
        raise MultishotValidationError(
            f"Prompt has unresolved placeholders for {shot_id}: {unresolved}"
        )
    return prompt


def build_multishot_prompts(
    *,
    project_title: str,
    request: dict[str, Any],
    story: dict[str, Any],
    character_bible: dict[str, Any],
    style_bible: dict[str, Any],
    shot_plan: dict[str, Any],
    continuity_by_shot: dict[str, dict[str, Any]],
    provider_specific_negative_constraints: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build prompts in plan order without mutating any input artifact."""
    results = []
    for shot in sorted(shot_plan["shots"], key=lambda item: item["order"]):
        shot_id = shot["id"]
        if shot_id not in continuity_by_shot:
            raise MultishotValidationError(
                f"Missing continuity input for planned shot {shot_id}"
            )
        results.append({
            "shot_id": shot_id,
            "prompt": build_multishot_prompt(
                project_title=project_title,
                request=request,
                story=story,
                character_bible=character_bible,
                style_bible=style_bible,
                shot=shot,
                continuity_in=continuity_by_shot[shot_id],
                provider_specific_negative_constraints=provider_specific_negative_constraints,
            ),
        })
    return results
