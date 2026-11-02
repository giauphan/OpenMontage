"""Shared test helpers for post-publish project cleanup tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.publish_store import file_sha256, publish_key


class FakeStore:
    def __init__(self, records: dict[str, Any]):
        self.records = records

    def get(self, key: str):
        return self.records.get(key)

    def mark_published(self, key: str, **kwargs):
        rec = dict(self.records.get(key, {}))
        rec["status"] = "published"
        rec.update(kwargs)
        self.records[key] = rec
        return rec


def make_project_with_renders(
    project_dir: Path,
    cut_content: str = "default cut reel",
    full_content: str = "default full reel",
) -> tuple[str, str]:
    renders = project_dir / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    r_cut = renders / "final_reels_vi_9x16.mp4"
    r_cut.write_text(cut_content)
    r_full = renders / "final_full_vi_9x16.mp4"
    r_full.write_text(full_content)
    return file_sha256(r_cut), file_sha256(r_full)


def canonical_records(
    date: str,
    topic: str,
    facebook_status: str,
    cut_hash: str | None = None,
    full_hash: str | None = None,
) -> dict[str, Any]:
    return {
        publish_key(date, topic, "youtube", "short"): {
            "status": "published",
            "media_sha256": cut_hash or "cut_hash_dummy",
            "remote_status": {"privacy_status": "public", "upload_status": "processed"},
        },
        publish_key(date, topic, "instagram", "reels"): {
            "status": "published",
            "media_sha256": cut_hash or "cut_hash_dummy",
            "remote_status": {"status": "published"},
        },
        publish_key(date, topic, "facebook", "reels"): {
            "status": facebook_status,
            "media_sha256": full_hash or cut_hash or "full_hash_dummy",
            "remote_status": {"status": "published"} if facebook_status == "published" else None,
        },
    }


def write_archive_entry(
    tmp_path: Path,
    project_id: str,
    date: str | None = "2026-09-27",
    cleanup_state: str = "cleanup_completed",
    platform_records: dict[str, Any] | None = None,
    media_hashes: dict[str, str] | None = None,
    include_hashes: bool = True,
) -> Path:
    """Helper to write a published_archive.jsonl entry."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    archive_file = logs_dir / "published_archive.jsonl"
    default_platforms = {
        "youtube/short": {"status": "published"},
        "instagram/reels": {"status": "published"},
        "facebook/reels": {"status": "published"},
    }
    entry: dict[str, Any] = {
        "project_id": project_id,
        "cleanup_state": cleanup_state,
        "date": date,
        "platform_records": default_platforms if platform_records is None else platform_records,
    }
    if include_hashes and media_hashes is not None:
        entry["media_hashes"] = media_hashes
    with open(archive_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return archive_file
