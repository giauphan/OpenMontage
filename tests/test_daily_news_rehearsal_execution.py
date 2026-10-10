from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT_MARKER = {"test_only": True, "purpose": "daily-news-rehearsal"}


def _copy_runtime_sources(stage: Path) -> None:
    """Copy only application source packages; never copy live checkout state."""
    for name in ("scripts", "lib", "tools", "schemas"):
        shutil.copytree(
            REPO / name,
            stage / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
        )
    (stage / "config").mkdir()


def _frozen_project(bundle_root: Path, index: int) -> dict[str, str]:
    project_id = f"fixture-news-{index:02d}"
    project = bundle_root / project_id
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True)
    (project / "hyperframes").mkdir()
    (project / "hyperframes_reels").mkdir()
    (project / "assets").mkdir()

    # These are valid director inputs, allowing the real director-artifact
    # validator to pass. The deliberately invalid evidence is rejected by the
    # real evidence validator before any audio or composition stage is reached.
    (artifacts / "research_brief.json").write_text(
        json.dumps({"topic": f"Tin tức công nghệ fixture {index}"}), encoding="utf-8"
    )
    script = {
        "version": "1.0",
        "title": f"Tin tức công nghệ fixture {index}",
        "total_duration_seconds": 10,
        "sections": [{
            "id": "fixture-section-1",
            "text": "Nội dung mới đây",
            "start_seconds": 0,
            "end_seconds": 10,
        }],
    }
    (artifacts / "script_vi.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    (artifacts / "proposal_packet.json").write_text("{}", encoding="utf-8")
    (artifacts / "selector_reply.json").write_text(json.dumps({
        "selected_candidate_id": f"fixture-candidate-{index:02d}",
        "research_draft": {"title": f"Synthetic news topic {index:02d}"},
    }), encoding="utf-8")
    (artifacts / "director_reply.json").write_text(
        json.dumps({"is_error": False, "result": "fixture-only; no director call"}), encoding="utf-8"
    )
    (artifacts / "reviewer_reply.json").write_text(json.dumps({
        "visual_quality": {"passed": True, "score": 4, "notes": "fixture only"},
        "audio_sync": {"passed": True, "score": 4, "notes": "fixture only"},
        "content_appropriateness": {"passed": True, "score": 4, "notes": "fixture only"},
        "brand_compliance": {"passed": True, "score": 4, "notes": "fixture only"},
        "overall_passed": True,
        "summary": "Synthetic; this reply must not be reached in this test",
    }), encoding="utf-8")
    (artifacts / "news_evidence.json").write_text(json.dumps({
        "version": "2.0",
        # Keep the byte binding valid so this exercises the full evidence
                # gate's rejection of unsupported claims, not the earlier binding guard.
                "script_sha256": hashlib.sha256((artifacts / "script_vi.json").read_bytes()).hexdigest(),
        "claims": [],
        "sources": [],
        "contradictions": [],
    }), encoding="utf-8")
    (project / "assets" / "narration.mp3").write_bytes(b"fixture bytes; never decoded")
    (project / "assets" / "music-bg.mp3").write_bytes(b"fixture bytes; never decoded")
    for composition in ("hyperframes", "hyperframes_reels"):
        (project / composition / "index.html").write_text(
            "<!doctype html><html><body><main>Fixture composition only</main></body></html>\n",
            encoding="utf-8",
        )
    return {"project_id": project_id, "project_dir": f"bundles/{project_id}"}


def _write_frozen_manifest(stage: Path) -> Path:
    manifest_dir = stage / "rehearsal"
    bundle_root = manifest_dir / "bundles"
    bundle_root.mkdir(parents=True)
    manifest = manifest_dir / "manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "bundles": [_frozen_project(bundle_root, index) for index in range(1, 4)],
    }), encoding="utf-8")
    return manifest


