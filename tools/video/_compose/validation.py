"""Pre-compose validation, quality checks, and transcript verification helpers.

Pure and policy-driven validation logic separated from the composition executor.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional, Set

from tools.base_tool import ToolResult

TTS_PUNCTUATION_LEAK_WORDS: Set[str] = {
    "dot", "dots", "ellipsis", "period", "periods",
    "comma", "commas", "semicolon", "colon",
    "dash", "hyphen", "emdash", "endash",
    "parenthesis", "bracket", "brace",
    "asterisk", "slash", "backslash",
    "exclamation", "question mark",
}


def read_text_file(path: str | Path | None) -> str | None:
    """Read a small text file if given a path; None-safe and exception-safe."""
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return None


def tokenize_text(text: str) -> list[str]:
    """Split text into comparable word tokens (lowercased, punctuation stripped)."""
    cleaned = re.sub(r"[^A-Za-z0-9\-' ]+", " ", text.lower())
    return [t for t in cleaned.split() if t and t != "-"]


def compare_transcript_to_script(
    transcript_path: str | Path,
    script_text: str,
) -> dict[str, Any]:
    """Compare a word-level transcript against the source script."""
    result: dict[str, Any] = {
        "transcript_matches_script": False,
        "word_accuracy": None,
        "script_word_count": 0,
        "transcript_word_count": 0,
        "spurious_punctuation_words": [],
        "issues": [],
    }

    if not transcript_path or not Path(transcript_path).is_file():
        result["issues"].append(
            "transcript_comparison skipped: narration_transcript not provided"
        )
        return result
    if not script_text:
        result["issues"].append(
            "transcript_comparison skipped: script_text not provided"
        )
        return result

    try:
        transcript_data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    except Exception as e:
        result["issues"].append(f"transcript_comparison could not parse transcript: {e}")
        return result

    transcript_words = [
        w.get("word", "").strip() for w in transcript_data.get("word_timestamps", [])
    ]
    transcript_tokens = tokenize_text(" ".join(transcript_words))
    script_tokens = tokenize_text(script_text)

    result["script_word_count"] = len(script_tokens)
    result["transcript_word_count"] = len(transcript_tokens)

    if not script_tokens or not transcript_tokens:
        result["issues"].append(
            f"transcript_comparison: empty token set "
            f"(script={len(script_tokens)}, transcript={len(transcript_tokens)})"
        )
        return result

    script_set = set(script_tokens)
    leak_occurrences: dict[str, int] = {}
    for token in transcript_tokens:
        if token in TTS_PUNCTUATION_LEAK_WORDS and token not in script_set:
            leak_occurrences[token] = leak_occurrences.get(token, 0) + 1

    if leak_occurrences:
        formatted = ", ".join(
            f"{w!r}×{n}" for w, n in sorted(leak_occurrences.items(), key=lambda x: -x[1])
        )
        result["spurious_punctuation_words"] = [
            {"word": w, "count": n} for w, n in leak_occurrences.items()
        ]
        result["issues"].append(
            f"TTS punctuation leak: transcript contains {formatted} — "
            f"these words are NOT in the script, which means the voice "
            f"engine is reading literal punctuation aloud. Rewrite the "
            f"script to eliminate the corresponding characters (ellipses, "
            f"em-dashes, etc.) and regenerate narration."
        )

    matched = sum(1 for t in script_tokens if t in set(transcript_tokens))
    accuracy = matched / max(1, len(script_tokens))
    result["word_accuracy"] = round(accuracy, 3)
    result["transcript_matches_script"] = accuracy >= 0.9 and not leak_occurrences

    if accuracy < 0.9:
        result["issues"].append(
            f"Low transcript-to-script match: only {accuracy:.0%} of script "
            f"words appear in the transcribed audio ({matched}/"
            f"{len(script_tokens)}). Narration may be truncated, mispronounced, "
            f"or the wrong script was used."
        )

    return result


def pre_compose_validation(
    edit_decisions: dict[str, Any],
    resolved_cuts: list[dict],
    scene_plan: list[dict] | None = None,
    asset_manifest: dict[str, Any] | None = None,
) -> ToolResult | None:
    """Pre-compose quality gate — blocks render on critical violations."""
    log = logging.getLogger("video_compose.validation")
    warnings: list[str] = []
    blocks: list[str] = []

    # 1. Delivery promise check
    delivery_data = edit_decisions.get("metadata", {}).get("delivery_promise")
    if not delivery_data:
        delivery_data = edit_decisions.get("delivery_promise")

    if delivery_data:
        try:
            from lib.delivery_promise import DeliveryPromise
            promise = DeliveryPromise.from_dict(delivery_data)
            result = promise.validate_cuts(resolved_cuts)
            if not result["valid"]:
                for v in result["violations"]:
                    blocks.append(f"Delivery promise violation: {v}")
        except Exception as e:
            log.warning("Could not validate delivery promise: %s", e)
    else:
        warnings.append("No delivery_promise in edit_decisions — skipping promise validation")

    # 2. Slideshow risk check
    renderer_family = edit_decisions.get("renderer_family")
    scenes = scene_plan or []

    if not scenes and resolved_cuts:
        scenes = [
            {
                "type": c.get("type", ""),
                "description": c.get("reason", ""),
                "shot_language": c.get("shot_language", {}),
                "shot_intent": c.get("shot_intent"),
                "narrative_role": c.get("narrative_role"),
                "information_role": c.get("information_role"),
                "hero_moment": c.get("hero_moment", False),
            }
            for c in resolved_cuts
        ]

    if scenes:
        try:
            from lib.slideshow_risk import score_slideshow_risk
            render_runtime = edit_decisions.get("render_runtime")
            risk = score_slideshow_risk(
                scenes, edit_decisions, renderer_family, render_runtime
            )
            if risk["verdict"] == "fail":
                blocks.append(
                    f"Slideshow risk score {risk['average']:.1f}/5.0 (verdict: fail). "
                    f"Video plan looks like a slideshow — revise scene plan before rendering."
                )
            elif risk["verdict"] == "revise":
                warnings.append(
                    f"Slideshow risk score {risk['average']:.1f}/5.0 (verdict: revise). "
                    f"Consider improving scene variety before final render."
                )
        except Exception as e:
            log.warning("Could not compute slideshow risk: %s", e)

    # 3. Missing renderer_family (BLOCK)
    if not renderer_family:
        blocks.append(
            "No renderer_family in edit_decisions. "
            "renderer_family must be set at proposal stage and locked before compose. "
            "Re-run the proposal stage with a renderer_family selection."
        )

    # 4. Music copyright / platform policy check
    if asset_manifest is not None:
        try:
            from lib.music_policy import validate_music_policy
            music_errors = validate_music_policy(asset_manifest, edit_decisions)
            for err in music_errors:
                blocks.append(f"Music policy: {err}")
        except Exception as e:
            log.warning("Could not validate music policy: %s", e)

    for w in warnings:
        log.warning("[pre-compose] %s", w)

    if blocks:
        return ToolResult(
            success=False,
            error=(
                "Pre-compose validation failed — render blocked.\n"
                + "\n".join(f"  • {b}" for b in blocks)
                + ("\n\nWarnings:\n" + "\n".join(f"  • {w}" for w in warnings) if warnings else "")
            ),
        )

    return None
