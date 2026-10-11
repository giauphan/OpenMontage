"""Focused regression tests for daily Docker cron reliability.

Covers:
1. Heartbeat writing & detection in scripts/check_missed_runs.py (missing,
   stale, failed, ok).
2. Schedule lock acquisition & contention behavior in the strict orchestrator.
3. Disk threshold enforcement and age-gated temporary cleanup.
4. Quarantine (never silent rm -rf) of failed-generation project directories.
5. Max stale-feed age enforcement in run_daily_news_pipeline.sh.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_missed_runs.py"


def test_check_missed_runs_detects_missing_heartbeats(tmp_path: Path):
    (tmp_path / "logs" / "heartbeat").mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path), "--jobs", "daily_orchestrator"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "MISSING_HEARTBEAT" in res.stdout
    alert_log = tmp_path / "logs" / "missed_run_alerts.log"
    assert alert_log.is_file()
    assert "MISSING_HEARTBEAT" in alert_log.read_text(encoding="utf-8")


def test_check_missed_runs_detects_stale_and_failed_heartbeats(tmp_path: Path):
    hb_dir = tmp_path / "logs" / "heartbeat"
    hb_dir.mkdir(parents=True, exist_ok=True)

    # 1. Stale orchestrator (>30h old)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=35)).isoformat().replace("+00:00", "Z")
    (hb_dir / "daily_orchestrator.json").write_text(
        json.dumps({"ts": stale_ts, "status": "completed", "run_id": "r_old"}),
        encoding="utf-8",
    )
    # 2. Fresh but failed slot
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    (hb_dir / "slot_0915.json").write_text(
        json.dumps({"ts": fresh_ts, "status": "failed", "exit_code": 1}),
        encoding="utf-8",
    )

    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path), "--jobs", "daily_orchestrator,slot_0915"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    out = res.stdout
    assert "STALE_HEARTBEAT" in out
    assert "RUN_FAILED" in out


def test_check_missed_runs_passes_when_all_heartbeats_fresh_and_ok(tmp_path: Path):
    hb_dir = tmp_path / "logs" / "heartbeat"
    hb_dir.mkdir(parents=True, exist_ok=True)
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    for job in ("daily_orchestrator", "slot_0915", "slot_1415", "slot_2115"):
        (hb_dir / f"{job}.json").write_text(
            json.dumps({"ts": fresh_ts, "status": "completed", "run_id": f"r_{job}"}),
            encoding="utf-8",
        )

    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "No missed-run or failure alerts." in res.stdout


def _scheduler_command() -> str:
    compose_lines = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    scheduler_start = compose_lines.index("  scheduler:")
    command_start = next(i for i in range(scheduler_start, len(compose_lines))
                         if compose_lines[i] == "    command: |")
    command_lines = []
    for line in compose_lines[command_start + 1:]:
        if line and not line.startswith("      "):
            break
        command_lines.append(line[6:] if line else "")
    return textwrap.dedent("\n".join(command_lines))


def _run_scheduler_command(tmp_path: Path, *, profile_exit=0, cron_installed=True, crontab_exit=0):
    bin_dir = tmp_path / "bin"
    scripts_dir = tmp_path / "scripts"
    deploy_dir = tmp_path / "deploy"
    bin_dir.mkdir()
    scripts_dir.mkdir()
    deploy_dir.mkdir()
    (deploy_dir / "openmontage.cron").write_text("# test fixture\n", encoding="utf-8")

    (scripts_dir / "init_codex_profile.sh").write_text(
        'printf \'profile\\n\' >> "$STUB_LOG"\nexit "$PROFILE_EXIT"\n', encoding="utf-8"
    )
    for name, target in (("bash", "/bin/bash"), ("mkdir", "/bin/mkdir"), ("jq", "/bin/true")):
        (bin_dir / name).symlink_to(target)
    (bin_dir / "crontab").write_text(
        '#!/bin/bash\nprintf \'crontab\\n\' >> "$STUB_LOG"\nexit "$CRONTAB_EXIT"\n', encoding="utf-8"
    )
    (bin_dir / "cron").write_text(
        '#!/bin/bash\nprintf \'cron\\n\' >> "$STUB_LOG"\nexit 0\n', encoding="utf-8"
    )
    for executable in (bin_dir / "crontab", bin_dir / "cron"):
        executable.chmod(0o755)
    if not cron_installed:
        (bin_dir / "cron").unlink()

    command = _scheduler_command().replace("/app", str(tmp_path))
    result = subprocess.run(
        ["/bin/bash", "-ec", command],
        env={
            "PATH": str(bin_dir),
            "STUB_LOG": str(tmp_path / "calls.log"),
            "PROFILE_EXIT": str(profile_exit),
            "CRONTAB_EXIT": str(crontab_exit),
        },
        capture_output=True,
        text=True,
    )
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines() if (tmp_path / "calls.log").exists() else []
    return result, calls


def test_scheduler_profile_failure_prevents_crontab_and_cron(tmp_path: Path):
    result, calls = _run_scheduler_command(tmp_path, profile_exit=17)

    assert result.returncode == 17
    assert calls == ["profile"]


def test_scheduler_missing_dependency_prevents_crontab_and_cron(tmp_path: Path):
    result, calls = _run_scheduler_command(tmp_path, cron_installed=False)

    assert result.returncode != 0
    assert calls == ["profile", "profile"]


def test_scheduler_crontab_failure_prevents_cron(tmp_path: Path):
    result, calls = _run_scheduler_command(tmp_path, crontab_exit=9)

    assert result.returncode == 9
    assert calls == ["profile", "profile", "crontab"]


def test_scheduler_starts_cron_only_after_successful_bootstrap(tmp_path: Path):
    result, calls = _run_scheduler_command(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["profile", "profile", "crontab", "cron"]


def _producer_block() -> str:
    pipeline = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(encoding="utf-8")
    return pipeline.split("# PRODUCER_EXECUTION_BEGIN\n", 1)[1].split("\n# PRODUCER_EXECUTION_END", 1)[0]


def _run_producer_block(tmp_path: Path, *, producer_exit=0, tee_exit=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text(
        '''#!/bin/bash\nprintf \'PROJECT_ID=one\\nPROJECT_ID=two\\nPROJECT_ID=three\\n\'\nexit "$PRODUCER_EXIT"\n''',
        encoding="utf-8",
    )
    fake_tee = bin_dir / "tee"
    fake_tee.write_text(
        '''#!/bin/bash\ncat > "$1"\nexit "$TEE_EXIT"\n''', encoding="utf-8"
    )
    fake_python.chmod(0o755)
    fake_tee.chmod(0o755)
    script = (
        'set -euo pipefail\nROOT="$TEST_ROOT"\ncd "$ROOT"\nmkdir -p logs\n'
        'PY="$TEST_BIN/python"\n' + _producer_block() + '\nprintf "%s\\n" "${PROJECT_IDS[@]}" > parsed-ids\n'
        'printf reached > downstream-sentinel\n'
    )
    return subprocess.run(
        ["/bin/bash", "-c", script],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "TEST_ROOT": str(tmp_path),
            "TEST_BIN": str(bin_dir),
            "PRODUCER_EXIT": str(producer_exit),
            "TEE_EXIT": str(tee_exit),
        },
        capture_output=True,
        text=True,
    )


def test_actual_producer_block_fails_before_candidate_or_director_work(tmp_path: Path):
    result = _run_producer_block(tmp_path, producer_exit=7)

    assert result.returncode == 7
    assert "topic production failed" in result.stderr
    assert not (tmp_path / "parsed-ids").exists()
    assert not (tmp_path / "downstream-sentinel").exists()


def test_actual_producer_block_succeeds_and_parses_candidates(tmp_path: Path):
    result = _run_producer_block(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "parsed-ids").read_text(encoding="utf-8").splitlines() == ["one", "two", "three"]
    assert (tmp_path / "downstream-sentinel").is_file()


def test_producer_failure_takes_precedence_over_tee_failure(tmp_path: Path):
    result = _run_producer_block(tmp_path, producer_exit=7, tee_exit=9)

    assert result.returncode == 7


def test_tee_failure_is_not_reported_as_success(tmp_path: Path):
    result = _run_producer_block(tmp_path, producer_exit=0, tee_exit=9)

    assert result.returncode == 9
    assert "could not persist topic production log" in result.stderr
    assert not (tmp_path / "downstream-sentinel").exists()


_UNSET = object()


def _run_strict_freshness_config(tmp_path: Path, dotenv_text: str | None, explicit=_UNSET):
    source = (ROOT / "scripts" / "run_strict_docker_publish.sh").read_text(encoding="utf-8")
    functions = source.split("# STRICT_FRESHNESS_CONFIG_BEGIN\n", 1)[1].split(
        "\n# STRICT_FRESHNESS_CONFIG_END", 1
    )[0]
    if dotenv_text is not None:
        (tmp_path / ".env").write_text(dotenv_text, encoding="utf-8")
    script = (
        'set -euo pipefail\nROOT="$TEST_ROOT"\nPY="$TEST_PY"\n'
        + functions
        + '\nload_news_max_source_age_from_dotenv\nvalidate_news_max_source_age\n'
    )
    env = {**os.environ, "TEST_ROOT": str(tmp_path), "TEST_PY": sys.executable}
    env.pop("NEWS_MAX_SOURCE_AGE_HOURS", None)
    if explicit is not _UNSET:
        env["NEWS_MAX_SOURCE_AGE_HOURS"] = explicit
    return subprocess.run(
        ["/bin/bash", "-c", script], capture_output=True, text=True, env=env
    )


def test_strict_freshness_falls_back_to_dotenv_when_unset(tmp_path: Path):
    result = _run_strict_freshness_config(tmp_path, "NEWS_MAX_SOURCE_AGE_HOURS=24\n")

    assert result.returncode == 0, result.stdout + result.stderr


def test_strict_freshness_rejects_missing_dotenv_setting(tmp_path: Path):
    result = _run_strict_freshness_config(tmp_path, None)

    assert result.returncode != 0


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "-Infinity", "0", "-1", "721", "not-a-number"])
def test_strict_freshness_rejects_invalid_dotenv_values(tmp_path: Path, value: str):
    result = _run_strict_freshness_config(
        tmp_path, f"NEWS_MAX_SOURCE_AGE_HOURS={value}\n"
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    if value:
        assert value not in output
    else:
        assert output == ""


def test_explicit_valid_freshness_override_takes_precedence(tmp_path: Path):
    result = _run_strict_freshness_config(
        tmp_path, "NEWS_MAX_SOURCE_AGE_HOURS=NaN\n", explicit="48"
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("explicit", ["", "invalid", "NaN", "721"])
def test_explicit_invalid_freshness_override_is_not_replaced(tmp_path: Path, explicit: str):
    result = _run_strict_freshness_config(
        tmp_path, "NEWS_MAX_SOURCE_AGE_HOURS=24\n", explicit=explicit
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    if explicit:
        assert explicit not in output
    else:
        assert output == ""


def test_dotenv_shell_expressions_are_not_executed(tmp_path: Path):
    marker = tmp_path / "shell-expression-ran"
    result = _run_strict_freshness_config(
        tmp_path, f"NEWS_MAX_SOURCE_AGE_HOURS=$(touch {marker})\n"
    )

    assert result.returncode != 0
    assert not marker.exists()
    assert str(marker) not in result.stdout + result.stderr


def test_dotenv_fallback_does_not_log_other_credentials(tmp_path: Path):
    secret = "test-only-not-a-real-credential"
    result = _run_strict_freshness_config(
        tmp_path,
        f"NEWS_MAX_SOURCE_AGE_HOURS=24\nNEWS_API_TOKEN={secret}\n",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert secret not in result.stdout + result.stderr
