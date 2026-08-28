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

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "publish_schedule.json"


def _parse_hhmm(value: str) -> dt_time:
    hh, mm = value.split(":", 1)
    return dt_time(int(hh), int(mm))


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
