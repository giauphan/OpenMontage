"""Reference and keyframe manager for the multi-shot pipeline.

Tracks provenance and content hashes for:
  - the master character reference (one per character)
  - the optional environment reference
  - one keyframe per shot

Generation of a shot's video is blocked when a required reference is absent
or its owning shot does not match. A changed reference content hash
invalidates the dependent video job.

No provider calls and no orchestration; pure bookkeeping on dicts and
filesystem paths.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from lib.multishot_schemas import MultishotValidationError

KEY_CHARACTER_MASTER = "character_master"
KEY_ENVIRONMENT = "environment"
KEY_SHOT_KEYFRAME = "keyframe"


def content_hash(path: Path) -> str:
    """Return the sha256 content hash of a readable image file."""
    if not Path(path).is_file():
        raise MultishotValidationError(f"Reference file not found: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError) as exc:
        raise MultishotValidationError(f"Reference file is not a readable image: {path}") from exc
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def new_reference_store() -> dict[str, Any]:
    """Return an empty reference store dict."""
    return {"references": {}, "shots": {}}


def register_character_master(
    store: dict[str, Any],
    character_id: str,
    path: Path,
) -> dict[str, Any]:
    """Register (or replace) the master reference for a character."""
    master_hash = content_hash(path)
    record = {
        "kind": KEY_CHARACTER_MASTER,
        "owner": character_id,
        "path": str(path),
        "content_hash": master_hash,
    }
    store["references"][f"character_master:{character_id}"] = record
    return record


def register_environment_reference(
    store: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    """Register (or replace) the single environment reference."""
    record = {
        "kind": KEY_ENVIRONMENT,
        "owner": None,
        "path": str(path),
        "content_hash": content_hash(path),
    }
    store["references"][KEY_ENVIRONMENT] = record
    return record


def register_shot_keyframe(
    store: dict[str, Any],
    shot_id: str,
    path: Path,
    *,
    derived_from_character: Optional[str] = None,
    derived_from_characters: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Register or replace the keyframe owned by a single shot.

    ``derived_from_character`` records the provenance key for one-reference
    providers that derive the shot keyframe from the character master.
    ``derived_from_characters`` handles multi-character provenance.
    """
    keyframe_hash = content_hash(path)

    char_hashes = {}
    if derived_from_character:
        char_hashes[derived_from_character] = store["references"].get(f"character_master:{derived_from_character}", {}).get("content_hash")
    if derived_from_characters:
        for char in derived_from_characters:
            char_hashes[char] = store["references"].get(f"character_master:{char}", {}).get("content_hash")

    record = {
        "kind": KEY_SHOT_KEYFRAME,
        "owner": shot_id,
        "path": str(path),
        "content_hash": keyframe_hash,
        "derived_from_character": derived_from_character,
        "derived_from_characters": list(char_hashes.keys()) if char_hashes else None,
        "derived_from_character_hash": (
            store["references"].get(f"character_master:{derived_from_character}", {}).get("content_hash")
            if derived_from_character else None
        ),
        "derived_from_character_hashes": char_hashes if char_hashes else None,
    }
    store["references"][f"keyframe:{shot_id}"] = record
    store["shots"].setdefault(shot_id, {"keyframe": record["content_hash"]})
    return record


def shot_keyframe(store: dict[str, Any], shot_id: str) -> Optional[dict[str, Any]]:
    """Return the keyframe record for a shot, or None when absent."""
    return store["references"].get(f"keyframe:{shot_id}")


def generation_reference_keys(
    shot: dict[str, Any],
    character_bible: dict[str, Any],
    *,
    supports_environment: bool,
) -> list[str]:
    """Return the reference keys that must be present before generation.

    A character-driven shot requires its keyframe. A single-reference provider
    derives that keyframe from the character master; a multi-reference
    provider may also consume the environment reference.
    """
    keys = []
    char_ids = shot.get("characters", [])
    if not char_ids:
        raise MultishotValidationError(
            f"Shot {shot.get('id')} has no characters; cannot resolve references"
        )
    known = {c["id"] for c in character_bible.get("characters", [])}
    for char_id in char_ids:
        if char_id not in known:
            raise MultishotValidationError(
                f"Shot {shot.get('id')} references unknown character {char_id!r}"
            )
        # Instead of appending multiple times, just ensure it's in the list
    if f"keyframe:{shot['id']}" not in keys:
        keys.append(f"keyframe:{shot['id']}")
    if supports_environment:
        keys.append(KEY_ENVIRONMENT)
    return keys


