"""Disposable-container cron integration checks for daily strict preflight.

The real-cron test requires root inside Docker and a checkout under /work. It
saves/restores only that disposable container's root crontab, uses an isolated
project root, starts its own foreground cron process group, and never reaches
generation or publishing.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
CRON_TRIGGER_DEADLINE_SECONDS = 60
STRICT_RUN_TIMEOUT_SECONDS = 15
CRON_WAIT_DEADLINE_SECONDS = 77


def test_deployed_cron_times_map_from_utc_to_vietnam_across_year_boundary():
    crontab = (ROOT / "deploy" / "openmontage.cron").read_text(encoding="utf-8")
    schedule = {}
    for line in crontab.splitlines():
        match = re.match(r"^(\d+) (\d+) \* \* \* .*", line)
        if match:
            minute, hour = map(int, match.groups())
            schedule.setdefault((hour, minute), line)

    daily = datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)
    assert (daily.hour, daily.minute) in schedule
    assert daily.astimezone(VIETNAM) == datetime(2026, 1, 1, 6, 0, tzinfo=VIETNAM)

    for hour, minute, expected in (
        (2, 15, "09:15"),
        (7, 15, "14:15"),
        (14, 15, "21:15"),
    ):
        utc_slot = datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc)
        assert (hour, minute) in schedule
        local_slot = utc_slot.astimezone(VIETNAM)
        assert local_slot.date().isoformat() == "2026-01-01"
        assert local_slot.strftime("%H:%M") == expected


def _require_disposable_cron_container() -> tuple[str, str, str]:
    if os.geteuid() != 0:
        pytest.skip("real cron integration requires root in a disposable container")
    if not Path("/.dockerenv").is_file():
        pytest.skip("refusing to install any crontab outside a Docker container")
    try:
        ROOT.relative_to(Path("/work").resolve())
    except ValueError:
        pytest.skip("real cron integration requires the isolated checkout under /work")
    cron = shutil.which("cron")
    crontab = shutil.which("crontab")
    timeout = shutil.which("timeout")
    if not cron or not crontab or not timeout:
        pytest.skip("cron, crontab, and timeout are required in the disposable image")
    return str(cron), str(crontab), str(timeout)


def _stop_owned_cron(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    # The cron leader can exit before a just-forked job child does. Kill only
    # this test-owned session after the grace period to prevent orphaned work.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait(timeout=1)


def _safe_tail(path: Path, limit: int = 3000) -> str:
    if not path.is_file():
        return "<not created>"
    text = path.read_text(encoding="utf-8", errors="replace")[-limit:]
    return re.sub(
        r"(?im)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*)=(.*)",
        r"\1=<redacted>",
        text,
    )


def _failure_diagnostics(fixture: Path, started_at: float, cron_returncode: int | None) -> str:
    state_names = ("crontab-installed", "daemon.pid", "cron-tick.log", "trigger-started", "env-state", "strict.exit")
    states = {name: _safe_tail(fixture / name, 500) for name in state_names}
    logs = {
        name: _safe_tail(fixture / name)
        for name in ("cron.log", "strict.log", "daemon.stdout.log", "daemon.stderr.log")
    }
    return (
        f"fixture retained at {fixture}; elapsed={time.monotonic() - started_at:.1f}s; "
        f"cron_returncode={cron_returncode}; state={states}; bounded_logs={logs}"
    )


def test_real_cron_child_runs_strict_preflight_with_isolated_environment():
    cron, crontab_bin, timeout_bin = _require_disposable_cron_container()
    if subprocess.run(
        ["pgrep", "-x", "cron"], capture_output=True, timeout=1, check=False
    ).returncode == 0:
        pytest.skip("a cron daemon is already active; test owns only its daemon")

    original = subprocess.run(
        [crontab_bin, "-l"], capture_output=True, timeout=1, check=False
    )
    had_original = original.returncode == 0
    assert had_original or b"no crontab" in original.stderr.lower(), (
        "could not safely inspect disposable container root crontab"
    )

    fixture = Path(tempfile.mkdtemp(prefix="openmontage-cron-integration-", dir="/work"))
    runtime_root = fixture / "project"
    scripts = runtime_root / "scripts"
    scripts.mkdir(parents=True)
    (fixture / "runtime-tmp").mkdir()
    (runtime_root / ".env").write_text(
        "NEWS_MAX_SOURCE_AGE_HOURS=24\n", encoding="utf-8"
    )
    codex_home = fixture / "codex-profile"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        '{"OPENAI_API_KEY":"cron-validation-mock-only"}', encoding="utf-8"
    )
    (codex_home / "config.toml").write_text('model = "mock"\n', encoding="utf-8")
    shutil.copy2(
        ROOT / "scripts" / "run_strict_docker_publish.sh",
        scripts / "run_strict_docker_publish.sh",
    )
    (scripts / "run_strict_docker_publish.sh").chmod(0o755)

    trigger = fixture / "cron-trigger.sh"
    trigger.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$(/usr/bin/date -u +%FT%TZ)" > "$OM_CRON_TEST_ROOT/trigger-started"\n'
        'if [ -n "${NEWS_MAX_SOURCE_AGE_HOURS:-}" ]; then\n'
        '  printf present > "$OM_CRON_TEST_ROOT/env-state"\n'
        "else\n"
        '  printf missing > "$OM_CRON_TEST_ROOT/env-state"\n'
        "fi\n"
        'set +e\n'
        '"$OM_CRON_TEST_TIMEOUT" --signal=TERM --kill-after=1s 15s '
        '/bin/bash "$OM_CRON_TEST_ROOT/project/scripts/run_strict_docker_publish.sh" '
        '> "$OM_CRON_TEST_ROOT/strict.log" 2>&1\n'
        'status=$?\n'
        'printf "%s\\n" "$status" > "$OM_CRON_TEST_ROOT/strict.exit"\n',
        encoding="utf-8",
    )
    trigger.chmod(0o755)
    cron_probe = fixture / "cron-probe.sh"
    cron_probe.write_text(
        '#!/bin/bash\n/usr/bin/date -u +%FT%TZ >> "$OM_CRON_TEST_ROOT/cron-tick.log"\n',
        encoding="utf-8",
    )
    cron_probe.chmod(0o755)

    cron_lines = [
        "SHELL=/bin/bash",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        'MAILTO=""',
        f"OM_CRON_TEST_ROOT={fixture}",
        f"OM_CRON_TEST_TIMEOUT={timeout_bin}",
        "OPENMONTAGE_PYTHON=/usr/bin/python3",
        f"CODEX_HOME={codex_home}",
        f"TMP_ROOT={fixture / 'runtime-tmp'}",
        f"* * * * * /bin/bash {cron_probe} >> {fixture / 'cron.log'} 2>&1",
        f"* * * * * /bin/bash {trigger} >> {fixture / 'cron.log'} 2>&1",
        "",
    ]
    test_crontab_installed = False
    daemon: subprocess.Popen[bytes] | None = None
    daemon_stdout = (fixture / "daemon.stdout.log").open("wb")
    daemon_stderr = (fixture / "daemon.stderr.log").open("wb")
    started_at = time.monotonic()
    failure: Exception | None = None
    cleanup_failure: str | None = None

    try:
        # Set before invoking crontab so even a timed-out install attempt restores
        # the container's prior table rather than leaving this test entry behind.
        test_crontab_installed = True
        installed = subprocess.run(
            [crontab_bin, "-"], input="\n".join(cron_lines), text=True,
            capture_output=True, timeout=1, check=False,
        )
        if installed.returncode != 0:
            raise AssertionError(f"test crontab install failed: {installed.stderr}")
        observed = subprocess.run(
            [crontab_bin, "-l"], capture_output=True, timeout=1, check=False
        )
        if observed.returncode != 0 or str(trigger).encode() not in observed.stdout:
            raise AssertionError("installed disposable crontab does not contain the trigger")
        (fixture / "crontab-installed").write_text("verified", encoding="utf-8")

        # The test value is only in the cron daemon's allowlisted environment,
        # not in the crontab. This verifies daemon-to-job inheritance directly.
        daemon_env = {
            "HOME": "/root",
            "LOGNAME": "root",
            "SHELL": "/bin/bash",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "NEWS_MAX_SOURCE_AGE_HOURS": "24",
        }
        daemon = subprocess.Popen(
            [cron, "-f"], env=daemon_env, stdout=daemon_stdout,
            stderr=daemon_stderr, start_new_session=True,
        )
        (fixture / "daemon.pid").write_text(str(daemon.pid), encoding="utf-8")
        daemon_started = time.monotonic()
        trigger_deadline = daemon_started + CRON_TRIGGER_DEADLINE_SECONDS
        hard_deadline = daemon_started + CRON_WAIT_DEADLINE_SECONDS
        exit_file = fixture / "strict.exit"
        while time.monotonic() < hard_deadline:
            if daemon.poll() is not None:
                raise AssertionError(f"test-owned cron exited early with {daemon.returncode}")
            if exit_file.is_file():
                break
            if time.monotonic() >= trigger_deadline and not (fixture / "trigger-started").exists():
                raise AssertionError("cron did not start the trigger within 60 seconds")
            time.sleep(0.1)
        if not exit_file.is_file():
            raise AssertionError("strict preflight exceeded the bounded 15-second invocation window")

        env_state = (fixture / "env-state").read_text(encoding="utf-8")
        strict_status = int(exit_file.read_text(encoding="utf-8").strip())
        strict_log = (fixture / "strict.log").read_text(encoding="utf-8", errors="replace")
        if env_state != "missing":
            raise AssertionError("cron fixture unexpectedly passed NEWS_MAX_SOURCE_AGE_HOURS to its child")
        if "preflight OK" not in strict_log:
            raise AssertionError("strict .env fallback did not pass freshness preflight")
        if "publish schedule missing" not in strict_log:
            raise AssertionError("strict runner did not stop at the isolated missing-schedule boundary")
        if "NEWS_MAX_SOURCE_AGE_HOURS is required" in strict_log:
            raise AssertionError("strict runner rejected the valid isolated .env fallback")
        if strict_status == 0 or "generation attempt" in strict_log:
            raise AssertionError("strict runner did not fail closed before generation")
        if (runtime_root / "projects").exists():
            raise AssertionError("strict runner unexpectedly created generation projects")
        if not (fixture / "cron-tick.log").is_file():
            raise AssertionError("independent harmless cron boundary probe did not fire")
    except Exception as exc:
        failure = exc
    finally:
        if daemon is not None:
            try:
                _stop_owned_cron(daemon)
            except Exception as exc:
                cleanup_failure = f"cron cleanup failed: {exc}"
        daemon_stdout.close()
        daemon_stderr.close()
        if test_crontab_installed:
            try:
                if had_original:
                    restored = subprocess.run(
                        [crontab_bin, "-"], input=original.stdout,
                        capture_output=True, timeout=1, check=False,
                    )
                    if restored.returncode != 0:
                        raise RuntimeError("failed to restore disposable container root crontab")
                else:
                    subprocess.run(
                        [crontab_bin, "-r"], capture_output=True,
                        timeout=1, check=False,
                    )
            except Exception as exc:
                cleanup_failure = f"crontab restore failed: {exc}"

    if failure is not None or cleanup_failure is not None:
        report = _failure_diagnostics(
            fixture, started_at, daemon.returncode if daemon is not None else None
        )
        raise AssertionError(
            f"real-cron integration failed: {failure or cleanup_failure}; "
            f"{cleanup_failure or ''}; {report}"
        ) from failure

    shutil.rmtree(fixture, ignore_errors=True)
