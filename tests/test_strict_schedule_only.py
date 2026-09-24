import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_strict_run_fails_when_native_platform_schedule_fails(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for directory in (scripts_dir, config_dir, projects_dir, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": ["01:00", "02:00", "03:00"]},
            "active_projects": [],
        }),
        encoding="utf-8",
    )

    (bin_dir / "claude").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
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
  echo "PROJECT_ID=$pid"
done
""",
        encoding="utf-8",
    )
    (scripts_dir / "run_daily_news_pipeline.sh").chmod(0o755)

    for name in ("validate_render_quality.py", "validate_publish_metadata.py", "claude_agent_validation.py"):
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
            "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
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
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for directory in (scripts_dir, config_dir, projects_dir, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    import shutil
    from zoneinfo import ZoneInfo
    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")

    now_local = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    today = now_local.strftime("%F")
    next_date = (now_local + timedelta(days=1)).strftime("%F")

    # Create slots: two passed, one available
    past_dt = now_local - timedelta(minutes=30)
    future_dt = now_local + timedelta(minutes=60)
    past_slot_1 = "01:00"
    past_slot_2 = past_dt.strftime("%H:%M")
    future_slot_1 = future_dt.strftime("%H:%M")

    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": [past_slot_1, past_slot_2, future_slot_1]},
            "active_projects": [],
        }),
        encoding="utf-8",
    )

    (bin_dir / "claude").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    for name in ("ffmpeg", "ffprobe"):
        executable = bin_dir / name
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    (scripts_dir / "run_daily_news_pipeline.sh").write_text(
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for pid in cand_A cand_B cand_C cand_D; do
  mkdir -p "$ROOT/projects/$pid/renders"
  printf '{"id":"%s","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}' "$pid" > "$ROOT/projects/$pid/publish_metadata.json"
  echo "dummy mp4 data" > "$ROOT/projects/$pid/renders/final_full_vi_9x16.mp4"
  echo "dummy mp4 data" > "$ROOT/projects/$pid/renders/final_reels_vi_9x16.mp4"
  echo "PROJECT_ID=$pid"
done
""",
        encoding="utf-8",
    )
    (scripts_dir / "run_daily_news_pipeline.sh").chmod(0o755)

    for name in ("validate_render_quality.py", "validate_publish_metadata.py", "claude_agent_validation.py"):
        (scripts_dir / name).write_text("", encoding="utf-8")

    (scripts_dir / "schedule_today_native.py").write_text(
        "import sys\nfrom pathlib import Path\nwith open('platform-schedule-called.log', 'a') as f: f.write(' '.join(sys.argv) + '\\n')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    (scripts_dir / "clear_stale_projects.sh").write_text("exit 0\n", encoding="utf-8")
    (scripts_dir / "clear_stale_projects.sh").chmod(0o755)
    (scripts_dir / "publish_manual_video.py").write_text("exit 0\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(scripts_dir / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PUBLISH_TZ": "Asia/Ho_Chi_Minh", "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1"},
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    schedule = json.loads((config_dir / "publish_schedule.json").read_text(encoding="utf-8"))
    queued = schedule["active_projects"]

    assert len(queued) == 4
    assert queued[0]["project_id"] == "cand_A" and queued[0]["publish_date"] == today and queued[0]["publish_time"] == future_slot_1
    assert queued[1]["project_id"] == "cand_B" and queued[1]["publish_date"] == next_date and queued[1]["publish_time"] == past_slot_1

    platform_command = (tmp_path / "platform-schedule-called.log").read_text(encoding="utf-8")
    assert today in platform_command and next_date in platform_command


def test_strict_run_preserves_existing_queue_entries(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for directory in (scripts_dir, config_dir, projects_dir, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    from zoneinfo import ZoneInfo

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")
    now_local = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    today = now_local.strftime("%F")
    next_date = (now_local + timedelta(days=1)).strftime("%F")
    future_slot = (now_local + timedelta(minutes=60)).strftime("%H:%M")

    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": [future_slot, "01:00", "02:00"]},
            "active_projects": [
                {"project_id": "existing_next", "publish_date": next_date, "publish_time": "02:00"}
            ],
        }),
        encoding="utf-8",
    )

    (bin_dir / "claude").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    for name in ("ffmpeg", "ffprobe"):
        executable = bin_dir / name
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    (scripts_dir / "run_daily_news_pipeline.sh").write_text(
        """#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/projects/cand_new/renders"
printf '{"id":"cand_new","title":"T","description":"D","yt_shorts":"renders/final_reels_vi_9x16.mp4","ig_reels":"renders/final_reels_vi_9x16.mp4","fb_video":"renders/final_full_vi_9x16.mp4"}' > "$ROOT/projects/cand_new/publish_metadata.json"
echo "dummy mp4 data" > "$ROOT/projects/cand_new/renders/final_full_vi_9x16.mp4"
echo "dummy mp4 data" > "$ROOT/projects/cand_new/renders/final_reels_vi_9x16.mp4"
echo "PROJECT_ID=cand_new"
""",
        encoding="utf-8",
    )
    (scripts_dir / "run_daily_news_pipeline.sh").chmod(0o755)

    for name in ("validate_render_quality.py", "validate_publish_metadata.py", "claude_agent_validation.py"):
        (scripts_dir / name).write_text("", encoding="utf-8")
    (scripts_dir / "schedule_today_native.py").write_text(
        "import sys\nfrom pathlib import Path\nwith open('platform-schedule-called.log', 'a') as f: f.write(' '.join(sys.argv) + '\\n')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    (scripts_dir / "clear_stale_projects.sh").write_text("exit 0\n", encoding="utf-8")
    (scripts_dir / "clear_stale_projects.sh").chmod(0o755)

    result = subprocess.run(
        ["bash", str(scripts_dir / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PUBLISH_TZ": "Asia/Ho_Chi_Minh", "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    schedule = json.loads((config_dir / "publish_schedule.json").read_text(encoding="utf-8"))
    entries = {(entry["project_id"], entry["publish_date"], entry["publish_time"]) for entry in schedule["active_projects"]}
    assert ("existing_next", next_date, "02:00") in entries
    assert ("cand_new", today, future_slot) in entries
    assert len(entries) == 2
