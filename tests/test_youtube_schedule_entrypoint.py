import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_documented_youtube_schedule_command_forwards_positional_date(tmp_path: Path) -> None:
    """The public scheduler wrapper must reach the native scheduler safely."""
    schedule = tmp_path / "publish_schedule.json"
    schedule.write_text(
        json.dumps(
            {
                "timezone": "UTC",
                "youtube": {"account": "test-account"},
                "active_projects": [],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ | {"OPENMONTAGE_CONFIG": str(schedule)}

    result = subprocess.run(
        [str(ROOT / "scripts" / "run_youtube_schedule.sh"), "2099-01-01", "--dry-run"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "No queued projects for 2099-01-01" in result.stdout
