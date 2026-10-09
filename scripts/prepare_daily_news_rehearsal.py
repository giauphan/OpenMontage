#!/usr/bin/env python3
"""Validate a frozen daily-news rehearsal manifest without touching live inputs.

Manifest v1: {"version":1,"bundles":[{"project_id":...,"project_dir":...}]}
Each bundle directory is a complete frozen projects/<id> tree with artifacts,
assets, hyperframes/index.html, and hyperframes_reels/index.html.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.daily_news_replay import (
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_ENTRIES,
    MAX_BUNDLE_FILES,
    _copy_project_bundle,
    _has_symlink_component,
    _manifest_path,
)

MARKER = ".openmontage-rehearsal-root.json"
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
REQUIRED = (
    "artifacts/research_brief.json",
    "artifacts/script_vi.json",
    "artifacts/proposal_packet.json",
    "artifacts/selector_reply.json",
    "artifacts/director_reply.json",
    "artifacts/reviewer_reply.json",
    "artifacts/news_evidence.json",
    "assets/narration.mp3",
    "assets/music-bg.mp3",
    "hyperframes/index.html",
    "hyperframes_reels/index.html",
)


def fail(message: str) -> int:
    print(f"rehearsal bundle error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--max-source-age-hours", required=True, type=float)
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_source_age_hours) or not 0 < args.max_source_age_hours <= 720:
        return fail("NEWS_MAX_SOURCE_AGE_HOURS must be finite and in (0, 720]")
    raw_root = args.root.expanduser().absolute()
    raw_manifest = args.manifest.expanduser().absolute()
    if _has_symlink_component(raw_root) or _has_symlink_component(raw_manifest):
        return fail("staging root and manifest paths must not traverse symlinks")
    if raw_root.is_symlink() or raw_manifest.is_symlink():
        return fail("staging root and manifest must not be symlinks")
    root = raw_root.resolve()
    manifest = raw_manifest.resolve()
    if not root.is_dir():
        return fail("staging root must already exist as a directory")
    if (root / "projects").exists() or (root / "projects").is_symlink():
        return fail("a rehearsal staging root must not contain existing projects")
    if (root / "logs").exists() or (root / "logs").is_symlink():
        return fail("a rehearsal staging root must not contain existing logs")
    feed_path = root / "data" / "newsnow_feed.json"
    if feed_path.exists() or feed_path.is_symlink():
        return fail("a rehearsal staging root must not contain a live NewsNow feed")
    if (root / ".git").exists() or (root / ".git").is_symlink():
        return fail("a rehearsal staging root must not be a git checkout/worktree")
    if (root / ".env").exists() or any(root.glob(".env.*")):
        return fail("a rehearsal staging root must not contain .env files")
    config_dir = root / "config"
    if config_dir.is_symlink():
        return fail("rehearsal config directory must not be a symlink")
    schedule_path = config_dir / "publish_schedule.json"
    if schedule_path.exists() or schedule_path.is_symlink():
        return fail("a rehearsal staging root must not contain a live publish schedule")
    marker = root / MARKER
    if marker.is_symlink() or not marker.is_file():
        return fail(f"dedicated staging root lacks {MARKER}: {root}")
    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        if marker_data != {"test_only": True, "purpose": "daily-news-rehearsal"}:
            return fail("staging marker contents do not match the exact test-only contract")
    except (OSError, ValueError) as exc:
        return fail(f"invalid staging marker: {exc}")
    if manifest == root or root not in manifest.parents:
        return fail("manifest must be contained inside the dedicated staging root")
    if not manifest.is_file():
        return fail(f"manifest does not exist: {manifest}")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return fail(f"cannot parse manifest: {exc}")
    bundles = data.get("bundles") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(bundles, list) or not 3 <= len(bundles) <= 3:
        return fail("manifest v1 requires exactly three bundles (the bounded pipeline limit)")
    ids: list[str] = []
    selected_ids: set[str] = set()
    topic_titles: set[str] = set()
    sources: list[Path] = []
    total_entries = 0
    total_files = 0
    total_bytes = 0
    for item in bundles:
        if not isinstance(item, dict):
            return fail("every bundle must be an object")
        project_id, source = item.get("project_id"), item.get("project_dir")
        if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
            return fail("invalid project_id")
        if project_id in ids:
            return fail(f"duplicate project_id: {project_id}")
        if (not isinstance(source, str) or not source.strip()
                or Path(source).is_absolute() or PureWindowsPath(source).is_absolute()
                or PureWindowsPath(source).drive or ".." in Path(source).parts):
            return fail(f"{project_id}: project_dir must be a safe relative path")
        try:
            source_path = _manifest_path(manifest.parent, source, f"{project_id} project_dir")
        except (OSError, ValueError, RuntimeError) as exc:
            return fail(str(exc))
        if not source_path.is_dir():
            return fail(f"{project_id}: project_dir must be a directory")
        try:
            _copy_project_bundle(source_path, None)
        except (OSError, ValueError, RuntimeError) as exc:
            return fail(f"{project_id}: frozen bundle rejected: {exc}")
        for path in source_path.rglob("*"):
            total_entries += 1
            if path.is_file():
                total_files += 1
                total_bytes += path.stat().st_size
        if total_entries > MAX_BUNDLE_ENTRIES or total_files > MAX_BUNDLE_FILES or total_bytes > MAX_BUNDLE_BYTES:
            return fail("combined bundles exceed file, entry, or 2 GB copy bounds")
        for rel in REQUIRED:
            path = source_path / rel
            if not path.is_file() or path.stat().st_size == 0:
                return fail(f"{project_id}: missing/empty frozen input {rel}")
        documents: dict[str, object] = {}
        for rel in REQUIRED[:7]:
            try:
                documents[rel] = json.loads((source_path / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return fail(f"{project_id}: invalid JSON in {rel}: {exc}")
        selector = documents["artifacts/selector_reply.json"]
        if (not isinstance(selector, dict)
                or not isinstance(selector.get("selected_candidate_id"), str)
                or not selector["selected_candidate_id"].strip()
                or not isinstance(selector.get("research_draft"), dict)):
            return fail(f"{project_id}: selector_reply.json needs selected_candidate_id and research_draft object")
        selected_id = selector["selected_candidate_id"].strip()
        title = selector["research_draft"].get("title")
        if selected_id in selected_ids:
            return fail(f"duplicate selected_candidate_id across bundles: {selected_id}")
        if not isinstance(title, str) or not title.strip() or title.casefold().strip() in topic_titles:
            return fail(f"{project_id}: research_draft.title must be non-empty and unique across bundles")
        selected_ids.add(selected_id)
        topic_titles.add(title.casefold().strip())
        if not isinstance(documents["artifacts/director_reply.json"], dict):
            return fail(f"{project_id}: director_reply.json must be an object")
        reviewer = documents["artifacts/reviewer_reply.json"]
        reviewer_categories = ("visual_quality", "audio_sync", "content_appropriateness", "brand_compliance")
        if (not isinstance(reviewer, dict)
                or not isinstance(reviewer.get("overall_passed"), bool)
                or any(not isinstance(reviewer.get(key), dict) for key in reviewer_categories)):
            return fail(f"{project_id}: reviewer_reply.json does not satisfy the strict-review reply contract")
        ids.append(project_id)
        sources.append(source_path)
    if len(ids) < 3:
        return fail("at least three unique project ids are required")

    projects = root / "projects"
    for project_id in ids:
        if (projects / project_id).exists() or (projects / project_id).is_symlink():
            return fail(f"refusing to overwrite existing staging project: {projects / project_id}")
    projects.mkdir(parents=True, exist_ok=True)
    for project_id, source in zip(ids, sources):
        destination = projects / project_id
        staging = Path(tempfile.mkdtemp(prefix=f".rehearsal-staging-{project_id}-", dir=projects))
        release_marker = staging / "OFFLINE_REHEARSAL_TEST_ONLY.json"
        try:
            release_marker.write_text(
                json.dumps({"test_only": True, "purpose": "daily-news-rehearsal"}) + "\n",
                encoding="utf-8",
            )
            _copy_project_bundle(source, staging, allow_existing_destination=True)
            (staging / ".openmontage-test-only").write_text(
                "Daily news rehearsal output; never publish or release.\n", encoding="utf-8"
            )
            if destination.exists() or destination.is_symlink():
                return fail(f"refusing to promote over existing staging project: {destination}")
            os.rename(staging, destination)
        except (OSError, ValueError, RuntimeError) as exc:
            return fail(f"{project_id}: frozen bundle copy failed; staging data preserved at {staging}: {exc}")
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "test_only": True,
            "timezone": "Asia/Ho_Chi_Minh",
            "active_projects": [],
            "slots": {"yt_slots_wib": ["09:15", "14:15", "21:15"],
                      "fb_slots_wib": ["10:15", "15:15", "22:15"],
                      "publish_slots_vn": ["09:15", "14:15", "21:15"]},
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print("\n".join(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
