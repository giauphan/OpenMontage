#!/usr/bin/env python3
"""Shared publish config loader.

Reads config/publish_schedule.json and lets env vars override the sensitive/
env-specific values so the flow is portable across servers.

Env overrides (all optional):
  PUBLISH_TZ            -> timezone (default from config)
  FB_PAGE_ID            -> Facebook Page ID
  IG_ACCOUNT_ID         -> Instagram Business Account ID
  YOUTUBE_ACCOUNT       -> YouTube account label
"""
import json
import os
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(os.environ.get("OPENMONTAGE_ROOT") or Path(__file__).resolve().parents[1])
CONFIG_PATH = Path(os.environ.get("OPENMONTAGE_CONFIG") or ROOT / "config" / "publish_schedule.json")


def _parse_hhmm(value: str) -> dt_time:
    hh, mm = value.split(":", 1)
    return dt_time(int(hh), int(mm))


import re

PLATFORM_ALIASES: dict[str, str] = {
    "ig": "instagram",
    "insta": "instagram",
    "instagram": "instagram",
    "fb": "facebook",
    "face": "facebook",
    "facebook": "facebook",
    "tiktok": "tiktok",
    "tt": "tiktok",
    "ytb": "youtube",
    "yt": "youtube",
    "youtube": "youtube",
}

ALL_CANONICAL_PLATFORMS: set[str] = {"youtube", "instagram", "facebook", "tiktok"}


def canonical_platform_name(name: str) -> str:
    """Normalize a platform alias or name to its canonical name.

    Supports aliases:
      - ig, insta, instagram -> instagram
      - fb, face, facebook -> facebook
      - tiktok, tt -> tiktok
      - ytb, yt, youtube -> youtube
    """
    cleaned = (name or "").strip().lower()
    return PLATFORM_ALIASES.get(cleaned, cleaned)


def parse_platform_list(value: Any) -> set[str]:
    """Parse comma/space/semicolon-separated string or iterable of platform names into canonical set."""
    if not value:
        return set()
    if isinstance(value, (list, set, tuple)):
        result: set[str] = set()
        for item in value:
            result.update(parse_platform_list(item))
        return result
    tokens = re.split(r"[\s,;]+", str(value).strip())
    return {canonical_platform_name(tok) for tok in tokens if tok.strip()}


def get_held_platforms(
    cfg: dict[str, Any] | None = None,
    extra_held: list[str] | set[str] | str | None = None,
) -> set[str]:
    """Return set of canonical platform names currently held (paused/skipped).

    Precedence/Sources:
      1. Explicit caller/CLI argument `extra_held` (e.g. from --hold-platform / --hold-platforms)
      2. Environment variable HOLD_PLATFORMS or HOLD_PIPELINE (e.g. "ig,fb" or "tiktok" or "ytb")
      3. Individual environment variables (truthy if 1/true/yes/on):
         - HOLD_IG, HOLD_INSTAGRAM
         - HOLD_FB, HOLD_FACEBOOK
         - HOLD_TIKTOK, HOLD_TT
         - HOLD_YTB, HOLD_YT, HOLD_YOUTUBE
      4. `held_platforms` in config/publish_schedule.json (or passed cfg dict)
    """
    held: set[str] = set()
    if extra_held:
        held.update(parse_platform_list(extra_held))

    for env_var in ("HOLD_PLATFORMS", "HOLD_PIPELINE"):
        raw = os.environ.get(env_var, "")
        if raw:
            held.update(parse_platform_list(raw))

    env_flags = [
        (("HOLD_IG", "HOLD_INSTAGRAM"), "instagram"),
        (("HOLD_FB", "HOLD_FACEBOOK"), "facebook"),
        (("HOLD_TIKTOK", "HOLD_TT"), "tiktok"),
        (("HOLD_YTB", "HOLD_YT", "HOLD_YOUTUBE"), "youtube"),
    ]
    for env_keys, canonical in env_flags:
        for k in env_keys:
            val = os.environ.get(k, "").strip().lower()
            if val in ("1", "true", "yes", "on"):
                held.add(canonical)
                break

    if cfg is None:
        try:
            if CONFIG_PATH.is_file():
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = None

    if cfg and isinstance(cfg, dict):
        cfg_held = cfg.get("held_platforms")
        if cfg_held:
            held.update(parse_platform_list(cfg_held))

    return held


