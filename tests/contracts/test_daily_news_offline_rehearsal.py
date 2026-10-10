"""Safety contracts for the daily-news rehearsal staging preflight."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.rehearse_daily_news_offline import ROOT, stage_rehearsal, validate_feed


def frozen_feed(path: Path, *, age_hours: float = 1) -> Path:
    published = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    payload = [
        {
            "id": f"fixture-{number}",
            "title": f"TEST FIXTURE ONLY — topic {number}",
            "url": f"https://example.invalid/fixture/{number}",
            "published_at": published,
            "source_feed": "offline-test-fixture",
        }
        for number in range(3)
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_stages_only_entrypoint_and_frozen_feed_and_reports_blockers(tmp_path: Path):
    feed = frozen_feed(tmp_path / "frozen-feed.json")
    destination = tmp_path / "fresh-stage"

    report = stage_rehearsal(str(destination), feed, 24)

    assert report["status"] == "blocked_before_execution"
    assert report["cost_usd"] == 0
    assert report["publication_enabled"] is False
    assert report["external_network_used"] is False
    gates = {entry["name"]: entry["status"] for entry in report["gates"]}
    assert gates["director_transport_is_deterministic_and_injected"] == "blocked"
    assert gates["project_news_evidence_gate"] == "present_not_evaluated"
    assert "The daily entrypoint has a project evidence gate, but no project-bound script/source evidence bundle is staged or validated." in report["blockers"]
    assert gates["real_render_audio_subtitle_and_quality_gates"] == "not_run"
    assert gates["failure_recovery_and_resume_idempotency"] == "not_run"
    assert gates["three_scheduled_equivalent_runs"] == "not_run"
    assert (destination / "scripts/run_daily_news_pipeline.sh").read_bytes() == (
        ROOT / "scripts/run_daily_news_pipeline.sh"
    ).read_bytes()
    assert (destination / "data/newsnow_feed.json").read_bytes() == feed.read_bytes()
    assert sorted(path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()) == [
        "data/newsnow_feed.json",
        "rehearsal-report.json",
        "scripts/run_daily_news_pipeline.sh",
    ]
    assert not (destination / ".env").exists()
    assert not (destination / "node_modules").exists()
    assert json.loads((destination / "rehearsal-report.json").read_text())["status"] == "blocked_before_execution"


def test_refuses_preexisting_stage_without_touching_it(tmp_path: Path):
    feed = frozen_feed(tmp_path / "frozen-feed.json")
    destination = tmp_path / "already-there"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("leave intact", encoding="utf-8")

    with pytest.raises(FileExistsError):
        stage_rehearsal(str(destination), feed, 24)

    assert sentinel.read_text(encoding="utf-8") == "leave intact"
    assert sorted(path.name for path in destination.iterdir()) == ["keep.txt"]


def test_refuses_source_checkout_and_ancestor_targets(tmp_path: Path):
    feed = frozen_feed(tmp_path / "frozen-feed.json")
    for forbidden in (ROOT, ROOT.parent):
        with pytest.raises(ValueError, match="outside the source checkout"):
            stage_rehearsal(str(forbidden), feed, 24)


def test_requires_explicit_positive_age_and_rejects_stale_or_future_items(tmp_path: Path):
    feed = frozen_feed(tmp_path / "frozen-feed.json", age_hours=25)
    with pytest.raises(ValueError, match="stale"):
        validate_feed(feed, 24)
    with pytest.raises(ValueError, match="finite positive"):
        validate_feed(feed, 0)

    future = frozen_feed(tmp_path / "future-feed.json", age_hours=-1)
    with pytest.raises(ValueError, match="future"):
        validate_feed(future, 24)


def test_rejects_duplicate_topics_and_unzoned_timestamps(tmp_path: Path):
    feed = frozen_feed(tmp_path / "frozen-feed.json")
    items = json.loads(feed.read_text(encoding="utf-8"))
    items[2]["title"] = items[1]["title"]
    feed.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="three distinct topic titles"):
        validate_feed(feed, 24)

    items[2]["title"] = "TEST FIXTURE ONLY — unique"
    items[2]["published_at"] = "2026-10-09T12:00:00"
    feed.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(ValueError, match="include a timezone"):
        validate_feed(feed, 24)
