import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_documented_youtube_schedule_command_forwards_positional_date(tmp_path: Path) -> None:
    """The public scheduler wrapper must reach the native scheduler safely."""
    captured_args = tmp_path / "args.txt"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\necho 'No queued projects for 2099-01-01'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = os.environ | {"OPENMONTAGE_PYTHON": str(fake_python), "CAPTURE_ARGS": str(captured_args)}

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
    assert captured_args.read_text(encoding="utf-8").splitlines() == [
        "scripts/schedule_today_native.py", "--date", "2099-01-01", "--dry-run",
    ]
