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
from datetime import time as dt_time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "publish_schedule.json"


def _parse_hhmm(value: str) -> dt_time:
    hh, mm = value.split(":", 1)
    return dt_time(int(hh), int(mm))


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["timezone"] = os.environ.get("PUBLISH_TZ", cfg.get("timezone", "Asia/Jakarta"))
    meta = cfg.setdefault("meta", {})
    meta["page_id"] = os.environ.get("FB_PAGE_ID", meta.get("page_id"))
    meta["ig_account_id"] = os.environ.get("IG_ACCOUNT_ID", meta.get("ig_account_id"))
    yt = cfg.setdefault("youtube", {})
    yt["account"] = os.environ.get("YOUTUBE_ACCOUNT", yt.get("account", "primary"))
    return cfg


def fb_slot_times(cfg: dict) -> list[dt_time]:
    return [_parse_hhmm(s) for s in cfg["slots"]["fb_slots_wib"]]


def yt_slot_times(cfg: dict) -> list[dt_time]:
    return [_parse_hhmm(s) for s in cfg["slots"]["yt_slots_wib"]]
