"""Thumbnail planning domain logic for YouTube video and Shorts thumbnails."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ThumbnailPlan:
    """Immutable plan for generating a high-converting video thumbnail."""

    title: str
    headline: str
    prompt: str
    negative_prompt: str
    aspect_ratio: str  # "9:16" or "16:9"
    target_dimensions: Tuple[int, int]  # (width, height)
    headline_position: str  # "upper_third", "center", "top"
    theme_color: str  # hex color for accent/badges


class ThumbnailPlanner:
    """Plans thumbnail visual prompts and layout structure for YouTube videos."""

    STYLE_PREFIX = "Epic, high-contrast YouTube thumbnail art of "
    THUMBNAIL_NEGATIVE_PROMPT = (
        "blurry, low resolution, cluttered, ugly, deformed, illegible gibberish text, "
        "distorted faces, watermark, signature, messy border, complex UI widgets"
    )

    DIMENSIONS_MAP = {
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "1:1": (1080, 1080),
    }

    @classmethod
    def clean_title_for_headline(cls, title: str, max_words: int = 5) -> str:
        """Extract a punchy 2-5 word uppercase headline from a video title."""
        if not title:
            return "HOT UPDATE"

        # Remove hashtags and bracketed tags
        cleaned = re.sub(r"#+\w*", "", title)
        cleaned = re.sub(r"\[.*?\]|\(.*?\)", "", cleaned)
        cleaned = re.sub(r"[!?:;\-–—|/#]+", " ", cleaned)
        words = [w.strip() for w in cleaned.split() if w.strip()]

        if not words:
            return "BREAKING NEWS"

        # Take up to max_words
        headline = " ".join(words[:max_words]).upper()
        if len(headline) > 40:
            headline = headline[:37].rsplit(" ", 1)[0] + "..."
        return headline

    @classmethod
    def resolve_aspect_ratio(cls, format_type: str = "short") -> Tuple[str, Tuple[int, int]]:
        """Map format label to standard aspect ratio and dimensions."""
        fmt = (format_type or "short").lower().strip()
        if fmt in ("long", "longform", "16:9", "16x9", "full", "horizontal"):
            return "16:9", cls.DIMENSIONS_MAP["16:9"]
        return "9:16", cls.DIMENSIONS_MAP["9:16"]

    @classmethod
    def build_muse_thumbnail_prompt(
        cls,
        title: str,
        topic: str = "",
        format_type: str = "short",
    ) -> Tuple[str, str]:
        """Build an optimized visual metaphor prompt for Muse Image Generation."""
        # Clean title text for topic extraction
        base_topic = topic or re.sub(r"#\w+", "", title).strip()
        clean_topic = re.sub(r"[^\w\s\-,.]", "", base_topic).strip()

        is_vertical = (format_type or "short").lower() in ("short", "shorts", "reels", "9:16", "9x16")
        framing = "vertical 9:16 poster composition, single powerful hero subject in center, cinematic rim lighting" if is_vertical else "cinematic 16:9 dynamic widescreen, hyper-detailed focal subject, dramatic studio lighting"

        prompt = (
            f"{cls.STYLE_PREFIX}{clean_topic}, {framing}, "
            "vivid saturated colors, high dynamic range, sharp focus, 8k concept art. "
            "Pure visual illustration, no text in background."
        )

        return prompt, cls.THUMBNAIL_NEGATIVE_PROMPT

    @classmethod
    def plan_thumbnail(
        cls,
        title: str,
        topic: str = "",
        format_type: str = "short",
        custom_headline: Optional[str] = None,
        theme_color: str = "#FFDD00",
    ) -> ThumbnailPlan:
        """Generate a complete ThumbnailPlan."""
        aspect_ratio, dimensions = cls.resolve_aspect_ratio(format_type)
        prompt, negative_prompt = cls.build_muse_thumbnail_prompt(title, topic, format_type)
        headline = custom_headline or cls.clean_title_for_headline(title)

        # For 9:16 Shorts, YouTube overlays buttons on the right and bottom, so upper_third is the safe zone.
        # For 16:9, upper_third or center works well.
        headline_position = "upper_third" if aspect_ratio == "9:16" else "top"

        return ThumbnailPlan(
            title=title,
            headline=headline,
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            target_dimensions=dimensions,
            headline_position=headline_position,
            theme_color=theme_color,
        )
