"""Release-boundary contracts for news provenance requirements."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.news_release_gate import is_news_project, require_news_evidence

def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_news_project(root: Path) -> Path:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    source = b"TEST ONLY: fictional source fixture; not production evidence.\n"
    (artifacts / "source-test.txt").write_bytes(source)
    script_bytes = json.dumps({"sections": [{"id": "1", "text_vi": "TEST ONLY: fictional release-gate claim."}]},
                              separators=(",", ":")).encode()
    (artifacts / "script_vi.json").write_bytes(script_bytes)
    # Relative fixture times keep the evidence fresh at execution time while
    # still running the real validator, including its future-date checks.
    now = datetime.now(timezone.utc)
    # Test-only human/editorial attestations. Never use these as production evidence.
    evidence = {
        "version": "1.0",
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "claims": [{"section_id": "1", "claim": "TEST ONLY: fictional provenance record", "source_ids": ["test"],
                    "reviewer": "TEST-ONLY editor", "reviewed_at": iso_utc(now - timedelta(seconds=30)),
                    "review_status": "approved"}],
        "sources": [{"id": "test", "url": "https://fixture.invalid/test", "status": "available",
                     "published_at": iso_utc(now - timedelta(hours=4)),
                     "updated_at": iso_utc(now - timedelta(hours=3)),
                     "retrieved_at": iso_utc(now - timedelta(hours=1)), "content_path": "artifacts/source-test.txt",
                     "content_sha256": hashlib.sha256(source).hexdigest(),
                     "excerpt": "TEST ONLY: fictional source fixture"}],
        "contradictions": [],
    }
    (artifacts / "news_evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    (root / "project.json").write_text(json.dumps({"pipeline_type": "newsnow"}), encoding="utf-8")
    return root


def test_valid_news_evidence_passes(tmp_path, monkeypatch):
    project = make_news_project(tmp_path / "news-project")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    assert require_news_evidence(project) is not None


@pytest.mark.parametrize("status", ["pending", "rejected", None])
def test_nonapproved_claim_fails_release_gate(tmp_path, monkeypatch, status):
    project = make_news_project(tmp_path / "news-project")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    evidence_path = project / "artifacts/news_evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if status is None:
        evidence["claims"][0].pop("review_status", None)
    else:
        evidence["claims"][0]["review_status"] = status
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="review_status"):
        require_news_evidence(project)


def test_missing_evidence_fails_closed(tmp_path, monkeypatch):
    project = tmp_path / "cand_missing_evidence"
    project.mkdir()
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    with pytest.raises(ValueError, match="News evidence gate failed"):
        require_news_evidence(project)


def test_missing_policy_fails_closed(tmp_path, monkeypatch):
    project = make_news_project(tmp_path / "news-project")
    monkeypatch.delenv("NEWS_MAX_SOURCE_AGE_HOURS", raising=False)
    with pytest.raises(ValueError, match="NEWS_MAX_SOURCE_AGE_HOURS"):
        require_news_evidence(project)


def test_stale_source_and_script_mutation_fail(tmp_path, monkeypatch):
    project = make_news_project(tmp_path / "news-project")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    evidence_path = project / "artifacts/news_evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    payload["sources"][0]["published_at"] = iso_utc(now - timedelta(hours=72))
    payload["sources"][0]["updated_at"] = iso_utc(now - timedelta(hours=48))
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="News evidence gate failed"):
        require_news_evidence(project)

    project = make_news_project(tmp_path / "changed-script")
    (project / "artifacts/script_vi.json").write_bytes(
        (project / "artifacts/script_vi.json").read_bytes() + b" "
    )
    with pytest.raises(ValueError, match="News evidence gate failed"):
        require_news_evidence(project, "24")


def test_bridge_metadata_shapes_and_colon_source_feeds_identify_news(tmp_path):
    project = tmp_path / "renamed-bridge-project"
    project.mkdir()
    bridge_metadata = {"metadata": {"candidate_id": "cand_x", "source_feed": "newsnow:github"}}
    assert is_news_project(project, bridge_metadata)
    assert is_news_project(project, {"metadata": {"source_feed": "newsnow:github"}})

    brief = project / "artifacts"
    brief.mkdir()
    (brief / "research_brief.json").write_text(
        json.dumps({"metadata": {"candidate_id": "cand_x", "source_feed": "newsnow:github"}}),
        encoding="utf-8",
    )
    assert is_news_project(project)


def test_renamed_project_with_news_evidence_artifact_is_news(tmp_path):
    project = make_news_project(tmp_path / "news-project")
    renamed = project.rename(tmp_path / "renamed-project")
    assert is_news_project(renamed)


def test_dangling_news_evidence_symlink_still_classifies_as_news(tmp_path, monkeypatch):
    project = tmp_path / "renamed-project"
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "news_evidence.json").symlink_to(artifacts / "missing-evidence.json")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")

    assert is_news_project(project)
    with pytest.raises(ValueError, match="News evidence gate failed"):
        require_news_evidence(project)


def test_malformed_explicit_news_markers_fail_closed(tmp_path, monkeypatch):
    project = tmp_path / "renamed-project"
    project.mkdir()
    artifacts = project / "artifacts"
    artifacts.mkdir()
    (artifacts / "news_evidence.json").write_text("{", encoding="utf-8")
    monkeypatch.setenv("NEWS_MAX_SOURCE_AGE_HOURS", "24")
    assert is_news_project(project)
    with pytest.raises(ValueError, match="News evidence gate failed"):
        require_news_evidence(project)

    (artifacts / "news_evidence.json").unlink()
    (project / "project.json").write_text(
        '{"pipeline_type": "newsnow",', encoding="utf-8"
    )
    assert is_news_project(project)


def test_unrelated_video_pipelines_remain_unclassified(tmp_path):
    for pipeline in ("cinematic", "animated-explainer"):
        unrelated = tmp_path / pipeline
        unrelated.mkdir()
        (unrelated / "project.json").write_text(json.dumps({"pipeline_type": pipeline}), encoding="utf-8")
        assert not is_news_project(unrelated)
        assert require_news_evidence(unrelated) is None
    assert is_news_project(tmp_path / "cand_generated")


def test_publish_batch_force_and_preflight_bypass_cannot_skip_news_gate(tmp_path, monkeypatch):
    from scripts import publish_manual_video

    project = make_news_project(tmp_path / "news-project")
    monkeypatch.delenv("NEWS_MAX_SOURCE_AGE_HOURS", raising=False)

    class NeverClaimStore:
        def claim(self, **kwargs):
            pytest.fail("claim must not happen when news policy is missing")

    with pytest.raises(ValueError, match="NEWS_MAX_SOURCE_AGE_HOURS"):
        publish_manual_video.publish_batch(
            {"id": "news", "title": "Test", "description": "Test", "yt_shorts": "x"},
            project, NeverClaimStore(), force=True, enforce_preflight=False,
        )
