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
    shutil.copy2(ROOT / "scripts" / "retry_daily_pipeline.sh", scripts / "retry_daily_pipeline.sh")
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
    write_executable(binaries / "curl", "#!/usr/bin/env bash\nexit 1\n")

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


def run_pipeline(
    tmp_path: Path, scripts: Path, binaries: Path, expected_success_count: int = 3,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "PUBLISH_TZ": "UTC",
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
            "DAILY_GENERATION_RETRIES": "2",
            "GENERATION_RETRY_DELAY_SECONDS": "0",
            "CLAUDE_VALIDATION_RETRIES": "3",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
            "EXPECTED_SUCCESS_COUNT": str(expected_success_count),
            **(extra_env or {}),
        },
        capture_output=True,
        text=True,
    )


def test_no_eligible_topic_stops_generation_retries_without_queue_changes(tmp_path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    write_executable(binaries / "curl", "#!/usr/bin/env bash\nexit 1\n")
    write_executable(scripts / "run_daily_news_pipeline.sh", "#!/usr/bin/env bash\necho run >> generation-count\necho STATUS=NO_ELIGIBLE_TOPIC\nexit 0\n")
    before = (config / "publish_schedule.json").read_text()
    result = run_pipeline(tmp_path, scripts, binaries)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "generation-count").read_text().splitlines() == ["run"]
    assert (config / "publish_schedule.json").read_text() == before
    assert json.loads((tmp_path / "logs/heartbeat/daily_orchestrator.json").read_text())["status"] == "completed"


def test_muse_no_topic_marker_prevents_retry_despite_curated_backlog(tmp_path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/.no_eligible_topic_marker").write_text("no topic")
    write_executable(binaries / "python3", "#!/usr/bin/env bash\nexit 0\n")
    write_executable(scripts / "run_strict_docker_publish.sh", "#!/usr/bin/env bash\ntouch should-not-run\n")
    res = subprocess.run(["bash", str(scripts / "retry_daily_pipeline.sh")], cwd=tmp_path,
                         env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC",
                              "NEWS_DISCOVERY_PROVIDER": "muse"}, capture_output=True, text=True)
    assert res.returncode == 0
    assert not (tmp_path / "should-not-run").exists()
    assert (tmp_path / "data/.no_eligible_topic_marker").exists()


def test_muse_partial_schedule_retries_until_daily_quota_is_met(tmp_path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text())
    schedule["active_projects"] = [{"project_id": "p1", "publish_date": tomorrow, "publish_time": "01:00"}]
    schedule_path.write_text(json.dumps(schedule))
    write_executable(scripts / "run_strict_docker_publish.sh", "#!/usr/bin/env bash\ntouch should-not-run\n")
    res = subprocess.run(["bash", str(scripts / "retry_daily_pipeline.sh")], cwd=tmp_path,
                         env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC",
                              "NEWS_DISCOVERY_PROVIDER": "muse"}, capture_output=True, text=True)
    assert res.returncode == 0
    assert (tmp_path / "should-not-run").exists()


def test_partial_validation_never_queues_an_incomplete_daily_batch(tmp_path: Path):
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

    assert result.returncode != 0
    assert (tmp_path / "generation-count").read_text(encoding="utf-8") == "2"
    assert (tmp_path / "cand_fail-validation-count").read_text(encoding="utf-8") == "3"
    assert (tmp_path / "cand_pass-validation-count").read_text(encoding="utf-8") == "3"

    schedule = json.loads((config / "publish_schedule.json").read_text(encoding="utf-8"))
    assert schedule["active_projects"] == occupied_today
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    assert tomorrow not in (tmp_path / "native-schedule-call").read_text(encoding="utf-8")


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

    result = run_pipeline(tmp_path, scripts, binaries, expected_success_count=2)

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
    result = run_pipeline(tmp_path, scripts, binaries, expected_success_count=1)

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


