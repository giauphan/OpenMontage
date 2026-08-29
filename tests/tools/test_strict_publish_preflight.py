from __future__ import annotations

import importlib
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "renders").mkdir(parents=True)
    for name in ("final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"):
        (project / "renders" / name).write_bytes(b"video")
    (project / "publish_metadata.json").write_text(
        '{"id":"topic","title":"Title","description":"Description",'
        '"yt_shorts":"renders/final_reels_vi_9x16.mp4",'
        '"ig_reels":"renders/final_reels_vi_9x16.mp4",'
        '"fb_video":"renders/final_full_vi_9x16.mp4"}',
        encoding="utf-8",
    )
    return project


@pytest.mark.parametrize("extra", [[], ["--dry-run"], ["--retry-failed"], ["--force"], ["--only-platform", "youtube"]])
def test_manual_modes_fail_before_firebase_when_quality_gate_fails(tmp_path, monkeypatch, extra):
    module = _load("publish_manual_video")
    project = _project(tmp_path)
    calls = []

    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="black frames"),
    )
    monkeypatch.setattr(module, "PublishStore", lambda: calls.append("firebase"))
    monkeypatch.setattr(module, "enforce_batch_gap", lambda *_: calls.append("batch-gap"))
    monkeypatch.setattr(sys, "argv", ["publish_manual_video.py", str(project), *extra])

    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert calls == []


def test_manual_preflight_fails_closed_when_media_tools_missing(tmp_path, monkeypatch):
    module = _load("publish_manual_video")
    project = _project(tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "glob", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sys, "argv", ["publish_manual_video.py", str(project), "--dry-run"])

    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


def test_platform_routes_finds_bundled_ffprobe(monkeypatch):
    module = importlib.import_module("tools.publishers.platform_routes")
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "glob", lambda *_args, **_kwargs: [Path("/tools/ffprobe")])

    assert module._ffprobe() == "/tools/ffprobe"


def test_active_project_publisher_delegates_to_manual_authority():
    module = _load("publish_active_projects")
    assert module.PUBLISHER.name == "publish_manual_video.py"


def test_legacy_slot_rejects_unmappable_job_before_claim(monkeypatch):
    module = _load("publish_slot")
    calls = []
    monkeypatch.setattr(module, "PublishStore", lambda: calls.append("firebase"))

    with pytest.raises(ValueError, match="canonical project"):
        module.run("topic1-short")

    assert calls == []


def test_youtube_scheduler_validates_project_before_store_claim(tmp_path, monkeypatch):
    module = _load("schedule_youtube_today")
    project = _project(tmp_path)
    calls = []
    cfg = {
        "timezone": "UTC",
        "youtube": {"account": "primary"},
        "slots": {"yt_slots_wib": ["23:59"]},
        "active_projects": [project.name],
    }

    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "projects").mkdir()
    project.rename(tmp_path / "projects" / project.name)
    monkeypatch.setattr(module, "load_config", lambda: cfg)
    monkeypatch.setattr(module, "PublishStore", lambda: calls.append("firebase"))
    monkeypatch.setattr(
        module,
        "validate_project_quality",
        lambda _project: (_ for _ in ()).throw(ValueError("quality failed")),
    )
    future_day = (datetime.now().date() + timedelta(days=1))

    with pytest.raises(ValueError, match="quality failed"):
        module.schedule_day(future_day)

    assert calls == []


def test_youtube_scheduler_uses_canonical_project_asset(tmp_path, monkeypatch):
    module = _load("schedule_youtube_today")
    project = _project(tmp_path)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "projects").mkdir()
    project.rename(tmp_path / "projects" / project.name)
    publish_at = datetime.now().astimezone()
    captured = {}
    monkeypatch.setattr(
        module.YoutubePublisher,
        "execute",
        lambda _self, payload: captured.update(payload) or SimpleNamespace(success=True, data={}),
    )

    module.upload(tmp_path / "projects" / project.name, {"yt_shorts": "renders/final_reels_vi_9x16.mp4", "title": "Title"}, "yt_shorts", publish_at)

    assert captured["video_path"] == str(tmp_path / "projects" / project.name / "renders" / "final_reels_vi_9x16.mp4")


def test_publish_driver_only_adds_dry_run_for_dry_run_mode():
    text = (SCRIPTS / "publish_driver.sh").read_text(encoding="utf-8")
    assert '${MODE:+"--dry-run"}' not in text
    assert 'PUBLISH_ARGS=("projects/$CAND")' in text
    assert 'PUBLISH_ARGS+=("--dry-run")' in text
