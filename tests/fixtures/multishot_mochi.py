"""Six-shot Mochi fixture — the canonical multi-shot E2E acceptance plan.

A funny orange cat (Mochi) tries to cook noodles. 9:16, 1080x1920, 30 fps,
30 seconds. This fixture is used by M1+ tests and the E2E-01 acceptance test.
"""

from __future__ import annotations

from copy import deepcopy

REQUEST = {
    "topic": "A funny orange cat Mochi tries to cook noodles",
    "target_duration_sec": 30,
    "language": "vi",
    "aspect_ratio": "9:16",
    "resolution": {"width": 1080, "height": 1920},
    "fps": 30,
    "shot_policy": {"min_shots": 2, "max_shots": 8,
                    "preferred_min_duration_sec": 4, "preferred_max_duration_sec": 6},
    "audio": {"narration": True, "music": True, "sfx": True, "subtitles": True},
}

STORY = {
    "version": "1.0",
    "title": "Mochi Cooking Disaster",
    "topic": "Funny cooking animation",
    "summary": "Mochi confidently cooks noodles, causes escalating chaos, then discovers the simple instructions too late.",
    "beats": [
        {"id": "beat_01", "type": "hook", "summary": "Mochi confidently starts cooking."},
        {"id": "beat_02", "type": "escalation", "summary": "Mistakes make the kitchen increasingly chaotic."},
        {"id": "beat_03", "type": "climax", "summary": "The flour storm peaks and the kitchen is wrecked."},
        {"id": "beat_04", "type": "resolution", "summary": "Mochi finds the one-step instructions, too late."},
        {"id": "beat_05", "type": "punchline", "summary": "Mochi eats the packet dry, unimpressed."},
    ],
    "characters": ["Mochi"],
    "locations": ["Kitchen"],
    "important_props": ["instant noodle packet", "pot", "flour bag", "instruction card"],
}

CHARACTER_BIBLE = {
    "version": "1.0",
    "characters": [
        {
            "id": "char_mochi",
            "name": "Mochi",
            "role": "main",
            "locked_identity": {
                "type": "chubby orange cartoon cat",
                "body": "round body, short legs, tiny paws",
                "face": "round face",
                "eyes": "large green eyes",
                "fur": "orange with cream belly and muzzle",
                "markings": "consistent orange stripes",
                "clothing": ["oversized white chef hat", "small red apron"],
            },
            "personality": ["overconfident", "clumsy", "curious", "dramatic"],
            "motion_style": ["exaggerated reactions", "squash and stretch", "expressive tail"],
            "forbidden_changes": [
                "do not change eye color",
                "do not change fur color",
                "do not change body proportions",
            ],
        }
    ],
}

STYLE_BIBLE = {
    "version": "1.0",
    "visual_style": "high-quality colorful 3D cartoon animation",
    "lighting": "bright warm cinematic lighting",
    "camera_language": ["reaction close-ups", "medium comedy shots", "wide shots for chaos"],
    "motion": ["continuous visible movement", "squash and stretch", "secondary motion"],
    "color": "bright cheerful saturated palette",
    "render_rules": [
        "consistent character identity",
        "consistent environment layout",
        "no flickering",
        "no character morphing",
        "no duplicated limbs",
        "no watermark",
        "no logo",
    ],
}


def _shot(order: int, action: str, start_state: dict, end_state: dict,
          expression: str = "", camera: str = "medium close-up",
          motion: str = "fast paw movement", props: list | None = None) -> dict:
    shot_id = f"shot_{order:03d}"
    return {
        "id": shot_id,
        "scene_id": f"scene_{order:02d}",
        "order": order,
        "duration_sec": 5,
        "location": "Kitchen",
        "characters": ["char_mochi"],
        "start_state": start_state,
        "action": action,
        "expression": expression,
        "camera": camera,
        "motion": motion,
        "props": props or ["instant noodle packet"],
        "end_state": end_state,
        "transition_out": "hard_cut",
    }


def shot_plan() -> dict:
    """Return a deep-copied, fresh six-shot Mochi plan."""
    return deepcopy({
        "version": "1.0",
        "target_duration_sec": 30,
        "shots": [
            _shot(1, "Mochi confidently slams a noodle packet onto the counter.",
                  {"character": "Mochi clean, chef hat straight", "environment": "clean kitchen"},
                  {"character": "Mochi surprised by a popping pot lid", "environment": "kitchen still clean",
                   "props": {"pot": "lid lifted briefly"}}),
            _shot(2, "Mochi dumps an extra-large spoon of chili in.",
                  {"character": "Mochi focused", "environment": "clean kitchen"},
                  {"character": "Mochi overconfident", "environment": "counter slightly messy"}),
            _shot(3, "Mochi flips the pot too hard; flour bursts open.",
                  {"character": "Mochi triumphant", "environment": "counter messy"},
                  {"character": "Mochi dusted in flour", "environment": "kitchen dusty",
                   "props": {"flour_bag": "burst open"}}),
            _shot(4, "Mochi tries to stir but makes the mess worse.",
                  {"character": "Mochi embarrassed", "environment": "dusty kitchen"},
                  {"character": "Mochi flustered", "environment": "kitchen very messy"}),
            _shot(5, "Mochi finds the instruction card: one step only.",
                  {"character": "Mochi panicked", "environment": "kitchen wrecked"},
                  {"character": "Mochi deflating", "environment": "kitchen wrecked"}),
            _shot(6, "Mochi eats the packet dry and winks at the camera.",
                  {"character": "Mochi resigned", "environment": "kitchen wrecked"},
                  {"character": "Mochi unimpressed content", "environment": "kitchen wrecked"}),
        ],
    })


def initial_continuity() -> dict:
    """The continuity state bound to shot 1."""
    return {
        "version": 1,
        "accepted_through_shot": None,
        "character_state": {},
        "environment_state": {"kitchen": "clean"},
        "object_state": {},
    }


def continuity_snapshot_for(shot_order: int) -> dict:
    """Return the continuity_in for a given shot order.

    Shot 1 uses the documented initial state. Later shots use an accepted
    state advanced up to the predecessor order.
    """
    if shot_order == 1:
        return initial_continuity()
    return {
        "version": shot_order - 1,
        "accepted_through_shot": f"shot_{shot_order - 1:03d}",
        "character_state": {"char_mochi": "messy"},
        "environment_state": {"kitchen": "messy"},
        "object_state": {},
    }


def all_project_data() -> dict:
    """Return a full, consistent six-shot Mochi project bundle."""
    return {
        "project_title": "Mochi Cooking Disaster",
        "request": deepcopy(REQUEST),
        "story": deepcopy(STORY),
        "character_bible": deepcopy(CHARACTER_BIBLE),
        "style_bible": deepcopy(STYLE_BIBLE),
        "shot_plan": shot_plan(),
    }
