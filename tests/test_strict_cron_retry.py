import fcntl
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def create_fixture(tmp_path: Path, validation_script: str) -> tuple[Path, Path, Path]:
    scripts = tmp_path / "scripts"
    config = tmp_path / "config"
    projects = tmp_path / "projects"
    binaries = tmp_path / "bin"
    for directory in (scripts, config, projects, binaries):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts / "run_strict_docker_publish.sh")
    for relative in ("lib/news_evidence.py", "lib/news_release_gate.py", "tests/fixtures/news_evidence.py"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    (config / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": ["01:00", "02:00", "03:00"]},
            "active_projects": [],
        }),
        encoding="utf-8",
    )

    for name in ("codex", "ffmpeg", "ffprobe"):
        write_executable(binaries / name, "#!/usr/bin/env bash\nexit 0\n")

    write_executable(
        scripts / "run_daily_news_pipeline.sh",
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COUNT_FILE="$ROOT/generation-count"
count=0
[ ! -f "$COUNT_FILE" ] || count=$(cat "$COUNT_FILE")
count=$((count + 1))
printf '%s' "$count" > "$COUNT_FILE"
if [ "$count" -eq 1 ]; then
  exit 5
fi
for pid in cand_fail cand_pass; do
  mkdir -p "$ROOT/projects/$pid/renders"
  printf '{"id":"%s","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}' "$pid" > "$ROOT/projects/$pid/publish_metadata.json"
  printf video > "$ROOT/projects/$pid/renders/final_full_vi_9x16.mp4"
  printf video > "$ROOT/projects/$pid/renders/final_reels_vi_9x16.mp4"
  PYTHONPATH="$ROOT/tests/fixtures:$ROOT" python3 -c 'import sys; from pathlib import Path; from news_evidence import write_reviewed_news_evidence; write_reviewed_news_evidence(Path(sys.argv[1]))' "$ROOT/projects/$pid"
  echo "PROJECT_ID=$pid"
done
""",
    )
    (scripts / "validate_render_quality.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "validate_publish_metadata.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "codex_agent_validation.py").write_text(validation_script, encoding="utf-8")
    (scripts / "schedule_today_native.py").write_text(
        "import sys\nfrom pathlib import Path\nPath('native-schedule-call').write_text(' '.join(sys.argv), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (scripts / "publish_active_projects.py").write_text(
        """import argparse
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--slot', required=True)
parser.add_argument('--date', required=True)
parser.add_argument('--only-platform')
args = parser.parse_args()
schedule = json.loads((root / 'config' / 'publish_schedule.json').read_text(encoding='utf-8'))
matching = [
    entry for entry in schedule.get('active_projects', [])
    if entry.get('publish_date') == args.date and entry.get('publish_time') == args.slot
]
if not matching:
    raise SystemExit(2)
project = root / 'projects' / matching[0]['project_id']
if not (project / 'publish_metadata.json').is_file():
    raise SystemExit(3)
if not (project / 'renders' / 'final_reels_vi_9x16.mp4').is_file():
    raise SystemExit(4)
(root / 'slot-publisher-call').write_text(f'{args.date} {args.slot} {matching[0]["project_id"]}', encoding='utf-8')
""",
        encoding="utf-8",
    )
    (scripts / "pipeline_monitoring.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    write_executable(scripts / "clear_stale_projects.sh", "#!/usr/bin/env bash\nexit 0\n")

    return scripts, config, binaries


def occupy_today_slots(config: Path) -> list[dict[str, str]]:
    today = datetime.now(timezone.utc).strftime("%F")
    occupied = [
        {"project_id": f"already_queued_{slot.replace(':', '')}", "publish_date": today, "publish_time": slot}
        for slot in ("01:00", "02:00", "03:00")
    ]
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["active_projects"] = occupied
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")
    return occupied


def run_pipeline(tmp_path: Path, scripts: Path, binaries: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "PUBLISH_TZ": "UTC",
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
            "DAILY_GENERATION_RETRIES": "2",
            "CLAUDE_VALIDATION_RETRIES": "3",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        },
        capture_output=True,
        text=True,
    )


def test_retries_generation_and_validation_before_next_day_queue(tmp_path: Path):
    scripts, config, binaries = create_fixture(
        tmp_path,
        """import sys
from pathlib import Path
project = Path(sys.argv[1]).name
counter = Path(f'{project}-validation-count')
count = int(counter.read_text()) if counter.exists() else 0
count += 1
counter.write_text(str(count))
if project == 'cand_fail' or count < 3:
    raise SystemExit(1)
""",
    )

    occupied_today = occupy_today_slots(config)
    result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "generation-count").read_text(encoding="utf-8") == "2"
    assert (tmp_path / "cand_fail-validation-count").read_text(encoding="utf-8") == "3"
    assert (tmp_path / "cand_pass-validation-count").read_text(encoding="utf-8") == "3"

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule = json.loads((config / "publish_schedule.json").read_text(encoding="utf-8"))
    assert schedule["active_projects"] == occupied_today + [{
        "project_id": "cand_pass",
        "publish_date": tomorrow,
        "publish_time": "01:00",
    }]
    assert tomorrow in (tmp_path / "native-schedule-call").read_text(encoding="utf-8")


def test_all_validation_failures_leave_schedule_unchanged(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(1)\n")
    original = (config / "publish_schedule.json").read_text(encoding="utf-8")

    result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode != 0
    assert "validation failed for all projects" in (result.stdout + result.stderr).lower()
    assert json.loads((config / "publish_schedule.json").read_text(encoding="utf-8")) == json.loads(original)
    assert not (tmp_path / "native-schedule-call").exists()


def test_queued_project_is_available_to_slot_publisher(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(1)\n")
    (scripts / "codex_agent_validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    occupied_today = occupy_today_slots(config)

    result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode == 0, result.stdout + result.stderr
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule = json.loads((config / "publish_schedule.json").read_text(encoding="utf-8"))
    queued = [entry for entry in schedule["active_projects"] if entry["publish_date"] == tomorrow]
    assert {entry["project_id"]: entry["publish_time"] for entry in queued} == {
        "cand_fail": "01:00",
        "cand_pass": "02:00",
    }
    assert schedule["active_projects"][:3] == occupied_today
    for entry in queued:
        project_id = entry["project_id"]
        assert (tmp_path / "projects" / project_id / "publish_metadata.json").is_file()
        assert (tmp_path / "projects" / project_id / "renders" / "final_reels_vi_9x16.mp4").is_file()

    slot_result = subprocess.run(
        [
            "python3",
            str(scripts / "publish_active_projects.py"),
            "--slot",
            "01:00",
            "--date",
            tomorrow,
            "--only-platform",
            "instagram",
        ],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "NEWS_MAX_SOURCE_AGE_HOURS": "24"},
        capture_output=True,
        text=True,
    )

    assert slot_result.returncode == 0, slot_result.stdout + slot_result.stderr
    assert (tmp_path / "slot-publisher-call").read_text(encoding="utf-8") == f"{tomorrow} 01:00 cand_fail"


def heartbeat_trap_block() -> str:
    source = (ROOT / "scripts" / "run_strict_docker_publish.sh").read_text(encoding="utf-8")
    return source.split("# STRICT_HEARTBEAT_TRAPS_BEGIN\n", 1)[1].split(
        "\n# STRICT_HEARTBEAT_TRAPS_END", 1
    )[0]


def test_unexpected_exit_writes_atomic_failed_heartbeat_and_preserves_status(tmp_path: Path):
    script = (
        'set -euo pipefail\nROOT="$TEST_ROOT"\n'
        + heartbeat_trap_block()
        + '\nwrite_heartbeat "started"\nexit 8\n'
    )
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        env={**os.environ, "TEST_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
    )

    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert result.returncode == 8
    data = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["run_id"]
    assert not list(heartbeat.parent.glob("daily_orchestrator.json.tmp.*"))


def test_successful_exit_writes_completed_heartbeat(tmp_path: Path):
    script = (
        'set -euo pipefail\nROOT="$TEST_ROOT"\n'
        + heartbeat_trap_block()
        + '\nwrite_heartbeat "started"\nwrite_heartbeat "completed"\nexit 0\n'
    )
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        env={**os.environ, "TEST_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
    )

    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert result.returncode == 0, result.stderr
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "completed"


def _signal_heartbeat_runner(tmp_path: Path, signum: int) -> subprocess.CompletedProcess[str]:
    script = (
        'set -euo pipefail\nROOT="$TEST_ROOT"\n'
        + heartbeat_trap_block()
        + '\nwrite_heartbeat "started"\nwhile :; do sleep 1; done\n'
    )
    process = subprocess.Popen(
        ["/bin/bash", "-c", script],
        env={**os.environ, "TEST_ROOT": str(tmp_path)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and process.poll() is None:
            if heartbeat.is_file() and json.loads(heartbeat.read_text(encoding="utf-8")).get("status") == "started":
                break
            time.sleep(0.01)
        assert heartbeat.is_file(), "heartbeat did not reach started state"
        assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "started"
        os.killpg(process.pid, signum)
        stdout, stderr = process.communicate(timeout=3)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)


def test_int_signal_writes_failed_heartbeat_with_130_status(tmp_path: Path):
    result = _signal_heartbeat_runner(tmp_path, signal.SIGINT)

    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert result.returncode == 130
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "failed"


def test_term_signal_writes_failed_heartbeat_with_143_status(tmp_path: Path):
    result = _signal_heartbeat_runner(tmp_path, signal.SIGTERM)

    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert result.returncode == 143
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "failed"


def test_failed_heartbeat_write_preserves_prior_valid_file(tmp_path: Path):
    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    heartbeat.parent.mkdir(parents=True)
    prior = {"ts": "2026-10-11T00:00:00Z", "run_id": "prior", "status": "completed"}
    heartbeat.write_text(json.dumps(prior), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_executable(bin_dir / "jq", "#!/bin/sh\nexit 1\n")
    script = (
        'set -euo pipefail\nROOT="$TEST_ROOT"\n'
        + heartbeat_trap_block()
        + '\nwrite_heartbeat "started"\n'
    )
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        env={**os.environ, "TEST_ROOT": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert json.loads(heartbeat.read_text(encoding="utf-8")) == prior
    assert not list(heartbeat.parent.glob("daily_orchestrator.json.tmp.*"))


def test_lock_contender_does_not_overwrite_active_heartbeat(tmp_path: Path):
    scripts, _, binaries = create_fixture(tmp_path, "raise SystemExit(1)\n")
    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    active = {"ts": "2026-10-11T00:00:00Z", "run_id": "active-run", "status": "started"}
    heartbeat.write_text(json.dumps(active), encoding="utf-8")
    lock_path = tmp_path / ".strict_docker_publish.lock"

    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode == 75
    assert json.loads(heartbeat.read_text(encoding="utf-8")) == active


def test_validation_deterministic_failure_aborts_retry_immediately(tmp_path: Path):
    """When validation fails with exit 2 (deterministic), Stage 5 must not retry 3 times."""
    scripts, config, binaries = create_fixture(
        tmp_path,
        """import sys
from pathlib import Path
project = Path(sys.argv[1]).name
counter = Path(f'{project}-validation-count')
count = int(counter.read_text()) if counter.exists() else 0
count += 1
counter.write_text(str(count))
raise SystemExit(2)
""",
    )

    occupy_today_slots(config)
    result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode != 0
    # Must have only run once per candidate, breaking out immediately on exit 2
    assert (tmp_path / "cand_fail-validation-count").read_text(encoding="utf-8") == "1"
    assert (tmp_path / "cand_pass-validation-count").read_text(encoding="utf-8") == "1"


def test_orchestrator_lock_fd_has_cloexec(tmp_path: Path):
    """File descriptor 199 (orchestrator lock) must have FD_CLOEXEC set so child processes do not inherit it."""
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")

    # Hook run_daily_news_pipeline.sh to check if fd 199 is inherited
    probe_script = """#!/usr/bin/env bash
python3 -c '
import os, sys
try:
    os.fstat(199)
    is_open = True
except OSError:
    is_open = False
with open("fd_199_inherited.txt", "w") as f:
    f.write(str(is_open))
'
exit 1
"""
    write_executable(scripts / "run_daily_news_pipeline.sh", probe_script)
    run_pipeline(tmp_path, scripts, binaries)

    fd_file = tmp_path / "fd_199_inherited.txt"
    assert fd_file.is_file()
    assert fd_file.read_text().strip() == "False"
