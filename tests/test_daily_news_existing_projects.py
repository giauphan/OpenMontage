from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _copy_runtime_sources(stage: Path) -> None:
    for name in ("scripts", "lib", "tools", "schemas"):
        shutil.copytree(
            REPO / name,
            stage / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
        )
    (stage / "config").mkdir()


def _project(stage: Path, project_id: str) -> None:
    project = stage / "projects" / project_id
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "research_brief.json").write_text(json.dumps({"topic": project_id}), encoding="utf-8")
    (artifacts / "news_evidence.json").write_text(json.dumps({"version": "2.0"}), encoding="utf-8")


def test_existing_project_ids_skip_news_fetch_and_producer(tmp_path: Path):
    stage = tmp_path / "stage"
    stage.mkdir()
    _copy_runtime_sources(stage)
    _project(stage, "cand_existing_01")

    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for tool in ("ffmpeg", "ffprobe", "hyperframes"):
        tool_path = bin_dir / tool
        tool_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool_path.chmod(0o755)

    python_shim = bin_dir / "python3"
    real_python = sys.executable
    python_shim.write_text(
        f"""#!/bin/sh
echo \"$@\" >> {tmp_path / 'python-calls.log'}
case \"$1\" in
  -c) exit 0 ;;
  *validate_news_evidence.py) exit 0 ;;
  *validate_newsnow_director_artifacts.py) exit 1 ;;
  *news_failure_quarantine.py) mkdir -p {stage}/projects/_failed_generation_recovered; exit 0 ;;
  *) exec {real_python} \"$@\" ;;
esac
""",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)

    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.defpath}",
        "PYTHONPATH": str(stage),
        "OPENMONTAGE_PYTHON": str(python_shim),
        "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        "PUBLISH_TZ": "UTC",
        "LANG": "C.UTF-8",
    }
    result = subprocess.run(
        ["bash", str(stage / "scripts" / "run_daily_news_pipeline.sh"), "--project-ids", "cand_existing_01"],
        cwd=stage,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    calls = (tmp_path / "python-calls.log").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 1
    assert any("validate_newsnow_director_artifacts.py" in call for call in calls)
    assert any("news_failure_quarantine.py" in call for call in calls)
    assert not any("news_pipeline_cli.py" in call for call in calls)
    assert "PROJECT_ID=cand_existing_01" in result.stdout


def test_existing_project_ids_reject_missing_research_brief(tmp_path: Path):
    stage = tmp_path / "stage"
    stage.mkdir()
    _copy_runtime_sources(stage)

    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for tool in ("ffmpeg", "ffprobe", "hyperframes"):
        tool_path = bin_dir / tool
        tool_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool_path.chmod(0o755)
    python_shim = bin_dir / "python3"
    python_shim.write_text("#!/bin/sh\ncase \"$1\" in -c) exit 0 ;; *) exec /usr/bin/python3 \"$@\" ;; esac\n", encoding="utf-8")
    python_shim.chmod(0o755)

    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.defpath}",
        "PYTHONPATH": str(stage),
        "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        "PUBLISH_TZ": "UTC",
    }
    result = subprocess.run(
        ["bash", str(stage / "scripts" / "run_daily_news_pipeline.sh"), "--project-ids", "missing_project"],
        cwd=stage,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "existing project path is invalid or unsafe: missing_project" in result.stderr


def test_existing_project_ids_reject_symlink_project(tmp_path: Path):
    stage = tmp_path / "stage"
    stage.mkdir()
    _copy_runtime_sources(stage)
    outside = tmp_path / "outside-project"
    outside.mkdir()
    (stage / "projects").mkdir()
    (stage / "projects" / "cand_symlink").symlink_to(outside, target_is_directory=True)

    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for tool in ("ffmpeg", "ffprobe", "hyperframes"):
        tool_path = bin_dir / tool
        tool_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool_path.chmod(0o755)
    python_shim = bin_dir / "python3"
    python_shim.write_text("#!/bin/sh\ncase \"$1\" in -c) exit 0 ;; *) exec /usr/bin/python3 \"$@\" ;; esac\n", encoding="utf-8")
    python_shim.chmod(0o755)

    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.defpath}",
        "PYTHONPATH": str(stage),
        "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        "PUBLISH_TZ": "UTC",
    }
    result = subprocess.run(
        ["bash", str(stage / "scripts" / "run_daily_news_pipeline.sh"), "--project-ids", "cand_symlink"],
        cwd=stage,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "existing project path is invalid or unsafe: cand_symlink" in result.stderr
