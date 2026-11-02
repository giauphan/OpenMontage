"""Extended tests for post-publish project cleanup (R2 through R5 and publisher-level checks)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.publish_active_projects import deactivate_project
from tools.publish_store import publish_key
from tests._publish_cleanup_helpers import (
    FakeStore,
    canonical_records,
    make_project_with_renders,
    write_archive_entry,
)


def test_r2_inspection_and_dry_run_are_strictly_read_only(tmp_path):
    """R2: Eligibility inspection must be strictly read-only and never mutate store or disk."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_r2_inspect"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    class StrictReadOnlyStore:
        def __init__(self):
            self.records = {
                publish_key("2026-09-27", pid, "youtube", "short"): {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "video_id": "yt1"},
                publish_key("2026-09-27", pid, "instagram", "reels"): {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "video_id": "ig1"},
                publish_key("2026-09-27", pid, "facebook", "reels"): {"status": "scheduled", "scheduled_for": "2026-09-27T00:00:00Z", "video_id": "fb1"},
            }

        def get(self, key):
            return self.records.get(key)

        def mark_published(self, *args, **kwargs):
            raise AssertionError("Mutation called during read-only inspection!")

    store = StrictReadOnlyStore()
    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "destinations_incomplete" in reason
    for rec in store.records.values():
        assert rec["status"] == "scheduled"


def test_r3_cleanup_fails_closed_when_stored_hash_missing(tmp_path, monkeypatch):
    """R3: Missing media_sha256 in publication record must fail closed and block cleanup."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_missing_hash"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_missing_hash"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_missing_hash", "publish_date": "2026-09-27"}))
    make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore({
        publish_key("2026-09-27", "cand_missing_hash", "youtube", "short"): {"status": "published"},
        publish_key("2026-09-27", "cand_missing_hash", "instagram", "reels"): {"status": "published"},
        publish_key("2026-09-27", "cand_missing_hash", "facebook", "reels"): {"status": "published"},
    })

    ok = deactivate_project("cand_missing_hash", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r3_cleanup_fails_closed_when_render_file_missing(tmp_path, monkeypatch):
    """R3: Missing local render file must fail closed and block cleanup."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_no_render"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_no_render"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_no_render", "publish_date": "2026-09-27"}))

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_no_render", "published", cut_hash="somehash", full_hash="somehash"))
    ok = deactivate_project("cand_no_render", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r3_cleanup_fails_closed_when_hash_mismatches(tmp_path, monkeypatch):
    """R3: Mismatched media hash between local render and store must block cleanup."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_mismatch_hash"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_mismatch_hash"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_mismatch_hash", "publish_date": "2026-09-27"}))
    h_cut, _ = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_mismatch_hash", "published", cut_hash=h_cut, full_hash="tampered_hash_value"))
    ok = deactivate_project("cand_mismatch_hash", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r3_exact_asset_per_platform_binding(tmp_path):
    """R3: Exact platform routes must bind to their specific render (YT/IG -> cut, FB -> full)."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_platform_routes"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    h_cut, h_full = make_project_with_renders(pdir, "cut content", "full story content")
    assert h_cut != h_full

    wrong_store = FakeStore(canonical_records("2026-09-27", pid, "published", cut_hash=h_cut, full_hash=h_cut))
    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=wrong_store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "media_hash_mismatch for facebook/reels" in reason

    correct_store = FakeStore(canonical_records("2026-09-27", pid, "published", cut_hash=h_cut, full_hash=h_full))
    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=correct_store, date="2026-09-27", root=tmp_path)
    assert eligible is True