def test_today_batch_error_does_not_abort_next_day_generation_and_publishing(tmp_path: Path):
    """When today's batch encounters an error in Stage 2, the pipeline must NOT abort;
    it must continue to generate, validate, queue, and platform-schedule next-day videos.
    """
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")

    # Mock schedule_today_native.py to fail for TODAY, but succeed for NEXT_DATE
    schedule_mock = """#!/usr/bin/env python3
import sys
from pathlib import Path

# Record all invocations
with open("native-schedule-calls.log", "a") as f:
    f.write(" ".join(sys.argv) + "\\n")

# Check the --date argument
if "--date" in sys.argv:
    idx = sys.argv.index("--date")
    target_date = sys.argv[idx + 1]
    with open("today_date.txt", "r") as tf:
        today_date = tf.read().strip()
    # Fail if today's date, succeed if tomorrow/next-day
    if target_date == today_date:
        print("SIMULATED ERROR: Today scheduling failed", file=sys.stderr)
        raise SystemExit(1)

raise SystemExit(0)
"""
    write_executable(scripts / "schedule_today_native.py", schedule_mock)

    today = datetime.now(timezone.utc).strftime("%F")
    (tmp_path / "today_date.txt").write_text(today, encoding="utf-8")

    # Put a failing project into active_projects for today
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["active_projects"] = [
        {"project_id": "today_failing_proj", "publish_date": today, "publish_time": "01:00"}
    ]
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    result = run_pipeline(tmp_path, scripts, binaries, expected_success_count=2)

    assert result.returncode == 0, f"Expected pipeline to succeed for next day, but failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    # Verify that schedule_today_native was invoked for next day
    calls = (tmp_path / "native-schedule-calls.log").read_text(encoding="utf-8")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    assert f"--date {tomorrow}" in calls

    # Verify that new projects were queued for tomorrow
    updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    tomorrow_projects = [
        p["project_id"] for p in updated_schedule.get("active_projects", [])
        if isinstance(p, dict) and p.get("publish_date") == tomorrow
    ]
    assert len(tomorrow_projects) > 0, "Expected next-day projects to be queued"
    assert "cand_fail" in tomorrow_projects or "cand_pass" in tomorrow_projects

    # Verify heartbeat completed
    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert heartbeat.is_file()
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "completed"


def test_today_platform_schedule_failure_still_schedules_next_day(tmp_path: Path):
    """When Stage 6.5 encounters a failure scheduling today's project, next-day scheduling must still proceed."""
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")

    # Mock schedule_today_native.py to fail for TODAY in stage 6.5, but succeed for tomorrow
    schedule_mock = """#!/usr/bin/env python3
import sys

with open("native-schedule-calls-stage6.log", "a") as f:
    f.write(" ".join(sys.argv) + "\\n")

if "--date" in sys.argv:
    idx = sys.argv.index("--date")
    target_date = sys.argv[idx + 1]
    with open("today_date.txt", "r") as tf:
        today_date = tf.read().strip()
    if target_date == today_date:
        # Fails for today
        print("ERROR: today upload failed", file=sys.stderr)
        raise SystemExit(1)

raise SystemExit(0)
"""
    write_executable(scripts / "schedule_today_native.py", schedule_mock)

    today = datetime.now(timezone.utc).strftime("%F")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    (tmp_path / "today_date.txt").write_text(today, encoding="utf-8")

    result = run_pipeline(tmp_path, scripts, binaries, expected_success_count=2)

    assert result.returncode == 0, f"Expected pipeline to succeed, got:\n{result.stdout}\n{result.stderr}"

    calls = (tmp_path / "native-schedule-calls-stage6.log").read_text(encoding="utf-8")
    assert f"--date {tomorrow}" in calls

    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert heartbeat.is_file()
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "completed"


