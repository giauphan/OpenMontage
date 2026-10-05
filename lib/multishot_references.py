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

from lib.multishot_schemas import MultishotValidationError

KEY_CHARACTER_MASTER = "character_master"
KEY_ENVIRONMENT = "environment"
KEY_SHOT_KEYFRAME = "keyframe"


def content_hash(path: Path) -> str:
    """Return the sha256 content hash of a file, prefixed ``sha256:``."""
    if not Path(path).is_file():
        raise MultishotValidationError(f"Reference file not found: {path}")
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
    record = {
        "kind": KEY_CHARACTER_MASTER,
        "owner": character_id,
        "path": str(path),
        "content_hash": content_hash(path),
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
) -> dict[str, Any]:
    """Register or replace the keyframe owned by a single shot.

    ``derived_from_character`` records the provenance key for one-reference
    providers that derive the shot keyframe from the character master.
    """
    record = {
        "kind": KEY_SHOT_KEYFRAME,
        "owner": shot_id,
        "path": str(path),
        "content_hash": content_hash(path),
        "derived_from_character": derived_from_character,
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
    for key in required:
        record = store["references"].get(key)
        if record is None:
            raise MultishotValidationError(
                f"Generation blocked for shot {shot.get('id')}: required "
                f"reference {key!r} is absent"
            )
        owner = record.get("owner")
        if key.startswith("keyframe:") and owner != shot.get("id"):
            raise MultishotValidationError(
                f"Generation blocked for shot {shot.get('id')}: keyframe owner "
                f"is {owner!r}"
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
    return record is not None and record.get("derived_from_character") == character_id


def reference_changed(
    before: dict[str, Any],
    after: dict[str, Any],
    reference_key: str,
) -> bool:
    """True when a named reference's content hash changed between two stores."""
    old = before.get("references", {}).get(reference_key, {}).get("content_hash")
    new = after.get("references", {}).get(reference_key, {}).get("content_hash")
    return old != new
