from __future__ import annotations

import importlib
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.publishers.social_metadata import meta_caption

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


def test_publish_store_finds_bundled_ffmpeg(monkeypatch):
    module = importlib.import_module("tools.publish_store")
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(Path, "glob", lambda *_args, **_kwargs: [Path("/tools/ffmpeg")])

    assert module._ffmpeg() == "/tools/ffmpeg"


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


@pytest.mark.parametrize("status", ["scheduled", "published"])
def test_publish_store_rejects_cross_date_duplicate_with_platform_record(tmp_path, monkeypatch, status):
    module = importlib.import_module("tools.publish_store")
    asset = tmp_path / "video.mp4"
    asset.write_bytes(b"video")
    existing = {
        "date": "2026-09-01",
        "topic": "topic",
        "status": status,
        "video_id": "platform-video-id",
    }
    store = object.__new__(module.PublishStore)
    updates = []

    monkeypatch.setattr(module, "file_sha256", lambda _path: "source-hash")
    monkeypatch.setattr(module, "media_fingerprint", lambda _path: "visual-hash")
    new_key = module.publish_key("2026-09-02", "topic", "youtube", "short")
    monkeypatch.setattr(store, "create_many_once", lambda _documents: False)
    monkeypatch.setattr(store, "get", lambda key: None if key == new_key else existing)
    monkeypatch.setattr(store, "update", lambda key, data: updates.append((key, data)))

    _key, claimed, conflict = store.claim(
        date="2026-09-02",
        topic="topic",
        platform="youtube",
        account="primary",
        kind="short",
        status="scheduling",
        title="Title",
        asset_path=str(asset),
    )

    assert claimed is False
    assert conflict == existing
    assert updates == []


@pytest.mark.parametrize("status", ["claimed", "scheduling", "scheduled", "published"])
def test_manual_retry_never_mutates_or_uploads_duplicate_active_record(tmp_path, monkeypatch, status):
    module = _load("publish_manual_video")
    project = _project(tmp_path)
    metadata = module.load_metadata(project)
    calls = []

    class Store:
        def claim(self, **_kwargs):
            return "key", False, {"status": status, "video_id": "existing-video"}

        def update(self, *_args, **_kwargs):
            calls.append("update")

        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError(f"unexpected store mutation: {name}")

    monkeypatch.setattr(module, "validate_publish_asset", lambda *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(module.YoutubePublisher, "execute", lambda *_args, **_kwargs: calls.append("youtube"))
    monkeypatch.setattr(module.MetaPublisher, "execute", lambda *_args, **_kwargs: calls.append("meta"))

    result = module.publish_batch(
        metadata,
        project,
        Store(),
        retry_failed=True,
        only_platform="youtube",
    )

    assert result["platforms"]["youtube/short"]["status"] == "skipped"
    assert calls == []


def test_manual_validates_exact_selected_asset_before_store_claim(tmp_path, monkeypatch):
    module = _load("publish_manual_video")
    project = _project(tmp_path)
    custom = project / "renders" / "custom-short.mp4"
    custom.write_bytes(b"video")
    metadata = module.load_metadata(project)
    metadata["yt_shorts"] = "renders/custom-short.mp4"
    calls = []

    class Store:
        def claim(self, **_kwargs):
            calls.append("claim")
            raise AssertionError("claim must not run after asset validation failure")

    monkeypatch.setattr(module, "validate_publish_asset", lambda path, *_args, **_kwargs: (_ for _ in ()).throw(ValueError(f"blank video: {path}")))

    with pytest.raises(ValueError, match="custom-short.mp4"):
        module.publish_batch(metadata, project, Store(), only_platform="youtube")

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
    monkeypatch.setattr(module, "validate_publish_asset", lambda *_args, **_kwargs: calls.append("asset-validation"))
    future_day = (datetime.now().date() + timedelta(days=1))

    with pytest.raises(ValueError, match="quality failed"):
        module.schedule_day(future_day)

    assert calls == []


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("  Title  ", f"  Title {'x' * 2_100}  ", f"Title {'x' * 2_100}"),
        ("Docker", "Dockerizing Python apps", "Docker\n\nDockerizing Python apps"),
        ("Docker", "Docker: Python apps", "Docker: Python apps"),
        ("   ", "  Description only  ", "Description only"),
    ],
)
def test_meta_caption_normalizes_and_deduplicates(title, description, expected):
    caption = meta_caption(title, description)

    assert caption == expected


def test_youtube_scheduler_adds_shorts_hashtag_without_truncating_it(tmp_path, monkeypatch):
    module = _load("schedule_youtube_today")
    project = _project(tmp_path)
    captured = {}
    monkeypatch.setattr(
        module.YoutubePublisher,
        "execute",
        lambda _self, payload: captured.update(payload) or SimpleNamespace(success=True, data={}),
    )

    title = "A" * 94
    module.upload(project, {"yt_shorts": "renders/final_reels_vi_9x16.mp4", "title": title}, "yt_shorts", datetime.now().astimezone())

    assert len(captured["title"]) == 100
    assert captured["title"].endswith(" #Shorts")


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
    assert captured["title"] == "Title #Shorts"


@pytest.mark.parametrize("length", [1, 92, 100, 500])
def test_youtube_short_title_preserves_limit_and_hashtag(length):
    routes = importlib.import_module("tools.publishers.platform_routes")

    title = routes.youtube_shorts_title("x" * length)

    assert len(title) <= 100
    assert title.endswith(" #Shorts")


def test_youtube_short_title_replaces_existing_case_insensitive_hashtag():
    routes = importlib.import_module("tools.publishers.platform_routes")

    assert routes.youtube_shorts_title("Title #shorts") == "Title #Shorts"


def test_manual_publish_quality_gate_rejects_empty_youtube_short_title(tmp_path):
    module = _load("publish_manual_video")
    project = _project(tmp_path)
    (project / "publish_metadata.json").write_text(
        '{"id":"topic","title":"#Shorts","description":"#tintuc #congnghe #ai"}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="YouTube Shorts title validation failed"):
        module.validate_project_quality(project)


def test_publish_driver_only_adds_dry_run_for_dry_run_mode():
    text = (SCRIPTS / "publish_driver.sh").read_text(encoding="utf-8")
    assert '${MODE:+"--dry-run"}' not in text
    assert 'PUBLISH_ARGS=("projects/$CAND")' in text
    assert 'PUBLISH_ARGS+=("--dry-run")' in text
