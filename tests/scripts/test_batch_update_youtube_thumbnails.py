from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.batch_update_youtube_thumbnails import (
    run_batch_update,
    update_single_candidate,
)


def test_update_single_candidate_missing_dir(tmp_path: Path):
    res = update_single_candidate(tmp_path / "nonexistent", video_id="vid123")
    assert res["success"] is False
    assert res["status"] == "DIR_NOT_FOUND"


def test_update_single_candidate_already_present(tmp_path: Path):
    pdir = tmp_path / "cand_001"
    thumb_dir = pdir / "thumbnails"
    thumb_dir.mkdir(parents=True)
    thumb_file = thumb_dir / "thumbnail.png"
    # Write > 100KB file
    thumb_file.write_bytes(b"\x00" * 150_000)

    res = update_single_candidate(pdir, video_id="vid123", force=False)
    assert res["success"] is True
    assert res["status"] == "ALREADY_PRESENT"
    assert res["size"] == 150_000


def test_update_single_candidate_regenerates_when_forced_or_placeholder(tmp_path: Path):
    pdir = tmp_path / "cand_002"
    thumb_dir = pdir / "thumbnails"
    thumb_dir.mkdir(parents=True)
    thumb_file = thumb_dir / "thumbnail.png"
    # Write small placeholder < 100KB
    thumb_file.write_bytes(b"\x00" * 20_000)

    with patch("scripts.batch_update_youtube_thumbnails.attach_thumbnail_to_video") as mock_attach:
        mock_attach.return_value = (True, "THUMBNAIL_ATTACHED", None)
        res = update_single_candidate(pdir, video_id="vid123", force=False)
        assert res["success"] is True
        assert res["status"] == "THUMBNAIL_ATTACHED"
        mock_attach.assert_called_once()


def test_run_batch_update(tmp_path: Path):
    p1 = tmp_path / "cand_A"
    p2 = tmp_path / "cand_B"
    p1.mkdir()
    p2.mkdir()

    with patch("scripts.batch_update_youtube_thumbnails.attach_thumbnail_to_video") as mock_attach:
        mock_attach.return_value = (True, "THUMBNAIL_ATTACHED", None)
        targets = [("cand_A", "vidA"), ("cand_B", "vidB")]
        results = run_batch_update(projects_dir=tmp_path, candidates=targets, delay_seconds=0.0)
        assert len(results) == 2
        assert all(r["success"] for r in results)
        assert mock_attach.call_count == 2
