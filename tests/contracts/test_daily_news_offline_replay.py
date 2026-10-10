"""Synthetic contract tests for the offline public-component replay."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.daily_news_replay import execute_replay


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _manifest(tmp_path: Path) -> Path:
    now = datetime.now(timezone.utc).isoformat()
    _write_json(tmp_path / "bundle/feed.json", [
        {"id": f"fixture-{i}", "title": f"SYNTHETIC FIXTURE topic {i}",
         "url": f"https://example.invalid/{i}", "published_at": now,
         "summary": "Synthetic test content; not a factual news claim."}
        for i in range(3)
    ])
    _write_json(tmp_path / "bundle/selector.json", {
        "selected_candidate_id": "fixture-0",
        "research_draft": {"title": "Synthetic test research"},
    })
    _write_json(tmp_path / "bundle/reviewer.json", {
        key: {"passed": True, "score": 4, "notes": "synthetic fixture response; not a human review"}
        for key in ("visual_quality", "audio_sync", "content_appropriateness", "brand_compliance")
    } | {"overall_passed": True, "summary": "Synthetic test response only"})
    project = tmp_path / "bundle/project-fixture"
    (project / "hyperframes").mkdir(parents=True)
    (project / "artifacts").mkdir()
    (project / "assets").mkdir()
    (project / "hyperframes/index.html").write_text("<main>synthetic fixture composition</main>")
    _write_json(project / "artifacts/script_vi.json", {"sections": [{"text": "Synthetic fixture only"}]})
    _write_json(project / "metadata.json", {"fixture_only": True})
    (project / "assets/video.mp4").write_bytes(b"synthetic-media-fixture-not-a-video")
    return _write_json(tmp_path / "bundle/manifest.json", {
        "schema_version": 1,
        "fixture_bundle": True,
        "feed": "feed.json",
        "selection_reply": "selector.json",
        "review_reply": "reviewer.json",
        "projects": [{"id": "fixture-project", "bundle": "project-fixture",
                      "video": "assets/video.mp4", "metadata": "metadata.json"}],
    })


def test_execute_replays_public_selector_and_review_with_explicit_fixture_transport(tmp_path, monkeypatch):
    import scripts.codex_agent_validation as validation

    monkeypatch.delenv("PRODUCTION_RELEASE", raising=False)
    monkeypatch.delenv("STRICT_PRODUCTION", raising=False)
    monkeypatch.delenv("CODEX_AGENT_VALIDATION_MOCK", raising=False)
    monkeypatch.delenv("CLAUDE_AGENT_VALIDATION_MOCK", raising=False)
    monkeypatch.setattr(validation.CodexAgentValidator, "validate_technical_contract",
                        lambda self, path: [validation.ValidationResult("Synthetic technical contract", True, "fixture test only")])
    monkeypatch.setattr(validation.CodexAgentValidator, "_extract_frames",
                        lambda self, video, directory: [Path(directory) / "synthetic-frame.jpg"])
    monkeypatch.setattr(validation, "_probe_audio_streams", lambda path: "synthetic test probe metadata")
    monkeypatch.setattr(validation, "resolve_agent_cli", lambda: pytest.fail("must not discover or launch a live agent"))
    monkeypatch.setattr(validation.subprocess, "run", lambda *args, **kwargs: pytest.fail("test transport must not launch subprocesses"))

    manifest = _manifest(tmp_path)
    report = execute_replay(manifest, str(tmp_path / "fresh-stage"), 24)

    assert report["status"] == "component_replay_passed"
    assert report["test_only"] is True
    assert report["publication_enabled"] is False
    assert report["shell_executed"] is False
    assert report["n5_complete"] is False
    assert report["selection"]["selected_candidate_id"] == "fixture-0"
    marker = tmp_path / "fresh-stage/projects/fixture-project/OFFLINE_REHEARSAL_TEST_ONLY.json"
    assert json.loads(marker.read_text())["test_only"] is True
    assert marker.stat().st_mode & 0o222 == 0
    assert [stage["stage"].split(":")[0] for stage in report["stage_outcomes"]] == [
        "frozen_feed", "public_selector", "technical_validation", "public_strict_review"
    ]
    review = report["stage_outcomes"][-1]["checks"]
    assert all(result["details"]["test_only_transport"] is True for result in review)
    assert (tmp_path / "fresh-stage/rehearsal-report.json").is_file()


def test_execute_refuses_production_or_incomplete_fixture_contract(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    monkeypatch.setenv("PRODUCTION_RELEASE", "1")
    with pytest.raises(ValueError, match="forbidden in production"):
        execute_replay(manifest, str(tmp_path / "stage-production"), 24)

    monkeypatch.delenv("PRODUCTION_RELEASE")
    data = json.loads(manifest.read_text())
    data["fixture_bundle"] = False
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fixture_bundle"):
        execute_replay(manifest, str(tmp_path / "stage-invalid"), 24)


def test_selector_fixture_failure_is_reported_and_does_not_claim_completion(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    _write_json(tmp_path / "bundle/selector.json", {"selected_candidate_id": "fixture-0", "research_draft": None})
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="rejected fixture response"):
        execute_replay(manifest, str(tmp_path / "stage-failed"), 24)
    report = json.loads((tmp_path / "stage-failed/rehearsal-report.json").read_text())
    assert report["status"] == "component_replay_failed"
    assert report["n5_complete"] is False
    assert report["publication_enabled"] is False


@pytest.mark.parametrize("bad_feed", ["/tmp/absolute-feed.json", "../outside.json"])
def test_manifest_rejects_absolute_paths_and_parent_traversal(tmp_path, bad_feed):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    data["feed"] = bad_feed
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="relative path"):
        execute_replay(manifest, str(tmp_path / "stage-escape"), 24)


def test_manifest_rejects_ancestor_symlink(tmp_path):
    manifest = _manifest(tmp_path)
    (tmp_path / "bundle/alias").symlink_to(tmp_path / "bundle", target_is_directory=True)
    data = json.loads(manifest.read_text())
    data["feed"] = "alias/feed.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="must not traverse symlinks"):
        execute_replay(manifest, str(tmp_path / "stage-symlink"), 24)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"selected_candidate_id": "not-in-feed", "research_draft": {"title": "synthetic"}}, "not present in the frozen feed"),
        ({"selected_candidate_id": "fixture-0", "research_status": "incomplete", "research_draft": {"title": "synthetic"}}, "incomplete research"),
    ],
)
def test_selector_fallback_and_out_of_feed_selection_fail_closed(tmp_path, reply, message):
    manifest = _manifest(tmp_path)
    _write_json(tmp_path / "bundle/selector.json", reply)
    with pytest.raises(ValueError, match=message):
        execute_replay(manifest, str(tmp_path / "stage-selector-rejected"), 24)
    report = json.loads((tmp_path / "stage-selector-rejected/rehearsal-report.json").read_text())
    assert report["stage_outcomes"][-1]["stage"] == "public_selector"
    assert report["stage_outcomes"][-1]["status"] == "failed"


@pytest.mark.parametrize("secret_entry", [".env", "config/credentials.json"])
def test_project_bundle_rejects_credentials_and_config_directories(tmp_path, secret_entry):
    manifest = _manifest(tmp_path)
    secret_path = tmp_path / "bundle/project-fixture" / secret_entry
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_entry.startswith("config/"):
        secret_path.write_text('{"api_key":"must-not-stage"}', encoding="utf-8")
        expected_message = "credential/config directory"
    else:
        secret_path.write_text("API_KEY=must-not-stage", encoding="utf-8")
        expected_message = "credential file"
    with pytest.raises(ValueError, match=expected_message):
        execute_replay(manifest, str(tmp_path / "stage-secret"), 24)
    assert not (tmp_path / "stage-secret/projects/fixture-project" / secret_entry).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("video", "/tmp/absolute-video.mp4"),
        ("metadata", "../metadata.json"),
    ],
)
def test_project_media_paths_must_be_relative_and_contained(tmp_path, field, value):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    data["projects"][0][field] = value
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="relative path"):
        execute_replay(manifest, str(tmp_path / "stage-project-path"), 24)


def test_project_bundle_entry_count_is_bounded_before_copy(tmp_path, monkeypatch):
    import lib.daily_news_replay as replay

    manifest = _manifest(tmp_path)
    monkeypatch.setattr(replay, "MAX_BUNDLE_ENTRIES", 2)
    with pytest.raises(ValueError, match="entry-count limit"):
        execute_replay(manifest, str(tmp_path / "stage-entry-limit"), 24)