def test_r3_archive_fallback_rejects_missing_hashes_when_media_present(tmp_path):
    """R3: Archive fallback must reject present media if tombstone lacks media_hashes."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_no_hash"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    write_archive_entry(tmp_path, pid, include_hashes=False)

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_missing_media_hashes_fail_closed" in reason


def test_r3_archive_fallback_rejects_hash_mismatch(tmp_path):
    """R3: Archive fallback must reject present media if local file hash differs from tombstone."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_mismatch"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    _, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    write_archive_entry(
        tmp_path, pid, media_hashes={"final_reels_vi_9x16.mp4": "old_cut_hash", "final_full_vi_9x16.mp4": h_full}
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_hash_mismatch_with_current_media" in reason


def test_r4_completion_audit_write_failure_surfaces_error(tmp_path, monkeypatch):
    """R4: If post-deletion audit tombstone write fails, deactivate_project surfaces failure."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_post_audit_fail"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_post_audit_fail"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text("{}")
    h_cut, h_full = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    original_write = pap.write_audit_tombstone
    def mock_write(project_id, project_dir, **kwargs):
        if kwargs.get("status") == "cleanup_completed":
            return False
        return original_write(project_id, project_dir, **kwargs)

    monkeypatch.setattr(pap, "write_audit_tombstone", mock_write)

    store = FakeStore(canonical_records("2026-09-27", "cand_post_audit_fail", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_post_audit_fail", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False


def test_r4_interrupted_finalization_with_new_media_fails_closed(tmp_path, monkeypatch):
    """R4: If cleanup was interrupted and newly generated media appears, retry refuses deletion."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_new_media"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_new_media"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text("{}")
    make_project_with_renders(pdir, "new newly rendered cut", "new full")

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_new_media", "published", cut_hash="old_generation_cut_hash", full_hash="old_full"))
    ok = deactivate_project("cand_new_media", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r5_explicit_path_duplicate_is_rejected(tmp_path, monkeypatch):
    """R5: Explicit path cannot bypass duplicate location rejection."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_dup_bypass"}]}), encoding="utf-8")

    p1 = tmp_path / "projects" / "cand_dup_bypass"
    p1.mkdir(parents=True)
    p2 = tmp_path / "projects_news" / "cand_dup_bypass"
    p2.mkdir(parents=True)

    h_cut, h_full = make_project_with_renders(p1)
    make_project_with_renders(p2)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_dup_bypass", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_dup_bypass", project_dir=p1, store=store, date="2026-09-27")
    assert ok is False
    assert p1.exists()
    assert p2.exists()


def test_r5_ancestor_symlink_is_rejected(tmp_path, monkeypatch):
    """R5: Reject paths whose parent/ancestor directory is a symlink."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_parent_sym"}]}), encoding="utf-8")

    real_base = tmp_path / "some_external_dir"
    real_base.mkdir()
    sym_parent = tmp_path / "projects" / "instagram"
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    sym_parent.symlink_to(real_base, target_is_directory=True)

    target_dir = sym_parent / "cand_parent_sym"
    target_dir.mkdir()
    h_cut, h_full = make_project_with_renders(target_dir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_parent_sym", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_parent_sym", project_dir=target_dir, store=store, date="2026-09-27")
    assert ok is False
    assert target_dir.exists()


def test_r5_metadata_id_mismatch_is_rejected(tmp_path, monkeypatch):
    """R5: Reject cleanup if publish_metadata.json contains a conflicting ID."""
    import scripts.publish_active_projects as pap

    config_file = tmp_path / "publish_schedule.json"
    config_file.write_text(json.dumps({"active_projects": [{"project_id": "cand_meta_mismatch"}]}), encoding="utf-8")

    pdir = tmp_path / "projects" / "cand_meta_mismatch"
    pdir.mkdir(parents=True)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": "cand_different_victim"}))
    h_cut, h_full = make_project_with_renders(pdir)

    monkeypatch.setattr(pap, "CONFIG", config_file)
    monkeypatch.setattr(pap, "ROOT", tmp_path)

    store = FakeStore(canonical_records("2026-09-27", "cand_meta_mismatch", "published", cut_hash=h_cut, full_hash=h_full))
    ok = deactivate_project("cand_meta_mismatch", project_dir=pdir, store=store, date="2026-09-27")
    assert ok is False
    assert pdir.exists()


