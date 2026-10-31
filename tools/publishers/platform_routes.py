"""Platform publishing routes and the 9:16 vertical geometry gate.

All output is vertical. YouTube Shorts, TikTok, and Facebook Reels take the full
vertical render; Instagram Reels takes the shorter cut render.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def _ffprobe() -> str | None:
    path = shutil.which("ffprobe")
    if path:
        return path
    candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
    return str(candidates[0]) if candidates else None

FULL_RENDER = "renders/final_full_vi_9x16.mp4"
CUT_RENDER = "renders/final_reels_vi_9x16.mp4"

# The full render is the complete vertical NewsNow story. The cut render is
# used by short-form routes that have a duration limit.
# platform -> (publish kind, publish_metadata.json field, render used)
PLATFORM_ROUTES: dict[str, tuple[str, str, str]] = {
    "youtube": ("short", "yt_shorts", CUT_RENDER),
    "tiktok": ("video", "tiktok", FULL_RENDER),
    "facebook": ("reels", "fb_video", FULL_RENDER),
    "instagram": ("reels", "ig_reels", CUT_RENDER),
}

VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
HORIZONTAL_WIDTH = 1920
HORIZONTAL_HEIGHT = 1080
YOUTUBE_SHORT_MIN_SECONDS = 60.0
YOUTUBE_SHORT_MAX_SECONDS = 180.0
LONGFORM_MIN_SECONDS = 60.0
YOUTUBE_TITLE_MAX_CHARS = 100
YOUTUBE_SHORTS_HASHTAG = "#Shorts"
DEFAULT_VIETNAMESE_TAGS = ["tintuc", "congnghe", "ai", "vietnam"]
DEFAULT_ENGLISH_TAGS = ["ai", "tech", "software"]


class ReleaseMetadata:
    """Centralized, immutable typed release metadata for all publishing platforms."""

    def __init__(
        self,
        project_id: str,
        title: str,
        description: str,
        yt_shorts: str,
        ig_reels: str,
        fb_video: str,
        tiktok: str,
        tags: list[str] | None = None,
        source_url: str | None = None,
        extra: dict | None = None,
    ):
        self.project_id = project_id
        self.title = title
        self.description = description
        self.yt_shorts = yt_shorts
        self.ig_reels = ig_reels
        self.fb_video = fb_video
        self.tiktok = tiktok
        self.tags = tags or list(DEFAULT_VIETNAMESE_TAGS)
        self.source_url = source_url
        self.extra = extra or {}

    @property
    def youtube_payload(self) -> dict:
        return {
            "title": youtube_shorts_title(self.title),
            "description": self.description,
            "tags": list(self.tags),
        }

    @property
    def instagram_payload(self) -> dict:
        from tools.publishers.social_metadata import meta_caption
        return {
            "caption": meta_caption(self.title, self.description),
        }

    @property
    def facebook_payload(self) -> dict:
        from tools.publishers.social_metadata import meta_caption
        return {
            "title": self.title,
            "caption": meta_caption(self.title, self.description),
        }

    @property
    def tiktok_payload(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
        }

    def to_dict(self) -> dict:
        d = {
            "id": self.project_id,
            "title": self.title,
            "description": self.description,
            "yt_shorts": self.yt_shorts,
            "ig_reels": self.ig_reels,
            "fb_video": self.fb_video,
            "tiktok": self.tiktok,
            "tags": self.tags,
        }
        if self.source_url:
            d["source_url"] = self.source_url
        if self.extra:
            d.update(self.extra)
        return d


def deduplicate_hashtags_in_text(text: str) -> str:
    """Deduplicate hashtags case-insensitively while preserving original order and formatting."""
    seen = set()
    tokens = text.split()
    result = []
    for token in tokens:
        if token.startswith("#"):
            normalized = token.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
        result.append(token)
    return " ".join(result)


def validate_release_metadata(meta: dict) -> list[str]:
    """Validate release metadata fields according to strict platform and quality constraints."""
    errors = []
    for required in ("id", "title", "description"):
        if not meta.get(required):
            errors.append(f"missing required field: {required}")

    title = str(meta.get("title", ""))
    desc = str(meta.get("description", ""))

    locale = (
        meta.get("locale")
        or os.environ.get("OPENMONTAGE_LOCALE")
        or os.environ.get("TARGET_LOCALE")
        or ("en-US" if "en-us" in str(meta.get("audience_profile_id", "")).lower() else "vi-VN")
    )

    if title:
        from scripts.validate_publish_metadata import validate_text_field
        errors.extend(validate_text_field("title", title))
        from lib.language_validation import get_language_validator
        validator = get_language_validator(locale)
        lang_errors = validator.validate_prose(title)
        if lang_errors:
            errors.extend(f"title language error: {err}" for err in lang_errors)

    if desc:
        from scripts.validate_publish_metadata import validate_text_field
        errors.extend(validate_text_field("description", desc))
        from lib.language_validation import get_language_validator
        validator = get_language_validator(locale)
        desc_lang = validator.validate_prose(desc)
        if desc_lang:
            errors.extend(f"description language error: {err}" for err in desc_lang)

    return errors


def _resolve_render_target(val: Any, default: str) -> str:
    target = val or default
    if isinstance(target, dict):
        return str(target.get("path") or target.get("file") or default)
    return str(target)


def _clean_and_dedup_tags(tags: Any, default_tags: tuple[str, ...]) -> list[str]:
    if not isinstance(tags, list):
        return list(default_tags)
    seen: set[str] = set()
    clean_tags: list[str] = []
    for t in tags:
        tag_clean = str(t).strip().lstrip("#").lower()
        if tag_clean and tag_clean not in seen:
            seen.add(tag_clean)
            clean_tags.append(tag_clean)
    return clean_tags or list(default_tags)


def _resolve_platform_defaults(data: dict) -> tuple[tuple[str, ...], str, str]:
    from lib.artifact_paths import is_english_locale
    locale = (
        data.get("locale")
        or os.environ.get("OPENMONTAGE_LOCALE")
        or os.environ.get("TARGET_LOCALE")
        or ("en-US" if "en-us" in str(data.get("audience_profile_id", "")).lower() else "vi-VN")
    )
    is_en = is_english_locale(locale)
    default_tags = DEFAULT_ENGLISH_TAGS if is_en else DEFAULT_VIETNAMESE_TAGS
    default_short = "renders/final_short_en_US_9x16.mp4" if is_en else CUT_RENDER
    default_full = "renders/final_long_en_US_16x9.mp4" if is_en else FULL_RENDER
    return default_tags, default_short, default_full


def compose_release_metadata(data: dict) -> ReleaseMetadata:
    """Build and validate a unified ReleaseMetadata object from raw metadata dict."""
    errors = validate_release_metadata(data)
    if errors:
        raise ValueError(f"Invalid release metadata: {'; '.join(errors)}")

    title = deduplicate_hashtags_in_text(str(data["title"]).strip())
    desc = deduplicate_hashtags_in_text(str(data["description"]).strip())
    default_tags, default_short, default_full = _resolve_platform_defaults(data)

    tags = _clean_and_dedup_tags(data.get("tags"), default_tags)
    yt_shorts = _resolve_render_target(data.get("yt_shorts"), default_short)
    ig_reels = _resolve_render_target(data.get("ig_reels"), default_short)
    fb_video = _resolve_render_target(data.get("fb_video"), default_full)
    default_tiktok = default_short
    raw_tiktok = data.get("tiktok")
    if raw_tiktok and ("16x9" in str(raw_tiktok) or "long" in str(raw_tiktok)):
        tiktok = default_tiktok
    else:
        tiktok = _resolve_render_target(raw_tiktok, default_tiktok)

    extra = {k: v for k, v in data.items() if k not in (
        "id", "title", "description", "yt_shorts", "ig_reels", "fb_video", "tiktok", "tags", "source_url"
    )}

    return ReleaseMetadata(
        project_id=str(data["id"]),
        title=title,
        description=desc,
        yt_shorts=yt_shorts,
        ig_reels=ig_reels,
        fb_video=fb_video,
        tiktok=tiktok,
        tags=tags,
        source_url=data.get("source_url"),
        extra=extra,
    )



def youtube_shorts_title(title: str) -> str:
    """Build a valid Shorts title without truncating its required hashtag."""
    base = re.sub(r"(?i)(?:^|\s)#shorts\b", "", title).strip()
    if not base:
        raise ValueError("YouTube Shorts title must contain text before #Shorts")
    suffix = f" {YOUTUBE_SHORTS_HASHTAG}"
    return f"{base[:YOUTUBE_TITLE_MAX_CHARS - len(suffix)].rstrip()}{suffix}"


def metadata_field(platform: str) -> str:
    return PLATFORM_ROUTES[platform][1]


def probe_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream.

    Raises ValueError when the file is missing, unprobeable, or has no video
    stream — publishing must fail closed rather than upload unknown media.
    """
    ffprobe = _ffprobe()
    if not ffprobe:
        raise ValueError("ffprobe is required to validate video geometry")
    if not path.is_file():
        raise ValueError(f"video not found: {path}")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path}: {result.stderr.strip()[:200]}")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: no video stream to validate ({exc})") from exc


