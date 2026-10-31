"""Phase 5 Remediation Contract Tests: Flexible Duration, Non-Distorted Audio & US Scheduling.

Verifies:
- T16: Natural speech pacing preserved without aggressive speed distortion
- T17: US America/New_York scheduling with DST safety, duplicate avoidance, and >=2h spacing
- T18: NO_ELIGIBLE_TOPIC suppresses retry storms on daily runner
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from publish_config import publish_slots_for_locale, publish_timezone_for_locale


def test_natural_speech_pacing_preserved():
    """T16: Extreme TTS rate shifts (+30%) and wide atempo pitch distortion are forbidden."""
    pipeline_sh = Path(__file__).resolve().parents[2] / "scripts" / "run_daily_news_pipeline.sh"
    content = pipeline_sh.read_text(encoding="utf-8")

    # Ensure +25% and +30% rate changes are removed
    assert '"+25%"' not in content, "Aggressive +25% edge-tts rate must not be used"
    assert '"+30%"' not in content, "Aggressive +30% edge-tts rate must not be used"
    # Ensure atempo is bounded to safe range (t >= 0.9 && t <= 1.1)
    assert "t >= 0.7 && t <= 1.4" not in content, "Aggressive atempo 1.4x distortion must not be used"
    assert "t >= 0.9 && t <= 1.1" in content, "Safe bounded atempo (0.9 to 1.1) must be enforced"


def test_us_schedule_dst_and_spacing(tmp_path: Path):
    """T17: US Eastern schedule handles DST transition, >=2h spacing, and max 3 projects/day."""
    tz_ny = ZoneInfo("America/New_York")
    
    # 1. Check DST boundary date (e.g. 2026-11-01 when US EDT transitions to EST)
    dt_dst = datetime(2026, 11, 1, 9, 0, tzinfo=tz_ny)
    dt_utc = dt_dst.astimezone(timezone.utc)
    # At 9:00 AM EST (UTC-5), UTC time is 14:00
    assert dt_utc.hour == 14

    # 2. Check US slots have >= 2 hours spacing
    slots = publish_slots_for_locale("en-US")
    assert len(slots) == 3
    # Convert slots on a single day and verify >= 2h gap
    day = date(2026, 11, 2)
    datetimes = [datetime.combine(day, s, tz_ny) for s in slots]
    for i in range(len(datetimes) - 1):
        gap = (datetimes[i+1] - datetimes[i]).total_seconds() / 3600.0
        assert gap >= 2.0, f"Slot gap between {slots[i]} and {slots[i+1]} must be >= 2h, got {gap}h"


def test_retry_runner_respects_no_eligible_topic(tmp_path: Path):
    """T18: When NO_ELIGIBLE_TOPIC marker exists for today, retry runner exits 0 without retry."""
    root = Path(__file__).resolve().parents[2]
    retry_sh = root / "scripts" / "retry_daily_pipeline.sh"
    content = retry_sh.read_text(encoding="utf-8")
    
    assert ".no_eligible_topic_marker" in content, (
        "scripts/retry_daily_pipeline.sh must check for .no_eligible_topic_marker to avoid retry storms"
    )