def _install_tripwires(home: Path, log_dir: Path) -> Path:
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    calls_log = log_dir / "python-calls.log"
    tripwire_log = log_dir / "forbidden-command-calls.log"
    python_shim = bindir / "python-rehearsal-guard"
    python_shim.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {str(calls_log)!r}\n"
        "case \"$*\" in\n"
        "  *news_pipeline_cli.py*|*codex_agent_validation.py*|*schedule_today_native.py*|"
        "*schedule_youtube_today.py*|*publish_active_projects.py*|*publish_manual_video.py*)\n"
        f"    printf '%s\\n' \"python:$*\" >> {str(tripwire_log)!r}; exit 97;;\n"
        "esac\n"
        f"exec {sys.executable!r} \"$@\"\n",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)
    for name in ("ffprobe", "ffmpeg", "hyperframes", "codex", "edge-tts"):
        executable = bindir / name
        executable.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"{name}:$*\" >> {str(tripwire_log)!r}\n"
            "exit 98\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    return python_shim


def test_copy_failure_keeps_release_marker_and_copied_artifacts_in_staging(tmp_path: Path, monkeypatch, capsys):
    from scripts import prepare_daily_news_rehearsal as preparer
    from lib.daily_news_replay import _copy_project_bundle as real_copy

    stage = tmp_path / "copy-failure-stage"
    stage.mkdir()
    (stage / ".openmontage-rehearsal-root.json").write_text(json.dumps(ROOT_MARKER), encoding="utf-8")
    manifest = _write_frozen_manifest(stage)
    copy_destinations: list[Path] = []

    def injected_copy(source: Path, destination: Path | None, *, allow_existing_destination: bool = False):
        if destination is None:
            return real_copy(source, destination)
        assert allow_existing_destination is True
        marker = destination / "OFFLINE_REHEARSAL_TEST_ONLY.json"
        assert marker.is_file()
        assert json.loads(marker.read_text(encoding="utf-8")) == ROOT_MARKER
        real_copy(source, destination, allow_existing_destination=True)
        (destination / "injected-copy-interruption.bin").write_bytes(b"retain partial output")
        copy_destinations.append(destination)
        raise OSError("injected copy interruption after fixture bytes were written")

    monkeypatch.setattr(preparer, "_copy_project_bundle", injected_copy)
    result = preparer.main([
        "--manifest", str(manifest),
        "--root", str(stage),
        "--max-source-age-hours", "24",
    ])

    output = capsys.readouterr().err
    assert result == 2
    assert "injected copy interruption" in output
    assert len(copy_destinations) == 1
    partial = copy_destinations[0]
    assert partial.parent == stage / "projects"
    assert partial.name.startswith(".rehearsal-staging-fixture-news-01-")
    assert json.loads((partial / "OFFLINE_REHEARSAL_TEST_ONLY.json").read_text(encoding="utf-8")) == ROOT_MARKER
    assert (partial / "artifacts" / "research_brief.json").is_file()
    assert (partial / "injected-copy-interruption.bin").read_bytes() == b"retain partial output"
    assert not (stage / "projects" / "fixture-news-01").exists()
    assert not (stage / "config" / "publish_schedule.json").exists()