def probe_duration(path: Path) -> float:
    """Return the container duration in seconds for a media file."""
    ffprobe = _ffprobe()
    if not ffprobe:
        raise ValueError("ffprobe is required to validate video duration")
    if not path.is_file():
        raise ValueError(f"video not found: {path}")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path}: {result.stderr.strip()[:200]}")
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: cannot determine video duration ({exc})") from exc


def ensure_vertical(path: Path) -> None:
    """Reject any asset that is not 9:16 portrait before it reaches a platform."""
    width, height = probe_dimensions(path)
    if width * 16 != height * 9:
        raise ValueError(
            f"{path}: {width}x{height} is not 9:16 vertical; "
            f"only {VERTICAL_WIDTH}x{VERTICAL_HEIGHT}-style portrait media may be published"
        )


def ensure_youtube_short(path: Path) -> None:
    """Reject a video that YouTube would classify as a regular video or that violates the 1-minute min rule."""
    duration = probe_duration(path)
    if duration < YOUTUBE_SHORT_MIN_SECONDS:
        raise ValueError(
            f"{path}: {duration:.3f}s is under the YouTube Shorts minimum duration of "
            f"{YOUTUBE_SHORT_MIN_SECONDS:.0f} seconds (1 minute minimum required)"
        )
    if duration > YOUTUBE_SHORT_MAX_SECONDS:
        raise ValueError(
            f"{path}: {duration:.3f}s exceeds the YouTube Shorts limit of "
            f"{YOUTUBE_SHORT_MAX_SECONDS:.0f} seconds"
        )


def ensure_horizontal(path: Path) -> None:
    """Reject any asset that is not landscape / horizontal (e.g. 16:9) for long-form publishing, or under 60s."""
    width, height = probe_dimensions(path)
    if width <= height:
        raise ValueError(
            f"{path}: {width}x{height} is not horizontal; "
            f"long-form videos must have landscape geometry (width > height, e.g. 16:9)"
        )
    if path.is_file():
        duration = probe_duration(path)
        if duration < LONGFORM_MIN_SECONDS:
            raise ValueError(
                f"{path}: {duration:.3f}s is under the minimum long-form duration of "
                f"{LONGFORM_MIN_SECONDS:.0f} seconds (1 minute minimum required)"
            )