def is_platform_held(
    platform: str,
    cfg: dict[str, Any] | None = None,
    extra_held: list[str] | set[str] | str | None = None,
) -> bool:
    """Check if a specific platform (or alias) is currently held."""
    canonical = canonical_platform_name(platform)
    return canonical in get_held_platforms(cfg=cfg, extra_held=extra_held)


PLATFORMS_CONFIG_PATH = Path(
    os.environ.get("OPENMONTAGE_PLATFORMS_CONFIG")
    or ROOT / "config" / "publish_platforms.json"
)


def get_enabled_platforms(
    cfg: dict[str, Any] | None = None,
    extra_enabled: list[str] | set[str] | str | None = None,
) -> set[str] | None:
    """Return set of canonical platform names currently enabled, or None if unconstrained.

    Precedence/Sources:
      1. Explicit caller/CLI argument `extra_enabled` (e.g. from --enabled-platforms / --enable-platform / --only-platform)
      2. Environment variable ENABLED_PLATFORMS, ACTIVE_PLATFORMS, or PUBLISH_PLATFORMS (e.g. "ytb" or "youtube,instagram")
      3. Individual environment variables (truthy if 1/true/yes/on):
         - ENABLE_YTB, ENABLE_YT, ENABLE_YOUTUBE
         - ENABLE_IG, ENABLE_INSTAGRAM
         - ENABLE_FB, ENABLE_FACEBOOK
         - ENABLE_TIKTOK, ENABLE_TT
      4. Dedicated config file (config/publish_platforms.json or OPENMONTAGE_PLATFORMS_CONFIG)
      5. `enabled_platforms` or `active_platforms` in config/publish_schedule.json (or passed cfg dict)

    If none of the above are set/configured, returns None (all platforms permitted by default).
    If any source specifies enabled platforms, returns a set of canonical names.
    """
    has_source = False
    enabled: set[str] = set()

    if extra_enabled is not None:
        has_source = True
        enabled.update(parse_platform_list(extra_enabled))

    for env_var in ("ENABLED_PLATFORMS", "ACTIVE_PLATFORMS", "PUBLISH_PLATFORMS"):
        raw = os.environ.get(env_var)
        if raw is not None:
            has_source = True
            if raw.strip():
                enabled.update(parse_platform_list(raw))

    env_flags = [
        (("ENABLE_YTB", "ENABLE_YT", "ENABLE_YOUTUBE"), "youtube"),
        (("ENABLE_IG", "ENABLE_INSTAGRAM"), "instagram"),
        (("ENABLE_FB", "ENABLE_FACEBOOK"), "facebook"),
        (("ENABLE_TIKTOK", "ENABLE_TT"), "tiktok"),
    ]
    for env_keys, canonical in env_flags:
        for k in env_keys:
            val = os.environ.get(k, "").strip().lower()
            if val in ("1", "true", "yes", "on"):
                has_source = True
                enabled.add(canonical)
                break

    if not has_source:
        try:
            platforms_path = Path(
                os.environ.get("OPENMONTAGE_PLATFORMS_CONFIG")
                or ROOT / "config" / "publish_platforms.json"
            )
            if platforms_path.is_file():
                p_cfg = json.loads(platforms_path.read_text(encoding="utf-8"))
                if isinstance(p_cfg, dict):
                    plat_list = p_cfg.get("enabled_platforms") or p_cfg.get("active_platforms")
                    if plat_list is not None:
                        has_source = True
                        enabled.update(parse_platform_list(plat_list))
                elif isinstance(p_cfg, (list, tuple)):
                    has_source = True
                    enabled.update(parse_platform_list(p_cfg))
        except Exception:
            pass

    if not has_source:
        if cfg is None:
            try:
                if CONFIG_PATH.is_file():
                    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                cfg = None
        if cfg and isinstance(cfg, dict):
            cfg_enabled = cfg.get("enabled_platforms") or cfg.get("active_platforms")
            if cfg_enabled is not None:
                has_source = True
                enabled.update(parse_platform_list(cfg_enabled))

    if not has_source:
        return None
    return enabled


def is_platform_enabled(
    platform: str,
    cfg: dict[str, Any] | None = None,
    extra_enabled: list[str] | set[str] | str | None = None,
    extra_held: list[str] | set[str] | str | None = None,
) -> bool:
    """Check if a specific platform (or alias) is currently enabled and not held."""
    canonical = canonical_platform_name(platform)
    if is_platform_held(canonical, cfg=cfg, extra_held=extra_held):
        return False
    enabled = get_enabled_platforms(cfg=cfg, extra_enabled=extra_enabled)
    if enabled is not None:
        return canonical in enabled
    return True


