#!/usr/bin/env python3
"""Stage frozen inputs or run a bounded offline public-component replay.

The replay uses explicit fixture transports at selector/reviewer subprocess
boundaries and keeps real media extraction and validation. It does not execute
the daily shell or claim an end-to-end/N5 rehearsal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_feed(feed_path: Path, max_age_hours: float, now: datetime | None = None) -> dict[str, Any]:
    """Validate frozen feed shape, distinctness and explicit freshness limit."""
    if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, (int, float)):
        raise ValueError("max source age must be a finite positive number")
    if not math.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ValueError("max source age must be a finite positive number")
    try:
        feed_bytes = feed_path.read_bytes()
        feed = json.loads(feed_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read frozen feed JSON: {exc}") from exc
    if not isinstance(feed, list) or len(feed) < 3:
        raise ValueError("frozen feed must be a JSON array containing at least three items")

    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    topics: list[dict[str, str]] = []
    for index, item in enumerate(feed):
        label = f"feed[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        item_id = item.get("id")
        title = item.get("title")
        url = item.get("url")
        if not all(isinstance(value, str) and value.strip() for value in (item_id, title, url)):
            raise ValueError(f"{label} requires non-empty id, title and url strings")
        canonical_url = url.strip().lower().rstrip("/")
        if item_id in seen_ids or canonical_url in seen_urls:
            raise ValueError(f"{label} duplicates an earlier feed id or URL")
        seen_ids.add(item_id)
        seen_urls.add(canonical_url)
        published = _parse_timestamp(item.get("published_at"), f"{label}.published_at")
        age_hours = (now_utc - published).total_seconds() / 3600
        if age_hours < 0:
            raise ValueError(f"{label}.published_at is in the future")
        if age_hours > max_age_hours:
            raise ValueError(f"{label} is stale ({age_hours:.2f}h; limit {max_age_hours:g}h)")
        topics.append({"id": item_id, "title": title.strip(), "url": url.strip()})

    if len({topic["title"].casefold() for topic in topics}) < 3:
        raise ValueError("frozen feed must contain at least three distinct topic titles")
    return {
        "sha256": hashlib.sha256(feed_bytes).hexdigest(),
        "item_count": len(feed),
        "topics": topics,
        "as_of": now_utc.isoformat(),
        "max_source_age_hours": max_age_hours,
    }


def _safe_stage_path(raw_path: str) -> Path:
    requested = Path(raw_path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    parent = requested.parent.resolve()
    destination = parent / requested.name
    if destination == ROOT or ROOT in destination.parents or destination in ROOT.parents:
        raise ValueError("stage directory must be outside the source checkout")
    protected_components = {"projects", "projects_news", "config", "logs"}
    if protected_components.intersection(part.lower() for part in destination.parts):
        raise ValueError("stage directory cannot be inside projects, config, or logs state paths")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing existing stage target: {destination}")
    return destination


def stage_rehearsal(stage_dir: str, feed_path: Path, max_age_hours: float) -> dict[str, Any]:
    """Create a fresh, minimal staging area and honestly report blocked gates."""
    feed_path = feed_path.expanduser()
    if feed_path.is_symlink():
        raise ValueError("frozen feed must be a regular, non-symlink file")
    feed_path = feed_path.resolve(strict=True)
    if not feed_path.is_file():
        raise ValueError("frozen feed must be a regular, non-symlink file")
    feed_info = validate_feed(feed_path, max_age_hours)
    destination = _safe_stage_path(stage_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    try:
        (destination / "scripts").mkdir()
        (destination / "data").mkdir()
        copied_entrypoint = destination / "scripts" / "run_daily_news_pipeline.sh"
        shutil.copyfile(ROOT / "scripts" / "run_daily_news_pipeline.sh", copied_entrypoint)
        staged_feed = destination / "data" / "newsnow_feed.json"
        shutil.copyfile(feed_path, staged_feed)
        os.chmod(copied_entrypoint, 0o700)
        os.chmod(staged_feed, 0o600)
        entrypoint_text = copied_entrypoint.read_text(encoding="utf-8")
        evidence_gate_wired = (
            "validate_project_news_evidence" in entrypoint_text
            and 'validate_project_news_evidence "$PROJECT_DIR"' in entrypoint_text
        )
        evidence_blocker = (
            "The daily entrypoint has a project evidence gate, but no project-bound script/source evidence bundle is staged or validated."
            if evidence_gate_wired
            else "The daily entrypoint has no detected project news-evidence gate; a frozen feed alone cannot establish claim/source evidence."
        )
        report = {
            "schema_version": 1,
            "status": "blocked_before_execution",
            "mode": "stage_and_preflight_only",
            "staging_directory": str(destination),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "harness_sha256": _sha256(Path(__file__).resolve()),
            "staged_files": {
                "scripts/run_daily_news_pipeline.sh": _sha256(copied_entrypoint),
                "data/newsnow_feed.json": _sha256(staged_feed),
            },
            "frozen_feed": feed_info,
            "cost_usd": 0,
            "publication_enabled": False,
            "external_network_used": False,
            "gates": [
                {"name": "frozen_feed_shape_and_freshness", "status": "passed"},
                {"name": "isolated_fresh_stage_and_hashes", "status": "passed"},
                {"name": "director_transport_is_deterministic_and_injected", "status": "blocked"},
                {"name": "project_news_evidence_gate", "status": "present_not_evaluated" if evidence_gate_wired else "blocked"},
                {"name": "real_render_audio_subtitle_and_quality_gates", "status": "not_run"},
                {"name": "failure_recovery_and_resume_idempotency", "status": "not_run"},
                {"name": "three_scheduled_equivalent_runs", "status": "not_run"},
            ],
            "blockers": [
                "The daily entrypoint has no deterministic director/provider transport seam. Its Codex director call can contact a live provider; this harness will not run it.",
                evidence_blocker,
                "The staged snapshot intentionally contains only the entrypoint and frozen feed, not its runtime dependencies, provider credentials, caches, node_modules, or .env; it is not runnable as a pipeline.",
                "An external container/network policy is required to guarantee outbound traffic is blocked; this preflight makes no network calls but does not configure a firewall.",
            ],
            "historical_render_sample": "projects/render-freeze-rehearsal is technical historical evidence only; not copied or represented as current factual content",
            "resume": "No runtime state was created. Use a new, empty stage directory for a later attempt; existing stage paths are refused.",
        }
        report_path = destination / "rehearsal-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(report_path, 0o600)
        return report
    except Exception:
        # Preserve the partial stage for inspection; never recursively delete unknown state.
        raise

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", required=True, help="fresh destination outside the source checkout")
    parser.add_argument("--feed", type=Path, help="user-supplied frozen NewsNow JSON array (stage-only mode)")
    parser.add_argument("--manifest", type=Path, help="strict local fixture bundle manifest (execute mode)")
    parser.add_argument("--execute", action="store_true", help="run offline public selector/reviewer replay; never runs the shell")
    parser.add_argument("--max-source-age-hours", required=True, type=float,
                        help="explicit freshness limit; there is no default")
    args = parser.parse_args(argv)
    try:
        if args.execute:
            if args.manifest is None or args.feed is not None:
                parser.error("--execute requires --manifest and does not accept --feed")
            from lib.daily_news_replay import execute_replay
            report = execute_replay(args.manifest, args.stage_dir, args.max_source_age_hours)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "component_replay_passed" else 2
        if args.manifest is not None or args.feed is None:
            parser.error("stage-only mode requires --feed and does not accept --manifest")
        report = stage_rehearsal(args.stage_dir, args.feed, args.max_source_age_hours)
    except Exception as exc:
        print(json.dumps({"status": "preflight_failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