def test_r1_reconcile_youtube_public_uploaded_not_processed_stays_pending(tmp_path):
    """R1: YouTube status with upload_status='uploaded' must NOT mark published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_uploading"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {
            "video_id": "yt_uploading",
            "privacy_status": "public",
            "upload_status": "uploaded",
        }
        res = reconcile_scheduled_record(store, "rec1", rec)
        assert res.get("status") == "scheduled"
        assert store.get("rec1").get("status") == "scheduled"


def test_r1_reconcile_youtube_missing_fields_stays_pending(tmp_path):
    """R1: YouTube status with missing privacy_status or upload_status must NOT mark published."""
    from scripts.check_cleanup_eligibility import reconcile_scheduled_record

    store = FakeStore({
        "rec1": {"status": "scheduled", "scheduled_for": "2026-09-27T08:00:00Z", "platform": "youtube", "video_id": "yt_incomplete"}
    })
    rec = store.get("rec1")

    with patch("tools.publishers.youtube_publisher.YoutubePublisher.check_video_published") as mock_check:
        mock_check.return_value = {"video_id": "yt_incomplete", "upload_status": "processed"}
        assert reconcile_scheduled_record(store, "rec1", rec).get("status") == "scheduled"

        mock_check.return_value = {"video_id": "yt_incomplete", "privacy_status": "public"}
        assert reconcile_scheduled_record(store, "rec1", rec).get("status") == "scheduled"


def test_publisher_level_api_failure_oembed_success_returns_unverified_oembed(monkeypatch, tmp_path):
    """Finding 5: Publisher-level test: API failure with oEmbed success returns unverified_oembed structure."""
    import urllib.request
    from tools.publishers.youtube_publisher import YoutubePublisher

    secret_file = tmp_path / "client_secret.json"
    secret_file.write_text('{"installed": {}}')
    token_file = tmp_path / "youtube_token.json"
    token_file.write_text('{"token": "dummy"}')
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", str(token_file))

    def mock_get_auth(self, s, t):
        raise RuntimeError("HttpError 403: insufficientPermissions")

    monkeypatch.setattr(YoutubePublisher, "_get_authenticated_service", mock_get_auth)

    class MockOembedResponse:
        status = 200
        def read(self):
            return b'{"title": "Sample Title", "author_name": "Sample Author"}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: MockOembedResponse())

    result = YoutubePublisher().check_video_published("vid_pub_test")
    assert result.get("status") == "unverified_oembed"
    assert result.get("video_id") == "vid_pub_test"
    assert result.get("via_oembed") is True
    assert result.get("title") == "Sample Title"
    assert result.get("author_name") == "Sample Author"
    assert "privacy_status" not in result
    assert "upload_status" not in result


def test_publisher_level_api_and_oembed_failure_returns_structured_error(monkeypatch, tmp_path):
    """Finding 5: When both API and oEmbed fail, check_video_published returns structured error."""
    import urllib.error
    import urllib.request
    from tools.publishers.youtube_publisher import YoutubePublisher

    secret_file = tmp_path / "client_secret.json"
    secret_file.write_text('{"installed": {}}')
    token_file = tmp_path / "youtube_token.json"
    token_file.write_text('{"token": "dummy"}')
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", str(token_file))

    def mock_get_auth(self, s, t, *args, **kwargs):
        raise ValueError("AUTH_REQUIRED: Please authenticate by visiting URL")

    monkeypatch.setattr(YoutubePublisher, "_get_authenticated_service", mock_get_auth)
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("Not found 404"))
    )

    result = YoutubePublisher().check_video_published("vid_fail_test")
    assert result.get("status") == "error"
    assert result.get("error_type") == "auth_required"
    assert "AUTH_REQUIRED" in result.get("error", "")


def test_real_publish_store_mark_published_accepts_verified_at_and_remote_status(monkeypatch):
    """Finding 1: Verify real PublishStore.mark_published accepts verified_at & remote_status without TypeError."""
    from tools.publish_store import PublishStore

    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", json.dumps({"project_id": "test-project"}))

    captured_updates = {}
    class MockResponse:
        status_code = 200
        def json(self):
            return {"fields": {}}

    class MockSession:
        def patch(self, url, params=None, json=None, timeout=None):
            captured_updates.update(json.get("fields", {}))
            return MockResponse()

    monkeypatch.setattr("tools.publish_store.Credentials.from_service_account_info", lambda *args, **kwargs: None)
    monkeypatch.setattr("tools.publish_store.AuthorizedSession", lambda creds: MockSession())

    store = PublishStore()
    store.mark_published(
        "test_key_1",
        video_id="v123",
        video_url="https://youtube.com/watch?v=v123",
        published_at="2026-10-01T09:15:00Z",
        verified_at="2026-10-01T09:20:00Z",
        remote_status={"privacy_status": "public", "upload_status": "processed"},
    )
    assert captured_updates.get("status") == {"stringValue": "published"}
    assert captured_updates.get("verified_at") == {"stringValue": "2026-10-01T09:20:00Z"}
    assert "remote_status" in captured_updates


def test_cleanup_boundary_rejects_historical_records_lacking_authoritative_proof(tmp_path):
    """Finding 2: Projects with records marked 'published' but lacking public release proof must fail closed."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_unverified_hist"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    recs = canonical_records("2026-09-27", pid, "published", cut_hash=h_cut, full_hash=h_full)
    recs[publish_key("2026-09-27", pid, "youtube", "short")]["remote_status"] = {
        "privacy_status": "unlisted", "upload_status": "processed"
    }
    store = FakeStore(recs)

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "missing_authoritative_public_evidence" in reason