def test_actual_daily_entrypoint_validates_and_quarantines_invalid_frozen_evidence(tmp_path: Path):
    stage = tmp_path / "isolated-daily-stage"
    stage.mkdir()
    _copy_runtime_sources(stage)
    (stage / ".openmontage-rehearsal-root.json").write_text(json.dumps(ROOT_MARKER), encoding="utf-8")
    manifest = _write_frozen_manifest(stage)
    observation_dir = tmp_path / "observations"
    observation_dir.mkdir()
    python_shim = _install_tripwires(tmp_path / "isolated-home", observation_dir)

    # Deliberately minimal environment: no inherited provider credentials,
    # production flags, .env, git directory, live schedule, or network config.
    env = {
        "HOME": str(tmp_path / "isolated-home"),
        "PATH": f"{tmp_path / 'isolated-home' / '.local' / 'bin'}:{os.defpath}",
        "PYTHONPATH": str(stage),
        "OPENMONTAGE_PYTHON": str(python_shim),
        "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        "PUBLISH_TZ": "UTC",
        "LANG": "C.UTF-8",
    }
    result = subprocess.run(
        ["bash", str(stage / "scripts" / "run_daily_news_pipeline.sh"),
         "--rehearsal-bundle", str(manifest)],
        cwd=stage,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "news evidence validation failed" in result.stderr
    assert not (stage / ".env").exists()
    assert not (stage / "data" / "newsnow_feed.json").exists()
    assert (stage / "config" / "publish_schedule.json").is_file()
    assert json.loads((stage / "config" / "publish_schedule.json").read_text(encoding="utf-8"))["active_projects"] == []

    report = json.loads((stage / "logs" / "daily_news_rehearsal_report.json").read_text(encoding="utf-8"))
    assert report["test_only"] is True
    assert report["shell_executed"] is True
    assert report["publication_enabled"] is False
    assert report["n5_complete"] is False
    assert report["egress_status"].startswith("not_asserted")
    assert report["requested_project_ids"] == ["fixture-news-01", "fixture-news-02", "fixture-news-03"]
    assert report["successful_project_ids"] == []
    assert report["failed_project_ids"] == report["requested_project_ids"]
    assert set(report["quarantined_project_ids"]) == set(report["requested_project_ids"])
    assert report["terminal_exit_status"] == result.returncode == 1
    assert report["terminal_stage"] == "incomplete_rehearsal"
    assert all(paths for paths in report["stage_evidence_paths"].values())
    assert report["freshness_policy"] == {
        "name": "NEWS_MAX_SOURCE_AGE_HOURS",
        "max_age_hours": "24",
        "explicitly_configured": True,
    }

    python_calls = (observation_dir / "python-calls.log").read_text(encoding="utf-8").splitlines()
    assert sum("validate_newsnow_director_artifacts.py" in call for call in python_calls) == 3
    assert sum("validate_news_evidence.py" in call for call in python_calls) == 3
    assert sum("news_failure_quarantine.py" in call for call in python_calls) == 3
    assert not any("news_pipeline_cli.py" in call for call in python_calls)
    assert not any("codex_agent_validation.py" in call for call in python_calls)

    director_results = list((stage / "logs").glob("directors_*_result.json"))
    assert len(director_results) == 3
    assert all("fixture-only; no director call" in path.read_text(encoding="utf-8") for path in director_results)

    recovery_root = stage / "projects" / "_failed_generation_recovered"
    recoveries = list(recovery_root.iterdir())
    assert len(recoveries) == 3
    assert {path.name.split("_", 1)[0] for path in recoveries} == {
        "fixture-news-01", "fixture-news-02", "fixture-news-03"
    }
    for recovery in recoveries:
        reason = (recovery / "failure_reason.txt").read_text(encoding="utf-8").strip()
        assert reason.startswith("news evidence missing or invalid; see ")
        validation_log = Path(reason.split("see ", 1)[1])
        assert validation_log.is_file()
        validation_output = validation_log.read_text(encoding="utf-8")
        assert '"ok": false' in validation_output
        assert "script binding mismatch" in validation_output or "claims must be a non-empty array" in validation_output
        quarantined_project = recovery / "project"
        assert (quarantined_project / "artifacts" / "script_vi.json").is_file()
        assert (quarantined_project / "artifacts" / "news_evidence.json").is_file()
        assert (quarantined_project / "OFFLINE_REHEARSAL_TEST_ONLY.json").is_file()

    tripwire_log = observation_dir / "forbidden-command-calls.log"
    assert not tripwire_log.exists(), tripwire_log.read_text(encoding="utf-8") if tripwire_log.exists() else ""
    assert not list((stage / "logs").glob("directors_*_result.json")) or all(
        "fixture-only; no director call" in path.read_text(encoding="utf-8")
        for path in (stage / "logs").glob("directors_*_result.json")
    )
    assert not (stage / "projects" / "fixture-news-01").exists()
    assert not (stage / "projects" / "fixture-news-02").exists()
    assert not (stage / "projects" / "fixture-news-03").exists()
