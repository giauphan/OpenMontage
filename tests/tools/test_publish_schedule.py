from datetime import datetime, timezone

import pytest

from scripts.publish_active_projects import scheduled_projects_for_slot
from scripts.publish_config import load_config, scheduled_for


def test_slot_filter_skips_legacy_and_malformed_entries(capsys):
    projects = [
        "legacy-project",
        {"project_id": "missing-date", "publish_time": "09:15"},
        {"project_id": "wrong-slot", "publish_date": "2026-08-29", "publish_time": "14:15"},
        {"project_id": "due", "publish_date": "2026-08-29", "publish_time": "09:15"},
        {"publish_date": "2026-08-29", "publish_time": "09:15"},
    ]

    res = scheduled_projects_for_slot(projects, "09:15", "2026-08-29")
    assert len(res) == 1
    assert res[0]["project_id"] == "due"
    assert res[0]["publish_date"] == "2026-08-29"
    assert res[0]["publish_time"] == "09:15"
    output = capsys.readouterr().out
    assert "legacy-project" in output
    assert "missing-date" in output
    assert "<unknown>" in output


def test_invalid_timezone_is_rejected(monkeypatch):
    monkeypatch.setenv("PUBLISH_TZ", "not/a-timezone")
    with pytest.raises(ValueError, match="invalid publish timezone"):
        load_config()


def test_scheduled_for_uses_configured_timezone_and_slot():
    cfg = {"timezone": "Asia/Ho_Chi_Minh", "slots": {"publish_slots_vn": ["09:15"]}}
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert scheduled_for(cfg, 0, now) == "2026-08-29T02:15:00Z"
