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

    STYLE_PREFIX = "Cinematic conceptual illustration of "
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
    def _matches_any(cls, text: str, keywords: tuple[str, ...]) -> bool:
        """Match keywords using boundary matching for single words to avoid substring false positives."""
        for kw in keywords:
            if " " in kw or "-" in kw or "." in kw:
                if kw in text:
                    return True
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    return True
        return False

    @classmethod
    def extract_visual_subject(
        cls,
        title: str,
        topic: str = "",
        context_text: str = "",
    ) -> str:
        """Extract a concrete, topic-matched visual subject for image generation."""
        clean_title = re.sub(r"#\w+", "", title).strip()
        clean_topic = re.sub(r"#\w+", "", topic).strip()
        combined = f"{clean_title} {clean_topic} {context_text}".lower()

        # 1. Topic-matched domain rules
        if cls._matches_any(combined, ("ipad", "tablet", "apple watch", "iphone", "smartphone")):
            device_name = "Apple iPad mini tablet" if "ipad" in combined else "modern tablet and mobile device"
            return f"sleek modern {device_name} held in hand, glowing futuristic neural engine processor on screen, high-tech clean Apple aesthetic"

        if cls._matches_any(combined, ("figma", "desigma", "ui design", "vector graphics", "ux design")):
            return "futuristic digital UI/UX design canvas workspace, glowing vector shapes and UI layout tools on a floating glass workstation"

        if cls._matches_any(combined, ("swarm", "manyagents", "autonomous agent", "multi-agent", "agentic")):
            return "swarm of autonomous glowing digital AI robotic agents collaborating in a high-tech network matrix, collective intelligence"

        if cls._matches_any(combined, ("browser", "opera", "webai", "web browser", "chrome")):
            return "futuristic web browser interface with integrated local AI engine, glowing cyber web browser workspace and code elements"

        if cls._matches_any(combined, ("voice", "speech", "audio", "soundwave", "theysaid", "loqui", "synthesis")):
            return "glowing futuristic digital soundwave visualizer and AI audio speech interface, holographic microphone with emotive sound waves"

        if cls._matches_any(combined, ("security", "1password", "secrets", "vault", "identity", "cryptographic", "dataroom", "papermark")):
            return "futuristic cyber security vault, glowing holographic digital keys and encrypted security shield, biometric cyber protection"

        if cls._matches_any(combined, ("off-grid", "off grid", "offline ai", "edge ai", "local ai", "decentralized")):
            return "rugged portable offline edge AI computing hardware device operating off-grid in nature, glowing circuit boards, decentralized personal hardware"

        if cls._matches_any(combined, ("video", "cinema", "nuvio", "film", "4k render")):
            return "futuristic cinema camera projecting a glowing 4K ultra-high-definition holographic AI film universe, high-speed generative video"

        if cls._matches_any(combined, ("job", "resume", "hiring", "jobmate", "recruiting")):
            return "digital futuristic hiring portal with glowing automated resume pipelines, AI bot reviewing job applications on holographic screens"

        if cls._matches_any(combined, ("pdf", "accessibility", "webyes", "document", "braille")):
            return "digital holographic document being scanned with glowing accessible sound waves and braille patterns, clean modern tech interface"

        if cls._matches_any(combined, ("bridge", "ai bridge")):
            return "futuristic glowing cybernetic bridge connecting neural AI models to real-world autonomous tasks, digital infrastructure"

        if cls._matches_any(combined, ("minimax", "m3.1")):
            return "ultra-fast lightning speed AI neural brain processor glowing with neon cyan energy and high-speed data flow"

        if cls._matches_any(combined, ("allmodels", "multi-model")):
            return "multiple interconnected glowing AI model nodes racing in a high-tech digital neural matrix"

        if cls._matches_any(combined, ("gpt", "openai", "claude", "gemini", "llm")):
            model_name = clean_topic or clean_title.split(":")[0].strip()
            return f"an advanced glowing neural artificial intelligence brain core representing {model_name}, futuristic AI data streams, holographic neural network"

        if cls._matches_any(combined, ("strawberry", "reasoning", "test-time", "compute", "o1", "o3", "thinking")):
            return "futuristic glowing crimson AI neural processor deep in thought and reasoning, holographic computational tree search, cognitive reasoning core"

        # Fallback: clean core subject from title
        core_subject = re.sub(r"[!?:;\-–—|/#]+", " ", clean_title)
        core_words = [w for w in core_subject.split() if w.lower() not in ("a", "an", "the", "in", "on", "and", "by", "of", "for", "with")]
        short_subject = " ".join(core_words[:6])
        return f"conceptual high-tech visual metaphor of {short_subject}, prominent hero subject, dramatic cinematic atmosphere"

    @classmethod
    def build_muse_thumbnail_prompt(
        cls,
        title: str,
        topic: str = "",
        format_type: str = "short",
        context_text: str = "",
    ) -> Tuple[str, str]:
        """Build an optimized visual metaphor prompt for Muse Image Generation."""
        visual_subject = cls.extract_visual_subject(title, topic, context_text)

        is_vertical = (format_type or "short").lower() in ("short", "shorts", "reels", "9:16", "9x16")
        framing = "vertical 9:16 poster composition" if is_vertical else "cinematic 16:9 dynamic widescreen"

        prompt = (
            f"{cls.STYLE_PREFIX}{visual_subject}, {framing}, dramatic studio lighting, 8k render. "
            "Pure visual imagery. Output markdown image tag ![Image](url)."
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
        context_text: str = "",
    ) -> ThumbnailPlan:
        """Generate a complete ThumbnailPlan."""
        aspect_ratio, dimensions = cls.resolve_aspect_ratio(format_type)
        prompt, negative_prompt = cls.build_muse_thumbnail_prompt(title, topic, format_type, context_text)
        headline = custom_headline or cls.clean_title_for_headline(title)

        # Body center positioning ensures text stays safely within YouTube safe zones and avoids edge/UI cutoff
        headline_position = "body_center"

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
