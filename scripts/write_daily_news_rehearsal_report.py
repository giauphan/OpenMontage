#!/usr/bin/env python3
"""Write an honest, release-blocking outcome report for a rehearsal run."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

MARKER = {"test_only": True, "purpose": "daily-news-rehearsal"}
ROOT_MARKER = ".openmontage-rehearsal-root.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--exit-status", required=True, type=int)
    parser.add_argument("--terminal-stage", required=True)
    parser.add_argument("--successful-ids", default="")
    args = parser.parse_args()

    root = args.root.absolute()
    manifest = args.manifest.absolute()
    if (root.is_symlink() or root.resolve() != root or (root / ".git").exists()
            or (root / ".env").exists() or any(root.glob(".env.*"))):
        return 2
    marker_path = root / ROOT_MARKER
    try:
        if json.loads(marker_path.read_text(encoding="utf-8")) != MARKER:
            return 2
        if manifest.is_symlink() or root not in manifest.resolve().parents:
            return 2
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        bundles = payload["bundles"]
        requested = [bundle["project_id"] for bundle in bundles]
        if len(requested) != 3 or len(set(requested)) != 3:
            return 2
        if ((root / "data" / "newsnow_feed.json").exists()
                or (root / "config" / "live_schedule.json").exists()
                or (root / "config" / "publish_schedule.json").is_symlink()):
            return 2
        if (root / "config" / "publish_schedule.json").exists():
            schedule = json.loads((root / "config" / "publish_schedule.json").read_text(encoding="utf-8"))
            if schedule.get("test_only") is not True or schedule.get("active_projects") != []:
                return 2
    except (OSError, ValueError, KeyError, TypeError):
        return 2

    successful = [item for item in args.successful_ids.split(",") if item]
    if any(item not in requested for item in successful) or len(set(successful)) != len(successful):
        successful = []
    quarantined: list[str] = []
    for project_id in requested:
        if any((root / "projects" / "_failed_generation_recovered").glob(f"{project_id}_*/project")):
            quarantined.append(project_id)
    failed = [project_id for project_id in requested if project_id not in successful]
    evidence_paths = {}
    for project_id in requested:
        evidence_paths[project_id] = [
            str(path.relative_to(root)) for path in sorted((root / "logs").glob(f"*{project_id}*"))
            if path.is_file()
        ]
    status = args.exit_status
    if successful != requested and status == 0:
        status = 1
    report = {
        "test_only": True,
        "shell_executed": True,
        "publication_enabled": False,
        "n5_complete": False,
        "egress_status": "not_asserted; isolation must be enforced by the external runner",
        "requested_project_ids": requested,
        "successful_project_ids": successful,
        "failed_project_ids": failed,
        "quarantined_project_ids": quarantined,
        "terminal_exit_status": status,
        "terminal_stage": args.terminal_stage,
        "stage_evidence_paths": evidence_paths,
        "freshness_policy": {
            "name": "NEWS_MAX_SOURCE_AGE_HOURS",
            "max_age_hours": os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS"),
            "explicitly_configured": bool(os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS")),
        },
    }
    logs = root / "logs"
    if logs.is_symlink():
        return 2
    logs.mkdir(exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".daily-news-rehearsal-report-", dir=logs)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, logs / "daily_news_rehearsal_report.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
