import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

SLOT_BUFFER_SECONDS = 1200  # must match run_strict_docker_publish.sh's slot guard


def expected_queue_assignment(now: datetime, tzname: str, slots: list[str],
                              today: str, next_date: str,
                              today_occupied: set, next_occupied: set,
                              num_projects: int) -> list[tuple[str, str]] | None:
    """Mirror the orchestrator's slot assignment (today-first, then next-day).

    Returns None when fewer total slots than projects are available (the
    orchestrator then fails closed with "not enough ... publish slots").
    """
    tz = ZoneInfo(tzname)
    now_epoch = now.timestamp()
    today_slots: list[str] = []
    next_slots: list[str] = []
    for slot in slots:
        slot_epoch = datetime.strptime(f"{today} {slot}", "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp()
        if slot_epoch > now_epoch + SLOT_BUFFER_SECONDS and slot not in today_occupied:
            today_slots.append(slot)
        if slot not in next_occupied:
            next_slots.append(slot)
    if len(today_slots) + len(next_slots) < num_projects:
        return None
    assignments: list[tuple[str, str]] = []
    ti = ni = 0
    for _ in range(num_projects):
        if ti < len(today_slots):
            assignments.append((today, today_slots[ti]))
            ti += 1
        else:
            assignments.append((next_date, next_slots[ni]))
            ni += 1
    return assignments


def _run_fixture(tmp_path: Path, projects: list[str], slots: list[str],
                 active: list[dict] | None = None, tzname: str = "Asia/Ho_Chi_Minh") -> subprocess.CompletedProcess:
    """Shared fixture: copy the real orchestrator, mock every external stage, run it."""
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    bin_dir = tmp_path / "bin"
    for directory in (scripts_dir, config_dir, tmp_path / "projects", bin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")
    for relative in ("lib/news_evidence.py", "lib/news_release_gate.py", "tests/fixtures/news_evidence.py"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": slots},
            "active_projects": active or [],
        }),
        encoding="utf-8",
    )

    (bin_dir / "codex").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "codex").chmod(0o755)
    for name in ("ffmpeg", "ffprobe"):
        executable = bin_dir / name
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    pipeline = ["#!/usr/bin/env bash", "set -eu", 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"']
    for pid in projects:
        pipeline += [
            f'mkdir -p "$ROOT/projects/{pid}/renders"',
            f'printf \'{{"id":"{pid}","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}}\' > "$ROOT/projects/{pid}/publish_metadata.json"',
            f'echo "dummy mp4 data" > "$ROOT/projects/{pid}/renders/final_full_vi_9x16.mp4"',
            f'echo "dummy mp4 data" > "$ROOT/projects/{pid}/renders/final_reels_vi_9x16.mp4"',
            f'PYTHONPATH="$ROOT/tests/fixtures:$ROOT" python3 -c \'import sys; from pathlib import Path; from news_evidence import write_reviewed_news_evidence; write_reviewed_news_evidence(Path(sys.argv[1]))\' "$ROOT/projects/{pid}"',
            f'echo "PROJECT_ID={pid}"',
        ]
    (scripts_dir / "run_daily_news_pipeline.sh").write_text("\n".join(pipeline) + "\n", encoding="utf-8")
    (scripts_dir / "run_daily_news_pipeline.sh").chmod(0o755)

    for name in ("validate_render_quality.py", "validate_publish_metadata.py", "codex_agent_validation.py"):
        (scripts_dir / name).write_text("", encoding="utf-8")
    (scripts_dir / "schedule_today_native.py").write_text(
        "import sys\nfrom pathlib import Path\nwith open('platform-schedule-called.log', 'a') as f: f.write(' '.join(sys.argv) + '\\n')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    (scripts_dir / "clear_stale_projects.sh").write_text("exit 0\n", encoding="utf-8")
    (scripts_dir / "clear_stale_projects.sh").chmod(0o755)
    (scripts_dir / "publish_manual_video.py").write_text("exit 0\n", encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PUBLISH_TZ": tzname,
        "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
        "GENERATION_RETRY_DELAY_SECONDS": "0",
        "PLATFORM_SCHEDULE_RETRY_DELAY_SECONDS": "0",
        "NEWS_MAX_SOURCE_AGE_HOURS": "24",
    }
    return subprocess.run(
        ["bash", str(scripts_dir / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


def test_strict_run_fails_when_native_platform_schedule_fails(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for directory in (scripts_dir, config_dir, projects_dir, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")
    for relative in ("lib/news_evidence.py", "lib/news_release_gate.py", "tests/fixtures/news_evidence.py"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": ["01:00", "02:00", "03:00"]},
            "active_projects": [],
        }),
        encoding="utf-8",
    )

    (bin_dir / "codex").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "codex").chmod(0o755)
    for name in ("ffmpeg", "ffprobe"):
        executable = bin_dir / name
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    (scripts_dir / "run_daily_news_pipeline.sh").write_text(
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for pid in cand_one cand_two cand_three; do
  mkdir -p "$ROOT/projects/$pid/renders"
  printf '{"id":"%s","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}' "$pid" > "$ROOT/projects/$pid/publish_metadata.json"
  echo "dummy mp4 data" > "$ROOT/projects/$pid/renders/final_full_vi_9x16.mp4"
  echo "dummy mp4 data" > "$ROOT/projects/$pid/renders/final_reels_vi_9x16.mp4"
  PYTHONPATH="$ROOT/tests/fixtures:$ROOT" python3 -c 'import sys; from pathlib import Path; from news_evidence import write_reviewed_news_evidence; write_reviewed_news_evidence(Path(sys.argv[1]))' "$ROOT/projects/$pid"
  echo "PROJECT_ID=$pid"
done
""",
        encoding="utf-8",
    )
    (scripts_dir / "run_daily_news_pipeline.sh").chmod(0o755)

    for name in ("validate_render_quality.py", "validate_publish_metadata.py", "codex_agent_validation.py"):
        (scripts_dir / name).write_text("", encoding="utf-8")
    (scripts_dir / "schedule_today_native.py").write_text(
        "import sys\nfrom pathlib import Path\nPath('platform-schedule-called').write_text(' '.join(sys.argv))\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    (scripts_dir / "clear_stale_projects.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (scripts_dir / "clear_stale_projects.sh").chmod(0o755)
    (scripts_dir / "publish_manual_video.py").write_text(
        "from pathlib import Path\nPath('manual-publisher-called').touch()\nraise SystemExit(7)\n",
        encoding="utf-8",
    )

    today = datetime.now(timezone.utc).strftime("%F")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    result = subprocess.run(
        ["bash", str(scripts_dir / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PUBLISH_TZ": "UTC",
            "STRICT_PUBLISH_NOW_EPOCH": str(
                int(datetime.now(timezone.utc).replace(hour=23, minute=0, second=0, microsecond=0).timestamp())
            ),
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
            "GENERATION_RETRY_DELAY_SECONDS": "0",
            "PLATFORM_SCHEDULE_RETRY_DELAY_SECONDS": "0",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    platform_command = (tmp_path / "platform-schedule-called").read_text(encoding="utf-8")
    assert "--date" in platform_command
    assert tomorrow in platform_command
    assert "next-day YouTube scheduling failed" in result.stdout
    assert all((projects_dir / pid).is_dir() for pid in ("cand_one", "cand_two", "cand_three"))

    schedule = json.loads((config_dir / "publish_schedule.json").read_text(encoding="utf-8"))
    queued = schedule["active_projects"]
    assert [entry["project_id"] for entry in queued] == ["cand_one", "cand_two", "cand_three"]
    assert [entry["publish_time"] for entry in queued] == ["01:00", "02:00", "03:00"]
    assert all(entry["publish_date"] == tomorrow for entry in queued)

def test_strict_run_today_recovery_uses_available_slots(tmp_path: Path):
    now_local = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    today = now_local.strftime("%F")
    next_date = (now_local + timedelta(days=1)).strftime("%F")
    slots = ["00:05", "12:00", "23:55"]

    available_assignments = expected_queue_assignment(
        now_local, "Asia/Ho_Chi_Minh", slots, today, next_date, set(), set(), 4
    )

    result = _run_fixture(tmp_path, ["cand_A", "cand_B", "cand_C", "cand_D"], slots)

    if available_assignments is None:
        assert result.returncode != 0
        assert "not enough unoccupied current/next-day publish slots" in (result.stdout + result.stderr)
        return

    assert result.returncode == 0, result.stdout + result.stderr
    schedule = json.loads((tmp_path / "config" / "publish_schedule.json").read_text(encoding="utf-8"))
    queued = schedule["active_projects"]

    assert len(queued) == 4
    for i, (expected_date, expected_slot) in enumerate(available_assignments):
        assert queued[i]["publish_date"] == expected_date
        assert queued[i]["publish_time"] == expected_slot

    platform_command = (tmp_path / "platform-schedule-called.log").read_text(encoding="utf-8")
    if any(d == today for d, _ in available_assignments):
        assert today in platform_command
    if any(d == next_date for d, _ in available_assignments):
        assert next_date in platform_command


def test_strict_run_preserves_existing_queue_entries(tmp_path: Path):
    now_local = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    today = now_local.strftime("%F")
    next_date = (now_local + timedelta(days=1)).strftime("%F")
    slots = ["01:00", "02:00", "23:55"]
    active = [{"project_id": "existing_next", "publish_date": next_date, "publish_time": "02:00"}]

    available_assignments = expected_queue_assignment(
        now_local, "Asia/Ho_Chi_Minh", slots, today, next_date, set(), {"02:00"}, 1
    )

    result = _run_fixture(tmp_path, ["cand_new"], slots, active)

    if available_assignments is None:
        assert result.returncode != 0
        assert "not enough unoccupied current/next-day publish slots" in (result.stdout + result.stderr)
        return

    assert result.returncode == 0, result.stdout + result.stderr
    schedule = json.loads((tmp_path / "config" / "publish_schedule.json").read_text(encoding="utf-8"))
    entries = {(entry["project_id"], entry["publish_date"], entry["publish_time"]) for entry in schedule["active_projects"]}

    expected_new_date, expected_new_slot = available_assignments[0]
    assert ("existing_next", next_date, "02:00") in entries
    assert ("cand_new", expected_new_date, expected_new_slot) in entries
    assert len(entries) == 2
