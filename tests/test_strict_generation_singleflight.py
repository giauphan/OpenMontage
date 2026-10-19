import importlib.util
import os
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "strict_cron_retry_helpers", ROOT / "tests" / "test_strict_cron_retry.py"
)
assert _HELPERS_SPEC and _HELPERS_SPEC.loader
_STRICT_CRON_RETRY = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_STRICT_CRON_RETRY)
create_fixture = _STRICT_CRON_RETRY.create_fixture
occupy_today_slots = _STRICT_CRON_RETRY.occupy_today_slots
run_pipeline = _STRICT_CRON_RETRY.run_pipeline


def install_blocking_generation_stub(scripts: Path) -> None:
    stub = scripts / "run_daily_news_pipeline.sh"
    stub.write_text(
        '''#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COUNT_FILE="$ROOT/generation-count"
count=0; [ ! -f "$COUNT_FILE" ] || count=$(cat "$COUNT_FILE")
count=$((count + 1)); printf '%s' "$count" > "$COUNT_FILE"
touch "$GENERATION_ENTERED"
while [ ! -e "$GENERATION_RELEASE" ]; do sleep 0.05; done
exit 0
''',
        encoding="utf-8",
    )
    stub.chmod(0o755)


def lock_test_env(tmp_path: Path, binaries: Path) -> dict[str, str]:
    (tmp_path / "tmp").mkdir(exist_ok=True)
    return {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "PUBLISH_TZ": "UTC",
        "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1",
        "CODEX_HOME": str(tmp_path / "codex"),
        "GENERATION_ENTERED": str(tmp_path / "generation-entered"),
        "GENERATION_RELEASE": str(tmp_path / "generation-release"),
        "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        "MIN_DISK_MB": "0",
        "MIN_TMP_DISK_MB": "0",
        "TMP_ROOT": str(tmp_path / "tmp"),
        "GENERATION_RETRY_DELAY_SECONDS": "0",
        "DAILY_GENERATION_RETRIES": "1",
    }


def wait_for_generation(tmp_path: Path, owner: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    entered = tmp_path / "generation-entered"
    while not entered.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert entered.exists(), "owner did not reach generation"


def kill_process_group(owner: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(owner.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if owner.poll() is None:
        owner.wait(timeout=10)


def test_overlapping_strict_run_exits_before_creating_run_state(tmp_path: Path):
    scripts, _, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    occupy_today_slots(tmp_path / "config")
    install_blocking_generation_stub(scripts)
    env = lock_test_env(tmp_path, binaries)
    owner = subprocess.Popen(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        wait_for_generation(tmp_path, owner)
        logs = tmp_path / "logs" / "strict_docker_publish"
        files_before = {path.name for path in logs.iterdir()}
        states_before = set(logs.glob("state_*.json"))
        count_before = (tmp_path / "generation-count").read_text(encoding="utf-8")
        contender = subprocess.run(
            ["bash", str(scripts / "run_strict_docker_publish.sh")],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert contender.returncode == 75
        assert "another strict publish run is active" in contender.stderr
        assert {path.name for path in logs.iterdir()} == files_before
        assert set(logs.glob("state_*.json")) == states_before
        assert (tmp_path / "generation-count").read_text(encoding="utf-8") == count_before
    finally:
        (tmp_path / "generation-release").touch()
        try:
            owner.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            kill_process_group(owner)
            owner.communicate(timeout=10)
        finally:
            kill_process_group(owner)


def test_lock_released_after_success_and_failure(tmp_path: Path):
    scripts, config, binaries = create_fixture(tmp_path, "raise SystemExit(1)\n")
    occupy_today_slots(config)

    failed = run_pipeline(tmp_path, scripts, binaries)
    assert failed.returncode != 0
    assert "validation failed for all projects" in (failed.stdout + failed.stderr).lower()
    # Today's native scheduling intentionally occurs before generation/validation.

    (scripts / "codex_agent_validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    succeeded = run_pipeline(tmp_path, scripts, binaries)
    assert succeeded.returncode == 0, succeeded.stdout + succeeded.stderr
    assert (tmp_path / "native-schedule-call").exists()


def test_lock_released_after_process_group_termination(tmp_path: Path):
    scripts, _, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    install_blocking_generation_stub(scripts)
    env = lock_test_env(tmp_path, binaries)
    owner = subprocess.Popen(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        wait_for_generation(tmp_path, owner)
        os.killpg(owner.pid, signal.SIGTERM)
        owner.wait(timeout=10)
        (scripts / "run_daily_news_pipeline.sh").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        retry_env = {**env, "GENERATION_ENTERED": str(tmp_path / "retry-entered")}
        retry = subprocess.run(
            ["bash", str(scripts / "run_strict_docker_publish.sh")],
            cwd=tmp_path,
            env=retry_env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert retry.returncode != 75, retry.stdout + retry.stderr
        assert not (tmp_path / "retry-entered").exists()
        assert (tmp_path / "generation-count").read_text(encoding="utf-8") == "1"
    finally:
        (tmp_path / "generation-release").touch()
        kill_process_group(owner)


def test_sigkill_parent_keeps_lock_until_inherited_descendants_exit(tmp_path: Path):
    scripts, _, binaries = create_fixture(tmp_path, "raise SystemExit(0)\n")
    install_blocking_generation_stub(scripts)
    env = lock_test_env(tmp_path, binaries)
    owner = subprocess.Popen(
        ["bash", str(scripts / "run_strict_docker_publish.sh")],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    group_still_running = False
    try:
        wait_for_generation(tmp_path, owner)
        generation_count = (tmp_path / "generation-count").read_text(encoding="utf-8")
        os.kill(owner.pid, signal.SIGKILL)
        owner.wait(timeout=10)
        group_still_running = True

        logs = tmp_path / "logs" / "strict_docker_publish"
        files_before = {path.name for path in logs.iterdir()}
        states_before = set(logs.glob("state_*.json"))
        blocked = subprocess.run(
            ["bash", str(scripts / "run_strict_docker_publish.sh")],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert blocked.returncode == 75, blocked.stdout + blocked.stderr
        assert {path.name for path in logs.iterdir()} == files_before
        assert set(logs.glob("state_*.json")) == states_before
        assert (tmp_path / "generation-count").read_text(encoding="utf-8") == generation_count

        os.killpg(owner.pid, signal.SIGKILL)
        group_still_running = False
        (scripts / "run_daily_news_pipeline.sh").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        retry = subprocess.run(
            ["bash", str(scripts / "run_strict_docker_publish.sh")],
            cwd=tmp_path,
            env={**env, "CODEX_HOME": str(tmp_path / "retry-codex")},
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert retry.returncode != 75, retry.stdout + retry.stderr
    finally:
        (tmp_path / "generation-release").touch()
        kill_process_group(owner)
        if group_still_running:
            try:
                os.killpg(owner.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
