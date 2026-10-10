"""Preserve failed daily-news project workspaces for later diagnosis."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
RECOVERY_NAME = "_failed_generation_recovered"
LIVE_STATUSES = {"published", "scheduled", "publishing", "live", "active"}


def _has_live_marker(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"status", "publish_status"} and str(item).lower() in LIVE_STATUSES:
                return True
            if key in {"published", "scheduled"} and item is True:
                return True
            if _has_live_marker(item):
                return True
    elif isinstance(value, list):
        return any(_has_live_marker(item) for item in value)
    return False


def _project_is_live(projects: Path, project_id: str, source: Path) -> bool:
    """Fail closed for scheduled projects or markers indicating live publication."""
    schedule_path = projects.parent / "config" / "publish_schedule.json"
    if schedule_path.exists() or schedule_path.is_symlink():
        if schedule_path.is_symlink():
            raise ValueError("publish schedule is a symlink; refusing quarantine")
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        active = schedule.get("active_projects")
        if not isinstance(active, list):
            raise ValueError("publish schedule has no valid active_projects list")
        if any(
            (item.get("project_id") if isinstance(item, dict) else item) == project_id
            for item in active
        ):
            return True

    project_marker = source / "project.json"
    if project_marker.is_symlink():
        raise ValueError("project marker is a symlink; refusing quarantine")
    if project_marker.exists():
        marker = json.loads(project_marker.read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            raise ValueError("project marker is not an object")
        marker_id = marker.get("project_id")
        if marker_id is not None and marker_id != project_id:
            raise ValueError("project marker identity does not match project id")
        if _has_live_marker(marker):
            return True

    metadata_path = source / "publish_metadata.json"
    if metadata_path.is_symlink():
        raise ValueError("publish metadata is a symlink; refusing quarantine")
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("publish metadata is not an object")
        metadata_id = metadata.get("id") or metadata.get("project_id")
        if metadata_id is not None and metadata_id != project_id:
            raise ValueError("publish metadata identity does not match project id")
        if _has_live_marker(metadata):
            return True
    return False


def quarantine(projects_dir: Path, project_id: str, reason: str) -> Path:
    """Atomically move one eligible direct-child project to unique recovery storage."""
    if (
        not PROJECT_ID_RE.fullmatch(project_id)
        or project_id in {".", ".."}
        or project_id == RECOVERY_NAME
        or project_id.startswith(RECOVERY_NAME + "_")
    ):
        raise ValueError("invalid or reserved project id")
    if not reason or len(reason) > 500 or "\x00" in reason:
        raise ValueError("reason must contain 1-500 printable characters")

    requested_projects = Path(projects_dir)
    if requested_projects.is_symlink():
        raise ValueError("projects directory must not be a symlink")
    projects = requested_projects.resolve(strict=True)
    source = projects / project_id
    if source.is_symlink() or not source.is_dir():
        raise ValueError("project must be an existing, non-symlink directory")
    if source.resolve(strict=True).parent != projects:
        raise ValueError("project path escapes projects directory")
    if _project_is_live(projects, project_id, source):
        raise ValueError("project is scheduled or marked live; refusing quarantine")

    recovery = projects / RECOVERY_NAME
    if recovery.is_symlink():
        raise ValueError("recovery directory must not be a symlink")
    recovery.mkdir(mode=0o700, exist_ok=True)
    if not recovery.is_dir() or recovery.resolve(strict=True).parent != projects:
        raise ValueError("recovery directory is not a safe direct child")

    while True:
        destination = recovery / f"{project_id}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex}"
        try:
            destination.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue

    (destination / "failure_reason.txt").write_text(reason.rstrip() + "\n", encoding="utf-8")
    # Moving into a newly-created, unique destination cannot replace existing data.
    os.rename(source, destination / "project")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("projects_dir", type=Path)
    parser.add_argument("project_id")
    parser.add_argument("reason")
    args = parser.parse_args()
    try:
        destination = quarantine(args.projects_dir, args.project_id, args.reason)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
