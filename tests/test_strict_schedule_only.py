import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_strict_run_queues_tomorrow_without_platform_upload(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    config_dir = tmp_path / "config"
    projects_dir = tmp_path / "projects"
    bin_dir = tmp_path / "bin"
    for directory in (scripts_dir, config_dir, projects_dir, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "scripts" / "run_strict_docker_publish.sh", scripts_dir / "run_strict_docker_publish.sh")
    today = datetime.now(timezone.utc).strftime("%F")
    (config_dir / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": ["09:15", "14:15", "21:15"]},
            "active_projects": [
                {"project_id": "cand_due_today", "publish_date": today, "publish_time": "09:15"},
            ],
        }),
        encoding="utf-8",
    )
    (projects_dir / "cand_due_today").mkdir()
    (projects_dir / "cand_due_today" / "publish_metadata.json").write_text(
        json.dumps({
            "id": "cand_due_today",
            "title": "T",
            "description": "D",
            "yt_shorts": "renders/final_reels_vi_9x16.mp4",
            "ig_reels": "renders/final_reels_vi_9x16.mp4",
            "fb_video": "renders/final_full_vi_9x16.mp4",
        }),
        encoding="utf-8",
    )
    renders = projects_dir / "cand_due_today" / "renders"
    renders.mkdir()
    (renders / "final_full_vi_9x16.mp4").touch()
    (renders / "final_reels_vi_9x16.mp4").touch()

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
    (scripts_dir / "clear_stale_projects.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (scripts_dir / "clear_stale_projects.sh").chmod(0o755)
    (scripts_dir / "publish_manual_video.py").write_text(
        """import sys, shutil, json
from pathlib import Path
project_dir = Path(sys.argv[1])
pid = project_dir.name
shutil.rmtree(project_dir, ignore_errors=True)
config = Path('config/publish_schedule.json')
if config.exists():
    data = json.loads(config.read_text(encoding='utf-8'))
    data['active_projects'] = [p for p in data.get('active_projects', []) if (p.get('project_id') if isinstance(p, dict) else p) != pid]
    config.write_text(json.dumps(data), encoding='utf-8')
raise SystemExit(0)
""",
        encoding="utf-8",
    )

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

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (tmp_path / "platform-upload-called").exists()
    assert all((projects_dir / pid).is_dir() for pid in ("cand_one", "cand_two", "cand_three"))

    schedule = json.loads((config_dir / "publish_schedule.json").read_text(encoding="utf-8"))
    queued = schedule["active_projects"]
    assert [entry["project_id"] for entry in queued] == ["cand_one", "cand_two", "cand_three"]
    assert [entry["publish_time"] for entry in queued] == ["09:15", "14:15", "21:15"]
    assert all(entry["publish_date"] == tomorrow for entry in queued)
