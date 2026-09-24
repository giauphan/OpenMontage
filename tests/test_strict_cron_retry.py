import json
import os
import shutil
import subprocess
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
    (config / "publish_schedule.json").write_text(
        json.dumps({
            "slots": {"publish_slots_vn": ["01:00", "02:00", "03:00"]},
            "active_projects": [],
        }),
        encoding="utf-8",
    )

    for name in ("claude", "ffmpeg", "ffprobe"):
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
  echo "PROJECT_ID=$pid"
done
""",
    )
    (scripts / "validate_render_quality.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "validate_publish_metadata.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "claude_agent_validation.py").write_text(validation_script, encoding="utf-8")
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

    result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "generation-count").read_text(encoding="utf-8") == "2"
    assert (tmp_path / "cand_fail-validation-count").read_text(encoding="utf-8") == "3"
    assert (tmp_path / "cand_pass-validation-count").read_text(encoding="utf-8") == "3"

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule = json.loads((config / "publish_schedule.json").read_text(encoding="utf-8"))
    assert schedule["active_projects"] == [{
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
    assert "claude validation failed for all projects" in result.stdout
    assert (config / "publish_schedule.json").read_text(encoding="utf-8") == original
    assert not (tmp_path / "native-schedule-call").exists()


def test_queued_project_is_available_to_slot_publisher(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(1)\n")
    (scripts / "claude_agent_validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")

    result = run_pipeline(tmp_path, scripts, binaries)

    assert result.returncode == 0, result.stdout + result.stderr
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F")
    schedule = json.loads((config / "publish_schedule.json").read_text(encoding="utf-8"))
    project_id = schedule["active_projects"][0]["project_id"]
    assert schedule["active_projects"][0]["publish_date"] == tomorrow
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
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    assert slot_result.returncode == 0, slot_result.stdout + slot_result.stderr
    assert tomorrow in (tmp_path / "slot-publisher-call").read_text(encoding="utf-8")
