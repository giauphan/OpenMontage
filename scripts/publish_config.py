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
