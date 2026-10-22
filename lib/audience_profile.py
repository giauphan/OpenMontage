"""Immutable, schema-validated loader for OpenMontage target audience profiles."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "audience_profile.schema.json"
DEFAULT_PROFILES_DIR = ROOT / "config" / "audience_profiles"


class AudienceProfileError(ValueError):
    """Base error for audience profile loading and validation."""


class AudienceProfileValidationError(AudienceProfileError):
    """Raised when an audience profile fails schema validation."""


@dataclass(frozen=True)
class ViewerProfile:
    primary_job: str
    segments: tuple[str, ...]
    banned_assumptions: tuple[str, ...]


@dataclass(frozen=True)
class ContentProfile:
    pillars: tuple[str, ...]
    source_requirement: str
    independent_claim_review: bool
    original_value_requirement: str
    cultural_rewrite: bool
    native_english_human_approval_initial_canary: bool


@dataclass(frozen=True)
class FormatSpec:
    output: str
    aspect: str
    internal_pilot_max_seconds: float | None = None
    suggested_minute_range: tuple[float, float] | None = None


@dataclass(frozen=True)
class VoiceProfile:
    locale: str
    provider_voice: str
    sample_pronunciation_first: bool


@dataclass(frozen=True)
class CaptionsProfile:
    language: str
    generate_from_final_audio: bool
    require_manual_critical_token_review: bool


@dataclass(frozen=True)
class VisualsProfile:
    require_scene_claim_bindings: bool
    require_media_rights: bool
    require_real_frame_samples: bool
    reject_unrelated_generic_background: bool
    reject_fake_product_ui: bool


@dataclass(frozen=True)
class PublishingProfile:
    only_platform: str
    enabled: bool
    allow_public_auto_upload: bool
    default_canary_visibility: str
    application_timezone: str
    min_hours_between_releases: float
    candidate_shorts_per_week: int
    candidate_longform_per_week: int
    kill_switch: bool
    target_channel_id: str | None = None


@dataclass(frozen=True)
class SafetyProfile:
    fail_closed: bool
    network_disabled_for_rehearsal: bool
    paid_calls_disabled_for_rehearsal: bool
    require_three_independent_rehearsals: bool
    keep_old_vi_queue_snapshot: bool


@dataclass(frozen=True)
class AudienceProfile:
    profile_id: str
    primary_market: str
    secondary_markets: tuple[str, ...]
    spoken_language: str
    metadata_language: str
    viewer_profile: ViewerProfile
    content: ContentProfile
    formats: dict[str, FormatSpec]
    voice: VoiceProfile
    captions: CaptionsProfile
    visuals: VisualsProfile
    publishing: PublishingProfile
    safety: SafetyProfile

    @property
    def is_english(self) -> bool:
        return self.spoken_language.startswith("en")

    @property
    def is_vietnamese(self) -> bool:
        return self.spoken_language.startswith("vi")


_PROFILE_CACHE: dict[str, AudienceProfile] = {}
_SCHEMA_CACHE: dict[str, Any] | None = None


def get_schema() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        if not SCHEMA_PATH.is_file():
            raise AudienceProfileError(f"Schema not found: {SCHEMA_PATH}")
        _SCHEMA_CACHE = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def validate_profile_dict(data: dict[str, Any]) -> None:
    schema = get_schema()
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise AudienceProfileValidationError(f"Invalid audience profile: {exc.message}") from exc


def _build_profile_object(data: dict[str, Any]) -> AudienceProfile:
    validate_profile_dict(data)

    vp = data["viewer_profile"]
    viewer_obj = ViewerProfile(
        primary_job=vp["primary_job"],
        segments=tuple(vp["segments"]),
        banned_assumptions=tuple(vp["banned_assumptions"]),
    )

    cp = data["content"]
    content_obj = ContentProfile(
        pillars=tuple(cp["pillars"]),
        source_requirement=cp["source_requirement"],
        independent_claim_review=bool(cp["independent_claim_review"]),
        original_value_requirement=cp["original_value_requirement"],
        cultural_rewrite=bool(cp["cultural_rewrite"]),
        native_english_human_approval_initial_canary=bool(
            cp.get("native_english_human_approval_initial_canary", False)
        ),
    )

    formats_obj: dict[str, FormatSpec] = {}
    for name, f_data in data["formats"].items():
        formats_obj[name] = FormatSpec(
            output=f_data["output"],
            aspect=f_data["aspect"],
            internal_pilot_max_seconds=f_data.get("internal_pilot_max_seconds"),
            suggested_minute_range=(
                tuple(f_data["suggested_minute_range"])
                if f_data.get("suggested_minute_range")
                else None
            ),
        )

    vo = data["voice"]
    voice_obj = VoiceProfile(
        locale=vo["locale"],
        provider_voice=vo["provider_voice"],
        sample_pronunciation_first=bool(vo["sample_pronunciation_first"]),
    )

    cap = data["captions"]
    captions_obj = CaptionsProfile(
        language=cap["language"],
        generate_from_final_audio=bool(cap["generate_from_final_audio"]),
        require_manual_critical_token_review=bool(cap["require_manual_critical_token_review"]),
    )

    vis = data["visuals"]
    visuals_obj = VisualsProfile(
        require_scene_claim_bindings=bool(vis["require_scene_claim_bindings"]),
        require_media_rights=bool(vis["require_media_rights"]),
        require_real_frame_samples=bool(vis["require_real_frame_samples"]),
        reject_unrelated_generic_background=bool(vis["reject_unrelated_generic_background"]),
        reject_fake_product_ui=bool(vis["reject_fake_product_ui"]),
    )

    pub = data["publishing"]
    publishing_obj = PublishingProfile(
        only_platform=pub["only_platform"],
        enabled=bool(pub["enabled"]),
        target_channel_id=pub.get("target_channel_id"),
        allow_public_auto_upload=bool(pub["allow_public_auto_upload"]),
        default_canary_visibility=pub["default_canary_visibility"],
        application_timezone=pub["application_timezone"],
        min_hours_between_releases=float(pub["min_hours_between_releases"]),
        candidate_shorts_per_week=int(pub["candidate_shorts_per_week"]),
        candidate_longform_per_week=int(pub["candidate_longform_per_week"]),
        kill_switch=bool(pub["kill_switch"]),
    )

    saf = data["safety"]
    safety_obj = SafetyProfile(
        fail_closed=bool(saf["fail_closed"]),
        network_disabled_for_rehearsal=bool(saf["network_disabled_for_rehearsal"]),
        paid_calls_disabled_for_rehearsal=bool(saf["paid_calls_disabled_for_rehearsal"]),
        require_three_independent_rehearsals=bool(saf["require_three_independent_rehearsals"]),
        keep_old_vi_queue_snapshot=bool(saf["keep_old_vi_queue_snapshot"]),
    )

    return AudienceProfile(
        profile_id=data["profile_id"],
        primary_market=data["primary_market"],
        secondary_markets=tuple(data.get("secondary_markets", [])),
        spoken_language=data["spoken_language"],
        metadata_language=data["metadata_language"],
        viewer_profile=viewer_obj,
        content=content_obj,
        formats=formats_obj,
        voice=voice_obj,
        captions=captions_obj,
        visuals=visuals_obj,
        publishing=publishing_obj,
        safety=safety_obj,
    )


def load_audience_profile(source: str | Path | None = None) -> AudienceProfile:
    """Load an audience profile from a file path, profile name, or default en-US.

    Returns an immutable AudienceProfile object. Caches results in memory.
    """
    if source is None:
        source = "en-US"

    source_str = str(source)
    if source_str in _PROFILE_CACHE:
        return _PROFILE_CACHE[source_str]

    path: Path | None = None
    target = Path(source)
    if target.is_file():
        path = target
    else:
        # Check standard dir
        for ext in (".yaml", ".yml", ".json"):
            candidate = DEFAULT_PROFILES_DIR / f"{source_str}{ext}"
            if candidate.is_file():
                path = candidate
                break

    if path is None or not path.is_file():
        raise AudienceProfileError(f"Audience profile not found for source: {source}")

    content = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(content)
    else:
        data = json.loads(content)

    if not isinstance(data, dict):
        raise AudienceProfileError(f"Audience profile in {path} must be a dictionary")

    profile = _build_profile_object(data)
    _PROFILE_CACHE[source_str] = profile
    _PROFILE_CACHE[profile.profile_id] = profile
    _PROFILE_CACHE[str(path)] = profile
    return profile
