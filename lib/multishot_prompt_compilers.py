"""Provider-specific prompt compilers for multi-shot video generation.

Translates canonical shot plans and multi-shot context into optimized,
provider-compliant prompt payloads without mutating core pipeline state.
"""

from __future__ import annotations

import hashlib
from typing import Any

from lib.multishot_schemas import MultishotValidationError


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


def prompt_hash_for_provider(provider: str, prompt: str) -> str:
    """Return the exact prompt_hash representation required by the provider."""
    if provider == "kling_official":
        return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
