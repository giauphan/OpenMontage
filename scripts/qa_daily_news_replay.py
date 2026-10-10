#!/usr/bin/env python3
"""Run a test-only offline QA replay over one supplied historical project video.

This runner copies only allowlisted project inputs and invokes the existing
public selector/reviewer replay twice: once with a schema-valid fixture reply,
then with a deliberately malformed reviewer fixture. It never renders,
generates news, publishes, or treats fixture content as factual.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

MAX_SINGLE_FILE_BYTES = 2_000_000_000


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(root: Path, raw: str, label: str) -> tuple[Path, Path]:
    relative = Path(raw)
    if (not raw.strip() or relative.is_absolute() or PureWindowsPath(raw).is_absolute()
            or PureWindowsPath(raw).drive or any(part == ".." for part in relative.parts)):
        raise ValueError(f"{label} must be a project-relative path without parent traversal")
    candidate = root / relative
    if _has_symlink_component(candidate):
        raise ValueError(f"{label} must not traverse symlinks")
    resolved = candidate.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError(f"{label} must name a regular file inside --project")
    return resolved, relative


def _copy_allowlisted(source: Path, target: Path, label: str, total_bytes: list[int]) -> str:
    if source.stat().st_size > MAX_SINGLE_FILE_BYTES:
        raise ValueError(f"{label} exceeds the 2 GB per-file limit")
    total_bytes[0] += source.stat().st_size
    if total_bytes[0] > MAX_SINGLE_FILE_BYTES:
        raise ValueError("allowlisted fixture files exceed the 2 GB aggregate limit")
    expected_size = source.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if target.stat().st_size != expected_size:
        raise ValueError(f"{label} changed while staging")
    return _hash_file(target)


def _feed_fixture() -> list[dict[str, str]]:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        {
            "id": f"synthetic-qa-topic-{index}",
            "title": f"SYNTHETIC QA FIXTURE topic {index}",
            "url": f"https://example.invalid/offline-qa/{index}",
            "published_at": timestamp,
            "summary": "Synthetic replay fixture only; contains no news claim.",
        }
        for index in range(1, 4)
    ]


def _valid_selector_reply() -> dict[str, Any]:
    return {
        "selected_candidate_id": "synthetic-qa-topic-1",
        "research_status": "synthetic_fixture",
        "research_draft": {
            "title": "SYNTHETIC TEST ONLY — no factual research",
            "hook": "Fixture parser exercise only.",
            "key_points": [],
            "target_duration_secs": 15,
        },
    }


def _valid_review_reply() -> dict[str, Any]:
    checks = {
        name: {
            "passed": True,
            "score": 4,
            "notes": "Synthetic fixture transport response; not a human/media judgment.",
        }
        for name in ("visual_quality", "audio_sync", "content_appropriateness", "brand_compliance")
    }
    return {**checks, "overall_passed": True, "summary": "Synthetic QA fixture only."}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_case(
    case_root: Path,
    *,
    project_root: Path,
    video_source: Path,
    video_relative: Path,
    reviewer_reply: dict[str, Any],
) -> tuple[Path, list[str]]:
    bundle = case_root / "fixture-bundle"
    fixture_project = bundle / "project"
    fixture_project.mkdir(parents=True)
    file_hashes: dict[str, str] = {}
    total_bytes = [0]

    source_files: list[tuple[Path, Path, str]] = []
    script_source, script_relative = _relative_file(project_root, "artifacts/script_vi.json", "script")
    source_files.append((script_source, script_relative, "script"))

    main_html, _ = _relative_file(project_root, "hyperframes/index.html", "main HTML composition")
    source_files.append((main_html, Path("hyperframes/index.html"), "main HTML composition"))
    if "reels" in video_source.name.casefold():
        reels_html, _ = _relative_file(project_root, "hyperframes_reels/index.html", "Reels HTML composition")
        source_files.append((reels_html, Path("hyperframes_reels/index.html"), "Reels HTML composition"))

    source_files.append((video_source, Path("renders") / video_relative.name, "selected historical video"))

    for source, relative, label in source_files:
        file_hashes[relative.as_posix()] = _copy_allowlisted(
            source, fixture_project / relative, label, total_bytes
        )

    _write_json(fixture_project / "metadata.json", {
        "fixture_only": True,
        "title": "SYNTHETIC QA ONLY — NOT FOR PUBLICATION",
        "description": "Synthetic metadata used only to exercise the offline review parser.",
        "tags": ["SYNTHETIC TEST ONLY"],
    })

    marker = fixture_project / "OFFLINE_REHEARSAL_TEST_ONLY.json"
    _write_json(marker, {
        "test_only": True,
        "artifact_kind": "historical_media_offline_qa_fixture",
        "factual_content_verified": False,
        "included_source_sha256": file_hashes,
    })
    os.chmod(marker, 0o444)
    copied_scope = sorted({relative.as_posix() for _, relative, _ in source_files} | {"metadata.json", marker.name})

    _write_json(bundle / "feed.json", _feed_fixture())
    _write_json(bundle / "selector-reply.json", _valid_selector_reply())
    _write_json(bundle / "reviewer-reply.json", reviewer_reply)
    project_video_path = Path("renders") / video_relative.name
    _write_json(bundle / "manifest.json", {
        "schema_version": 1,
        "fixture_bundle": True,
        "feed": "feed.json",
        "selection_reply": "selector-reply.json",
        "review_reply": "reviewer-reply.json",
        "projects": [{
            "id": "historical-technical-sample",
            "bundle": "project",
            "video": project_video_path.as_posix(),
            "metadata": "metadata.json",
        }],
    })
    return bundle / "manifest.json", copied_scope


def _execute_case(manifest: Path, stage_dir: Path, max_age: float) -> dict[str, Any]:
    from lib.daily_news_replay import execute_replay

    try:
        return execute_replay(manifest, str(stage_dir), max_age)
    except Exception as exc:
        report_path = stage_dir / "rehearsal-report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["runner_exception"] = f"{type(exc).__name__}: {exc}"
            return report
        return {
            "status": "component_replay_failed",
            "test_only": True,
            "error": f"{type(exc).__name__}: {exc}",
            "stage_report_written": False,
        }


def run_qa(project: str, video_relative: str, output_root: str) -> tuple[int, dict[str, Any]]:
    from scripts.rehearse_daily_news_offline import _safe_stage_path

    project_argument = Path(project).expanduser()
    if project_argument.is_symlink() or _has_symlink_component(project_argument.absolute()):
        raise ValueError("--project must not traverse symlinks")
    project_root = project_argument.resolve(strict=True)
    if not project_root.is_dir():
        raise ValueError("--project must be an existing directory")

    video_source, video_rel = _relative_file(project_root, video_relative, "--video-relative")
    if video_source.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        raise ValueError("--video-relative must name a supported local video file")


    output_argument = Path(output_root).expanduser().absolute()
    if _has_symlink_component(output_argument):
        raise ValueError("--output-root must not traverse symlinks")
    output_path = _safe_stage_path(str(output_argument))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(mode=0o700)
    _write_json(output_path / "QA_REPLAY_TEST_ONLY.json", {
        "test_only": True,
        "factual_content_verified": False,
        "purpose": "synthetic feed/reviewer parser exercise over explicitly supplied historical media",
    })

    cases_root = output_path / "cases"
    cases_root.mkdir()
    valid_case = cases_root / "valid-review-fixture"
    valid_manifest, valid_copy_scope = _prepare_case(
        valid_case,
        project_root=project_root,
        video_source=video_source,
        video_relative=video_rel,
        reviewer_reply=_valid_review_reply(),
    )
    max_age_hours = 24.0
    first_stage = output_path / "replay-valid-review-fixture"
    first_report = _execute_case(valid_manifest, first_stage, max_age_hours)
    first_report_path = first_stage / "rehearsal-report.json"
    first_report_hash = hashlib.sha256(first_report_path.read_bytes()).hexdigest() if first_report_path.is_file() else None

    malformed_reply = {
        "visual_quality": {
            "passed": True,
            "score": 4,
            "notes": "Synthetic malformed response; required reviewer sections are deliberately absent.",
        }
    }
    malformed_case = cases_root / "malformed-review-fixture"
    malformed_manifest, _ = _prepare_case(
        malformed_case,
        project_root=project_root,
        video_source=video_source,
        video_relative=video_rel,
        reviewer_reply=malformed_reply,
    )
    second_stage = output_path / "replay-malformed-review-fixture"
    second_report = _execute_case(malformed_manifest, second_stage, max_age_hours)
    second_report_path = second_stage / "rehearsal-report.json"

    first_preserved = bool(
        first_report_hash
        and first_report_path.is_file()
        and hashlib.sha256(first_report_path.read_bytes()).hexdigest() == first_report_hash
    )
    malformed_review = next((
        stage for stage in second_report.get("stage_outcomes", [])
        if stage.get("stage") == "public_strict_review:historical-technical-sample"
    ), None)
    expected_failure = bool(malformed_review and malformed_review.get("status") == "failed")
    summary = {
        "status": "qa_passed" if first_report.get("status") == "component_replay_passed" and expected_failure and first_preserved else "qa_failed",
        "test_only": True,
        "factual_content_verified": False,
        "publication_enabled": False,
        "rendering_or_news_generation_performed": False,
        "project": str(project_root),
        "video_relative": video_rel.as_posix(),
        "output_root": str(output_path),
        "valid_fixture_case": {
            "status": first_report.get("status"),
            "report": str(first_report_path),
            "report_sha256_after_second_case": first_report_hash,
            "preserved_after_second_case": first_preserved,
        },
        "malformed_reviewer_case": {
            "status": second_report.get("status"),
            "report": str(second_report_path),
            "review_stage_status": malformed_review.get("status") if malformed_review else "missing",
            "failure_report_written": second_report_path.is_file(),
        },
        "allowlisted_copy_scope": valid_copy_scope,
    }
    summary_path = output_path / "qa-summary.json"
    _write_json(summary_path, summary)
    return (0 if summary["status"] == "qa_passed" else 2), summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="existing historical technical sample project directory")
    parser.add_argument("--video-relative", required=True, help="explicit video file path relative to --project")
    parser.add_argument("--output-root", required=True, help="fresh destination outside this source checkout")

    args = parser.parse_args(argv)
    try:
        code, summary = run_qa(args.project, args.video_relative, args.output_root)
    except Exception as exc:
        print(json.dumps({"status": "qa_preflight_failed", "test_only": True,
                          "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