def test_cron_empty_today_allocates_both_today_and_next_day(tmp_path: Path):
    """When cron runs with empty active_projects, newly validated projects must be allocated

    to BOTH today (for same-day publishing) and next day (for next-day platform publishing).
    """
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")

    # Mock schedule_today_native.py to record all date calls
    schedule_mock = """#!/usr/bin/env python3
import sys

with open("native-schedule-both-dates.log", "a") as f:
    f.write(" ".join(sys.argv) + "\\n")

raise SystemExit(0)
"""
    write_executable(scripts / "schedule_today_native.py", schedule_mock)

    # Empty active_projects
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["active_projects"] = []
    # Configure slot far in future for today
    schedule["slots"]["publish_slots_vn"] = ["23:59"]
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    today = datetime.now(timezone.utc).strftime("%F")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")

    result = run_pipeline(tmp_path, scripts, binaries, expected_success_count=2)

    assert result.returncode == 0, f"Expected pipeline to succeed, got:\n{result.stdout}\n{result.stderr}"

    calls = (tmp_path / "native-schedule-both-dates.log").read_text(encoding="utf-8")
    # Verify that BOTH today AND tomorrow were platform-scheduled
    assert f"--date {today}" in calls
    assert f"--date {tomorrow}" in calls

    # Verify that both dates have projects queued in active_projects
    updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    today_pids = [
        p["project_id"] for p in updated_schedule.get("active_projects", [])
        if isinstance(p, dict) and p.get("publish_date") == today
    ]
    tomorrow_pids = [
        p["project_id"] for p in updated_schedule.get("active_projects", [])
        if isinstance(p, dict) and p.get("publish_date") == tomorrow
    ]
    assert len(today_pids) >= 1, "Expected at least 1 project queued for today"
    assert len(tomorrow_pids) >= 1, "Expected at least 1 project queued for tomorrow"

    heartbeat = tmp_path / "logs" / "heartbeat" / "daily_orchestrator.json"
    assert heartbeat.is_file()
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["status"] == "completed"