def test_r3_current_store_pending_or_failed_records_cannot_be_overridden_by_archive(tmp_path):
    """R3: Historical archive tombstone must NOT override current pending/failed store records."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_override_prevented"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))

    write_archive_entry(
        tmp_path, pid, media_hashes={"final_reels_vi_9x16.mp4": h_cut, "final_full_vi_9x16.mp4": h_full}
    )

    active_store = FakeStore({
        publish_key("2026-09-27", pid, "youtube", "short"): {"status": "published", "media_sha256": h_cut},
        publish_key("2026-09-27", pid, "instagram", "reels"): {"status": "scheduled", "video_id": "ig1"},
        publish_key("2026-09-27", pid, "facebook", "reels"): {"status": "published", "media_sha256": h_full},
    })

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=active_store, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "destinations_incomplete" in reason
    assert "instagram/reels (status=scheduled)" in reason


def test_r3_archive_fallback_rejects_missing_date_when_media_present(tmp_path):
    """R3: Archive tombstone with missing date must fail closed when media is present."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_no_date"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    write_archive_entry(
        tmp_path, pid, date=None, media_hashes={"final_reels_vi_9x16.mp4": h_cut, "final_full_vi_9x16.mp4": h_full}
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_missing_date_fail_closed" in reason


def test_r3_archive_fallback_rejects_empty_platform_records_when_media_present(tmp_path):
    """R3: Archive tombstone with empty platform_records must fail closed when media is present."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_empty_plat"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    write_archive_entry(
        tmp_path, pid, platform_records={}, media_hashes={"final_reels_vi_9x16.mp4": h_cut, "final_full_vi_9x16.mp4": h_full}
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_missing_or_empty_platform_records_fail_closed" in reason


def test_r3_archive_fallback_rejects_missing_required_route_in_archive(tmp_path):
    """R3: Archive tombstone missing required platform must fail closed."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_missing_route"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    write_archive_entry(
        tmp_path,
        pid,
        platform_records={"youtube/short": {"status": "published"}, "instagram/reels": {"status": "published"}},
        media_hashes={"final_reels_vi_9x16.mp4": h_cut, "final_full_vi_9x16.mp4": h_full},
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "audit_archive_incomplete_destinations_fail_closed" in reason


def test_r3_archive_fallback_valid_fully_evidenced_recovery_allows_cleanup(tmp_path):
    """R3: Valid archive tombstone with matching hashes across all routes allows cleanup."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_valid_full"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    write_archive_entry(
        tmp_path, pid, media_hashes={"final_reels_vi_9x16.mp4": h_cut, "final_full_vi_9x16.mp4": h_full}
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is True
    assert reason == "verified_via_audit_archive"


def test_r3_archive_fallback_already_absent_directory_recovery_allows_idempotent_cleanup(tmp_path):
    """R3: Archive tombstone allows idempotent recovery when directory is already deleted."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_already_deleted"
    pdir = tmp_path / "projects" / pid
    write_archive_entry(
        tmp_path, pid, media_hashes={"final_reels_vi_9x16.mp4": "cut_hash_1", "final_full_vi_9x16.mp4": "full_hash_1"}
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is True
    assert reason == "verified_via_audit_archive"


def test_r3_archive_fallback_newly_present_render_file_fails_closed(tmp_path):
    """R3: Newly present/unrecognized render file in project not accounted for in archive fails closed."""
    from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup

    pid = "cand_arch_new_file"
    pdir = tmp_path / "projects" / pid
    pdir.mkdir(parents=True)
    h_cut, h_full = make_project_with_renders(pdir)
    (pdir / "publish_metadata.json").write_text(json.dumps({"id": pid, "publish_date": "2026-09-27"}))
    (pdir / "renders" / "bonus_render.mp4").write_text("bonus unrecorded content")
    write_archive_entry(
        tmp_path, pid, media_hashes={"final_reels_vi_9x16.mp4": h_cut, "final_full_vi_9x16.mp4": h_full}
    )

    eligible, reason, _ = is_project_eligible_for_cleanup(pid, project_dir=pdir, store=None, date="2026-09-27", root=tmp_path)
    assert eligible is False
    assert "unrecognized_new_media_file_in_archive_check" in reason