def load_config() -> dict[str, Any]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["timezone"] = os.environ.get("PUBLISH_TZ", cfg.get("timezone", "Asia/Ho_Chi_Minh"))
    try:
        ZoneInfo(cfg["timezone"])
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError(f"invalid publish timezone: {cfg['timezone']!r}") from exc
    meta = cfg.setdefault("meta", {})
    meta["page_id"] = os.environ.get("FB_PAGE_ID", meta.get("page_id"))
    meta["ig_account_id"] = os.environ.get("IG_ACCOUNT_ID", meta.get("ig_account_id"))
    yt = cfg.setdefault("youtube", {})
    yt["account"] = os.environ.get("YOUTUBE_ACCOUNT", yt.get("account", "primary"))
    cfg["held_platforms"] = sorted(list(get_held_platforms(cfg)))
    enabled = get_enabled_platforms(cfg)
    cfg["enabled_platforms"] = sorted(list(enabled)) if enabled is not None else None
    return cfg


def fb_slot_times(cfg: dict[str, Any]) -> list[dt_time]:
    return [_parse_hhmm(s) for s in cfg["slots"]["fb_slots_wib"]]


def yt_slot_times(cfg: dict[str, Any]) -> list[dt_time]:
    return [_parse_hhmm(s) for s in cfg["slots"]["yt_slots_wib"]]


def publish_timezone(cfg: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(cfg.get("timezone", "Asia/Ho_Chi_Minh"))


def next_publish_date(cfg: dict[str, Any], now: datetime | None = None) -> date:
    """Return next calendar date in configured publishing timezone."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(publish_timezone(cfg))
    return local_now.date() + timedelta(days=1)


def publish_slots(cfg: dict[str, Any]) -> list[dt_time]:
    """Three daily Vietnam slots, shared by generation and publishing."""
    values = cfg.get("slots", {}).get("publish_slots_vn")
    if values is None:
        values = cfg.get("slots", {}).get("yt_slots_wib", ["09:15", "14:15", "21:15"])
    return [_parse_hhmm(value) for value in values]


def scheduled_for(cfg: dict[str, Any], slot_index: int, now: datetime | None = None) -> str:
    slots = publish_slots(cfg)
    if slot_index < 0 or slot_index >= len(slots):
        raise ValueError(f"slot_index must be between 0 and {len(slots) - 1}")
    local = datetime.combine(next_publish_date(cfg, now), slots[slot_index], tzinfo=publish_timezone(cfg))
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def publish_timezone_for_locale(locale: str | None, cfg: dict[str, Any] | None = None) -> ZoneInfo:
    """Return timezone for a project's locale, respecting PUBLISH_TZ override."""
    env_tz = os.environ.get("PUBLISH_TZ")
    if env_tz:
        return ZoneInfo(env_tz)
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    from lib.artifact_paths import is_english_locale
    if locale and is_english_locale(locale):
        us_tz = cfg.get("us", {}).get("timezone") or "America/New_York"
        return ZoneInfo(us_tz)
    return publish_timezone(cfg)


def publish_slots_for_locale(locale: str | None, cfg: dict[str, Any] | None = None) -> list[dt_time]:
    """Return configured publish slots for the given locale."""
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    from lib.artifact_paths import is_english_locale
    if locale and is_english_locale(locale):
        values = (
            cfg.get("slots", {}).get("publish_slots_us")
            or cfg.get("us", {}).get("publish_slots")
            or ["09:00", "13:00", "18:00"]
        )
        return [_parse_hhmm(v) for v in values]
    return publish_slots(cfg)


def validate_slot_spacing(slot_times: list[dt_time], min_hours: float = 2.0) -> bool:
    """Validate that consecutive slot times have at least min_hours gap."""
    if len(slot_times) <= 1:
        return True
    sorted_slots = sorted(slot_times)
    min_delta = timedelta(hours=min_hours)
    dummy_date = date(2026, 1, 1)
    for i in range(len(sorted_slots) - 1):
        dt1 = datetime.combine(dummy_date, sorted_slots[i])
        dt2 = datetime.combine(dummy_date, sorted_slots[i + 1])
        if dt2 - dt1 < min_delta:
            return False
    return True