def test_more_validated_projects_than_available_slots_queues_available_count(tmp_path: Path):
    """When more validated projects exist than empty slots, it must queue up to the available slots rather than fail."""
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    (scripts / "codex_agent_validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    occupy_today_slots(config)

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    # Pre-occupy 2 of 3 tomorrow slots: 01:00 and 02:00
    schedule["active_projects"].extend([
        {"project_id": "pre_01", "publish_date": tomorrow, "publish_time": "01:00"},
        {"project_id": "pre_02", "publish_date": tomorrow, "publish_time": "02:00"},
    ])
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    # Pipeline generates 2 projects (cand_fail, cand_pass), but only 1 slot (03:00) is free
    result = run_pipeline(tmp_path, scripts, binaries, expected_success_count=1)

    assert result.returncode == 0, f"Expected pipeline to succeed, got:\n{result.stdout}\n{result.stderr}"

    updated = json.loads(schedule_path.read_text(encoding="utf-8"))
    tomorrow_entries = [p for p in updated.get("active_projects", []) if p.get("publish_date") == tomorrow]
    # Total tomorrow entries should now be exactly 3 (2 pre-occupied + 1 newly queued)
    assert len(tomorrow_entries) == 3
    newly_queued = [p for p in tomorrow_entries if p["project_id"] not in ("pre_01", "pre_02")]
    assert len(newly_queued) == 1
    assert newly_queued[0]["publish_time"] == "03:00"


def test_retry_daily_pipeline_noop_when_satisfied(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["active_projects"] = [
        {"project_id": f"p_{i}", "publish_date": tomorrow, "publish_time": f"0{i}:00"}
        for i in range(1, 4)
    ]
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    write_executable(scripts / "run_strict_docker_publish.sh", "#!/usr/bin/env bash\necho CALLED > call.txt; exit 1\n")

    res = subprocess.run(
        ["bash", str(scripts / "retry_daily_pipeline.sh")],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC"},
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert not (tmp_path / "call.txt").exists()
    assert "No retry needed" in res.stdout


def test_full_queue_with_pending_native_schedule_retries_without_generation(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text())
    schedule["active_projects"] = [
        {"project_id": f"p_{i}", "publish_date": tomorrow, "publish_time": f"0{i}:00"}
        for i in range(1, 4)
    ]
    schedule_path.write_text(json.dumps(schedule))
    pending = tmp_path / "logs" / "strict_docker_publish" / f"platform-schedule-{tomorrow}.pending"
    pending.parent.mkdir(parents=True)
    pending.touch()
    (scripts / "schedule_today_native.py").write_text(
        "import sys\nfrom pathlib import Path\nPath('scheduled-date').write_text(sys.argv[2])\n"
    )
    write_executable(scripts / "run_strict_docker_publish.sh", "#!/usr/bin/env bash\ntouch unexpected-generation\n")
    res = subprocess.run(["bash", str(scripts / "retry_daily_pipeline.sh")], cwd=tmp_path,
                         env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC"},
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert (tmp_path / "scheduled-date").read_text() == tomorrow
    assert not (tmp_path / "unexpected-generation").exists()
    assert not pending.exists()


def test_failed_native_schedule_retry_keeps_pending_marker(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text())
    schedule["active_projects"] = [
        {"project_id": f"p_{i}", "publish_date": tomorrow, "publish_time": f"0{i}:00"}
        for i in range(1, 4)
    ]
    schedule_path.write_text(json.dumps(schedule))
    pending = tmp_path / "logs" / "strict_docker_publish" / f"platform-schedule-{tomorrow}.pending"
    pending.parent.mkdir(parents=True)
    pending.touch()
    (scripts / "schedule_today_native.py").write_text("raise SystemExit(1)\n")
    result = subprocess.run(["bash", str(scripts / "retry_daily_pipeline.sh")], cwd=tmp_path,
                            env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC"},
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert pending.exists()


def test_retry_daily_pipeline_skips_when_lock_held(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    lock_file = tmp_path / ".strict_docker_publish.lock"
    lock_file.write_text("", encoding="utf-8")

    fd = os.open(str(lock_file), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = subprocess.run(
            ["bash", str(scripts / "retry_daily_pipeline.sh")],
            cwd=tmp_path,
            env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC"},
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "lock held" in res.stdout
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_retry_daily_pipeline_triggers_when_incomplete(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["active_projects"] = [
        {"project_id": "p_1", "publish_date": tomorrow, "publish_time": "01:00"},
        {"project_id": "p_2", "publish_date": tomorrow, "publish_time": "02:00"},
    ]
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    write_executable(
        scripts / "run_strict_docker_publish.sh",
        "#!/usr/bin/env bash\necho EXPECTED=$EXPECTED_SUCCESS_COUNT > trigger.log\nexit 0\n",
    )

    res = subprocess.run(
        ["bash", str(scripts / "retry_daily_pipeline.sh")],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "PUBLISH_TZ": "UTC", "NEWS_DISCOVERY_PROVIDER": "daily-news"},
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert (tmp_path / "trigger.log").is_file()
    assert (tmp_path / "trigger.log").read_text(encoding="utf-8").strip() == "EXPECTED=1"


def test_daily_news_fetch_imports_project_modules_without_pythonpath(tmp_path: Path):
    scripts, _, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    cli = tmp_path / "tools/news/news_pipeline_cli.py"
    cli.parent.mkdir(parents=True)
    (tmp_path / "lib/cron_import_probe.py").write_text("VALUE = 'loaded'\n")
    cli.write_text(
        "from lib.cron_import_probe import VALUE\n"
        "from pathlib import Path\n"
        "Path('fetch-import-result').write_text(VALUE)\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update({
        "PATH": f"{binaries}:{env['PATH']}", "PUBLISH_TZ": "UTC",
        "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1", "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        "NEWS_DISCOVERY_PROVIDER": "daily-news", "TMP_ROOT": str(tmp_path),
        "DAILY_GENERATION_RETRIES": "1", "GENERATION_RETRY_DELAY_SECONDS": "0",
    })
    result = subprocess.run(["bash", str(scripts / "run_strict_docker_publish.sh")],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert (tmp_path / "fetch-import-result").exists(), result.stdout + result.stderr
    assert (tmp_path / "fetch-import-result").read_text() == "loaded"


def test_generation_accumulates_candidates_across_attempts(tmp_path: Path):
    """When attempt 1 yields 1 valid project and attempt 2 yields 1 more, all are accumulated and queued."""
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    (scripts / "codex_agent_validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    occupy_today_slots(config)

    write_executable(
        scripts / "run_daily_news_pipeline.sh",
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COUNT_FILE="$ROOT/gen_count"
count=0
[ ! -f "$COUNT_FILE" ] || count=$(cat "$COUNT_FILE")
count=$((count + 1))
printf '%s' "$count" > "$COUNT_FILE"

pid="cand_att${count}"
mkdir -p "$ROOT/projects/$pid/renders"
printf '{"id":"%s","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}' "$pid" > "$ROOT/projects/$pid/publish_metadata.json"
printf video > "$ROOT/projects/$pid/renders/final_full_vi_9x16.mp4"
printf video > "$ROOT/projects/$pid/renders/final_reels_vi_9x16.mp4"
printf '{"strict_quality_pass": true}' > "$ROOT/projects/$pid/validation_status.json"
PYTHONPATH="$ROOT/tests/fixtures:$ROOT" python3 -c 'import sys; from pathlib import Path; from news_evidence import write_reviewed_news_evidence; write_reviewed_news_evidence(Path(sys.argv[1]))' "$ROOT/projects/$pid"
echo "PROJECT_ID=$pid"

if [ "$count" -eq 1 ]; then
  exit 2
else
  exit 0
fi
""",
    )

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule_path = config / "publish_schedule.json"

    res = subprocess.run(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "PUBLISH_TZ": "UTC",
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
            "DAILY_GENERATION_RETRIES": "3",
            "EXPECTED_SUCCESS_COUNT": "2",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
            "GENERATION_RETRY_DELAY_SECONDS": "0",
        },
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Expected success, got:\n{res.stdout}\n{res.stderr}"

    updated = json.loads(schedule_path.read_text(encoding="utf-8"))
    tomorrow_pids = [
        p["project_id"] for p in updated.get("active_projects", [])
        if p.get("publish_date") == tomorrow
    ]
    assert "cand_att1" in tomorrow_pids
    assert "cand_att2" in tomorrow_pids
    assert len(tomorrow_pids) == 2


def test_cron_pipeline_scripts_default_local_agent_disabled():
    strict_script = (ROOT / "scripts" / "run_strict_docker_publish.sh").read_text(encoding="utf-8")
    daily_script = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(encoding="utf-8")

    assert "export OPENMONTAGE_REQUIRE_LOCAL_AGENT=1" not in strict_script
    assert "export OPENMONTAGE_REQUIRE_LOCAL_AGENT=1" not in daily_script
    assert 'OPENMONTAGE_REQUIRE_LOCAL_AGENT="${OPENMONTAGE_REQUIRE_LOCAL_AGENT:-0}"' in strict_script
    assert 'OPENMONTAGE_REQUIRE_LOCAL_AGENT="${OPENMONTAGE_REQUIRE_LOCAL_AGENT:-0}"' in daily_script


def test_old_bug_local_agent_requirement_causes_cron_failure_and_retry_recovery(tmp_path: Path):
    """Mocks the old bug where OPENMONTAGE_REQUIRE_LOCAL_AGENT=1 causes pipeline failure,
    then verifies retry succeeds when OPENMONTAGE_REQUIRE_LOCAL_AGENT defaults to 0."""
    scripts, config, projects = tmp_path / "scripts", tmp_path / "config", tmp_path / "projects"
    binaries = tmp_path / "bin"
    for directory in (scripts, config, projects, binaries):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts / "run_strict_docker_publish.sh")
    shutil.copy2(ROOT / "scripts" / "retry_daily_pipeline.sh", scripts / "retry_daily_pipeline.sh")
    for relative in ("lib/news_evidence.py", "lib/news_release_gate.py", "tests/fixtures/news_evidence.py"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)

    schedule_path = config / "publish_schedule.json"
    schedule_path.write_text(
        json.dumps({
            "slots": {"publish_slots_vn": ["01:00", "02:00", "03:00"]},
            "active_projects": [],
        }),
        encoding="utf-8",
    )

    for name in ("codex", "ffmpeg", "ffprobe"):
        write_executable(binaries / name, "#!/usr/bin/env bash\nexit 0\n")
    write_executable(binaries / "curl", "#!/usr/bin/env bash\nexit 1\n")

    write_executable(
        scripts / "run_daily_news_pipeline.sh",
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${OPENMONTAGE_REQUIRE_LOCAL_AGENT:-0}" = "1" ]; then
  echo "lib.local_agent_handoff.HandoffError: local-agent request timed out" >&2
  exit 1
fi
for pid in cand_mock_fixed1 cand_mock_fixed2 cand_mock_fixed3; do
  mkdir -p "$ROOT/projects/$pid/renders"
  printf '{"id":"%s","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}' "$pid" > "$ROOT/projects/$pid/publish_metadata.json"
  printf video > "$ROOT/projects/$pid/renders/final_full_vi_9x16.mp4"
  printf video > "$ROOT/projects/$pid/renders/final_reels_vi_9x16.mp4"
  printf '{"strict_quality_pass": true}' > "$ROOT/projects/$pid/validation_status.json"
  PYTHONPATH="$ROOT/tests/fixtures:$ROOT" python3 -c 'import sys; from pathlib import Path; from news_evidence import write_reviewed_news_evidence; write_reviewed_news_evidence(Path(sys.argv[1]))' "$ROOT/projects/$pid"
  echo "PROJECT_ID=$pid"
done
""",
    )
    (scripts / "validate_render_quality.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "validate_publish_metadata.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "codex_agent_validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "schedule_today_native.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "pipeline_monitoring.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    write_executable(scripts / "clear_stale_projects.sh", "#!/usr/bin/env bash\nexit 0\n")

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")

    # Step 1: Simulate the OLD BUG where OPENMONTAGE_REQUIRE_LOCAL_AGENT=1 is forced.
    old_bug_res = subprocess.run(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "PUBLISH_TZ": "UTC",
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
            "DAILY_GENERATION_RETRIES": "1",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
            "OPENMONTAGE_REQUIRE_LOCAL_AGENT": "1",
            "GENERATION_RETRY_DELAY_SECONDS": "0",
        },
        capture_output=True,
        text=True,
    )
    assert old_bug_res.returncode != 0
    assert "local-agent request timed out" in old_bug_res.stderr or "local-agent request timed out" in old_bug_res.stdout
    schedule_data = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert len(schedule_data.get("active_projects", [])) == 0

    # Step 2: Test the FIX with retry_daily_pipeline.sh where OPENMONTAGE_REQUIRE_LOCAL_AGENT is unset/0.
    retry_res = subprocess.run(
        ["bash", str(scripts / "retry_daily_pipeline.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "PUBLISH_TZ": "UTC",
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
            "DAILY_GENERATION_RETRIES": "1",
            "EXPECTED_SUCCESS_COUNT": "3",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
            "GENERATION_RETRY_DELAY_SECONDS": "0",
        },
        capture_output=True,
        text=True,
    )
    assert retry_res.returncode == 0, f"Retry failed:\nSTDOUT: {retry_res.stdout}\nSTDERR: {retry_res.stderr}"

    updated = json.loads(schedule_path.read_text(encoding="utf-8"))
    tomorrow_pids = [
        p["project_id"] for p in updated.get("active_projects", [])
        if p.get("publish_date") == tomorrow
    ]
    assert len(tomorrow_pids) == 3
    assert set(tomorrow_pids) == {"cand_mock_fixed1", "cand_mock_fixed2", "cand_mock_fixed3"}






