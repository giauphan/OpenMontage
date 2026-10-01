import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_stage3_failure_quarantines_unscheduled_generated_folders(tmp_path: Path):
    """Failed-generation project dirs must be moved to a recovery root (never rm -rf)."""
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for d in (scripts_dir, config_dir, projects_dir, bin_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Copy actual strict orchestrator under test
    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")

    # Schedule with one active project
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({"active_projects": [{"project_id": "cand_keep", "publish_date": "2099-01-01", "publish_time": "09:15"}]}),
        encoding="utf-8",
    )

    # Mock Codex CLI in PATH
    for name in ("codex", "ffmpeg", "ffprobe"):
        mock_bin = bin_dir / name
        mock_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        mock_bin.chmod(0o755)

    # Mock daily pipeline: emits 3 project IDs (2 unscheduled, 1 scheduled), creates folders, then fails
    mock_pipeline = scripts_dir / "run_daily_news_pipeline.sh"
    mock_pipeline.write_text(
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/projects/cand_failed_one" "$ROOT/projects/cand_failed_two" "$ROOT/projects/cand_keep"
echo "PROJECT_ID=cand_failed_one"
echo "PROJECT_ID=cand_failed_two"
echo "PROJECT_ID=cand_keep"
exit 5
""",
        encoding="utf-8",
    )
    mock_pipeline.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PUBLISH_TZ": "Asia/Ho_Chi_Minh",
        "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
        # Hermetic: point tmp cleanup at the fixture tmp dir, disable disk thresholds.
        "TMP_ROOT": str(tmp_path / "tmp_root"),
        "MIN_DISK_MB": "0",
        "MIN_TMP_DISK_MB": "0",
    }
    (tmp_path / "tmp_root").mkdir(exist_ok=True)

    result = subprocess.run(
        ["bash", str(scripts_dir / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    # Unscheduled partial candidate directories must be quarantined, not deleted.
    quarantine = projects_dir / "_failed_generation_recovered"
    assert not (projects_dir / "cand_failed_one").exists()
    assert not (projects_dir / "cand_failed_two").exists()
    assert (quarantine / "cand_failed_one").is_dir()
    assert (quarantine / "cand_failed_two").is_dir()
    # Scheduled candidate directory must be preserved in place.
    assert (projects_dir / "cand_keep").is_dir()


def test_disk_threshold_blocks_preflight_when_space_insufficient(tmp_path: Path):
    """Preflight must fail closed when disk falls under the configured minimum."""
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for d in (scripts_dir, config_dir, projects_dir, bin_dir):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({"active_projects": []}),
        encoding="utf-8",
    )
    for name in ("codex", "ffmpeg", "ffprobe"):
        mock_bin = bin_dir / name
        mock_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        mock_bin.chmod(0o755)

    (scripts_dir / "run_daily_news_pipeline.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    (scripts_dir / "run_daily_news_pipeline.sh").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PUBLISH_TZ": "Asia/Ho_Chi_Minh",
        "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
        "TMP_ROOT": str(tmp_path / "tmp_root"),
        # Set minimums absurdly high so the real (ample) disk reports below them.
        "MIN_DISK_MB": "99999999",
        "MIN_TMP_DISK_MB": "99999999",
    }
    (tmp_path / "tmp_root").mkdir(exist_ok=True)

    result = subprocess.run(
        ["bash", str(scripts_dir / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "insufficient disk space" in combined
    # A failed preflight must write the heartbeat as failed, not completed.
    hb = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert hb.is_file()
    assert json.loads(hb.read_text(encoding="utf-8"))["status"] == "failed"