def validate_generation_ready(
    store: dict[str, Any],
    shot: dict[str, Any],
    character_bible: dict[str, Any],
    *,
    supports_environment: bool = False,
) -> list[str]:
    """Block generation when a required reference is absent or mismatched.

    Returns the list of required reference keys that are present. Raises
    ``MultishotValidationError`` for the first missing or mismatched ref.
    """
    required = generation_reference_keys(shot, character_bible, supports_environment=supports_environment)
    present: list[str] = []

    # In order to return unique reference keys without disrupting the loop
    # We will build a unique list. Note that generation_reference_keys may contain duplicates
    # since keyframe:{shot_id} is appended for each character, but we only validate it once per unique key.

    # Actually generation_reference_keys appending keyframe:{shot["id"]} per character
    # creates multiple same elements. Let's fix that uniqueness logic.
    unique_required = []
    for k in required:
        if k not in unique_required:
            unique_required.append(k)

    for key in unique_required:
        record = store["references"].get(key)
        if record is None:
            raise MultishotValidationError(
                f"Generation blocked for shot {shot.get('id')}: required "
                f"reference {key!r} is absent"
            )
        owner = record.get("owner")
        if key.startswith("keyframe:"):
            if owner != shot.get("id"):
                raise MultishotValidationError(
                    f"Generation blocked for shot {shot.get('id')}: keyframe owner "
                    f"is {owner!r}"
                )
            path = Path(record["path"])
            if content_hash(path) != record.get("content_hash"):
                raise MultishotValidationError(
                    f"Generation blocked for shot {shot.get('id')}: keyframe content changed"
                )

            # Verify that provenance covers all required characters.
            char_ids = shot.get("characters", [])
            derived_chars = record.get("derived_from_characters") or []
            if record.get("derived_from_character") and record.get("derived_from_character") not in derived_chars:
                derived_chars.append(record.get("derived_from_character"))

            for char_id in char_ids:
                if char_id not in derived_chars:
                    raise MultishotValidationError(
                        f"Generation blocked for shot {shot.get('id')}: keyframe provenance missing character {char_id}"
                    )

            # Check masters
            hashes = record.get("derived_from_character_hashes") or {}

            for character_id in derived_chars:
                master = store["references"].get(f"character_master:{character_id}")

                 # Fallback logic for derived_from_character_hash
                expected_hash = hashes.get(character_id)
                if expected_hash is None and character_id == record.get("derived_from_character"):
                    expected_hash = record.get("derived_from_character_hash")

                if (
                    master is None
                    or master.get("content_hash") != expected_hash
                    or content_hash(Path(master["path"])) != master.get("content_hash")
                ):
                    raise MultishotValidationError(
                        f"Generation blocked for shot {shot.get('id')}: master provenance changed"
                    )
                # Verify master ownership
                if master.get("owner") != character_id:
                    raise MultishotValidationError(
                        f"Generation blocked for shot {shot.get('id')}: master owner is not {character_id}"
                    )

        elif content_hash(Path(record["path"])) != record.get("content_hash"):
            raise MultishotValidationError(
                f"Generation blocked for shot {shot.get('id')}: reference content changed"
            )
        present.append(key)
    return present


def invalidate_dependent_jobs(
    store: dict[str, Any],
    reference_key: str,
) -> set[str]:
    """Return shot ids whose keyframe depends on the named reference.

    A master-character reference change invalidates every shot keyframe
    derived from it; a single keyframe change invalidates only its shot.
    """
    if reference_key.startswith("character_master:"):
        character_id = reference_key.split(":", 1)[1]
        stale = {
            shot_id for shot_id in store.get("shots", {})
            if _keyframe_derived_from(store, shot_id, character_id)
        }
        return stale
    if reference_key.startswith("keyframe:"):
        shot_id = reference_key.split(":", 1)[1]
        return {shot_id} if shot_id in store.get("shots", {}) else set()
    return set()


def _keyframe_derived_from(store: dict[str, Any], shot_id: str, character_id: str) -> bool:
    record = shot_keyframe(store, shot_id)
    if not record:
        return False
    if record.get("derived_from_character") == character_id:
        return True
    if record.get("derived_from_characters") and character_id in record.get("derived_from_characters", []):
        return True
    return False


def reference_changed(
    before: dict[str, Any],
    after: dict[str, Any],
    reference_key: str,
) -> bool:
    """True when a named reference's content hash changed between two stores."""
    old = before.get("references", {}).get(reference_key, {}).get("content_hash")
    new = after.get("references", {}).get(reference_key, {}).get("content_hash")
    return old != new
