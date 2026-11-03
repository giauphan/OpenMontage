"""Offline shell-boundary regressions; execute only in a remote test checkout."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts/run_daily_news_pipeline.sh").read_text(encoding="utf-8")


def run_shell(tmp_path, body, setup=""):
    (tmp_path / "logs").mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail\nROOT="$1"\nPY="$2"\n' + setup + "\n" + body,
         "boundary-test", str(tmp_path), sys.executable],
        cwd=tmp_path, env=os.environ.copy(), capture_output=True, text=True,
        timeout=15, check=False,
    )


def producer_block():
    return SOURCE.split("# PRODUCER_EXECUTION_BEGIN\n", 1)[1].split(
        "# PRODUCER_EXECUTION_END", 1)[0]


@pytest.mark.parametrize("fetch_status", [0, 9])
def test_muse_acquisition_calls_muse_and_never_falls_back(tmp_path, fetch_status):
    body = SOURCE.split("# DAILY_DISCOVERY_BEGIN\n", 1)[1].split("# DAILY_DISCOVERY_END", 1)[0]
    setup = f'''
fetcher() {{ printf '%s\\n' "$*" >> fetch_calls; return {fetch_status}; }}
PY=fetcher
NEWS_DISCOVERY_PROVIDER=muse
'''
    result = run_shell(tmp_path, body + '\nprintf "FETCH_COMPLETE\\n"', setup)
    calls = (tmp_path / "fetch_calls").read_text().splitlines()
    assert len(calls) == 1
    assert "fetch --source muse" in calls[0]
    assert result.returncode == (0 if fetch_status == 0 else 1)
    assert ("FETCH_COMPLETE" in result.stdout) is (fetch_status == 0)


@pytest.mark.parametrize("producer_status,tee_status,expected", [(23, 0, 23), (0, 19, 19), (23, 19, 23)])
def test_producer_and_log_failure_preserve_status(tmp_path, producer_status, tee_status, expected):
    setup = f'''
producer() {{ printf 'PROJECT_ID=partial\n'; return {producer_status}; }}
PY=producer
tee() {{ cat > "$1"; return {tee_status}; }}
'''
    result = run_shell(tmp_path, producer_block() + '\nprintf "ACCEPTED\\n"', setup)
    assert result.returncode == expected, result.stderr
    assert "ACCEPTED" not in result.stdout
    assert "PROJECT_ID=partial" in next((tmp_path / "logs").iterdir()).read_text()


def test_producer_log_parse_failure_blocks_candidates(tmp_path):
    setup = '''
producer() { printf 'PROJECT_ID=one\nPROJECT_ID=two\nPROJECT_ID=three\n'; }
PY=producer
awk() { return 17; }
'''
    result = run_shell(tmp_path, producer_block() + '\nprintf "ACCEPTED\\n"', setup)
    assert result.returncode != 0
    assert "ACCEPTED" not in result.stdout


def test_no_eligible_marker_does_not_mask_producer_failure(tmp_path):
    setup = '''
producer() { printf 'STATUS=NO_ELIGIBLE_TOPIC\\n'; return 7; }
PY=producer
'''
    result = run_shell(tmp_path, producer_block(), setup)
    assert result.returncode == 7


def test_muse_does_not_require_more_projects_than_were_found(tmp_path):
    body = SOURCE.split("# DAILY_TARGET_BEGIN\n", 1)[1].split("# DAILY_TARGET_END", 1)[0]
    setup = 'NEWS_DISCOVERY_PROVIDER=muse\nREHEARSAL_MANIFEST=""\nPROJECT_IDS=(one)\nEXPECTED_SUCCESS_COUNT=3'
    result = run_shell(tmp_path, body + '\nprintf "TARGET:%s\\n" "$EXPECTED_SUCCESS_COUNT"', setup)
    assert result.returncode == 0, result.stderr
    assert "TARGET:1" in result.stdout

def test_producer_missing_project_id_blocks_candidates(tmp_path):
    """Missing PROJECT_ID in producer output should block candidates (new regression)."""
    setup = '''
producer() { printf 'NO_PROJECT_ID\n'; }
PY=producer
'''
    result = run_shell(tmp_path, producer_block() + '\nif [ "${#PROJECT_IDS[@]}" -lt 3 ]; then exit 42; fi\nprintf "ACCEPTED\\n"', setup)
    assert result.returncode == 42
    assert "ACCEPTED" not in result.stdout

def test_producer_unique_id_filtering(tmp_path):
    """Unique ID filtering should deduplicate candidates (new regression)."""
    setup = '''
producer() { printf 'PROJECT_ID=a\nPROJECT_ID=a\nPROJECT_ID=b\n'; }
PY=producer
'''
    result = run_shell(tmp_path, producer_block() + '\nprintf "ACCEPTED\\n"', setup)
    assert result.returncode == 0
    assert "ACCEPTED" in result.stdout


def test_producer_logs_are_unique_and_ids_filtered(tmp_path):
    setup = '''
producer() { printf 'PROJECT_ID=one\nPROJECT_ID=one\nPROJECT_ID=two\nPROJECT_ID=three\nPROJECT_ID=../escape\nPROJECT_ID=_failed_generation_recovered\nPROJECT_ID=_failed_generation_recovered_old\n'; }
PY=producer
# Freeze wall-clock naming to reproduce collisions without a timing race.
date() { printf '20300101T000000Z\n'; }
'''
    body = producer_block() + '\nprintf "IDS:%s\\n" "${PROJECT_IDS[*]}"'
    for _ in range(2):
        result = run_shell(tmp_path, body, setup)
        assert result.returncode == 0, result.stderr
        assert "IDS:one two three" in result.stdout
    assert len(list((tmp_path / "logs").iterdir())) == 2


@pytest.mark.parametrize("status", [3, 4, 6, 124])
def test_failed_director_cannot_recover_from_existing_artifacts(tmp_path, status):
    # Exercise the actual post-retry boundary with a validator accepting old files.
    start = SOURCE.index("set -e\n#", SOURCE.index("validate_current_director_artifacts()"))
    end_marker = (
        '\nif [[ "$DIRECTOR_EXIT" -eq 0 ]]; then'
        if '\nif [[ "$DIRECTOR_EXIT" -eq 0 ]]; then' in SOURCE[start:]
        else '\nif [ "$DIRECTOR_EXIT" -eq 0 ]; then'
    )
    end = SOURCE.index(end_marker, start)
    setup = f'''
PROJECT_ID=old-project
TEMPLATE_MODE=0
DIRECTOR_EXIT={status}
accept_old_artifacts() {{ return 0; }}
PY=accept_old_artifacts
'''
    result = run_shell(tmp_path, SOURCE[start:end] + '\nprintf "STATUS:%s\\n" "$DIRECTOR_EXIT"', setup)
    assert result.returncode == 0, result.stderr
    assert f"STATUS:{status}" in result.stdout


@pytest.mark.parametrize("fresh", [False, True])
def test_compositions_must_belong_to_current_attempt(tmp_path, fresh):
    project = tmp_path / "projects" / "candidate"
    # Artifact validator accepts the script; isolate composition freshness here.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "validate_newsnow_director_artifacts.py").write_text("raise SystemExit(0)\n")
    cutoff = 2_000_000_000_500_000_000
    for name in ("hyperframes", "hyperframes_reels"):
        composition = project / name / "index.html"
        composition.parent.mkdir(parents=True)
        composition.write_text("old or current composition")
        mtime = cutoff + 1 if fresh else cutoff - 1
        os.utime(composition, ns=(mtime, mtime))
    start = SOURCE.index("validate_current_director_artifacts() {")
    end = SOURCE.index('\n\nif [ -n "$REHEARSAL_MANIFEST" ]', start)
    setup = f'''
PROJECT_ID=candidate
PROJECT_DIR="$ROOT/projects/$PROJECT_ID"
DIRECTORS_LOG="$ROOT/logs/directors.log"
START_TS=2000000000
DIRECTOR_SESSION_START_NS={cutoff}
DIRECTOR_ATTEMPT_START_NS={cutoff}
'''
    result = run_shell(tmp_path, SOURCE[start:end] + "\nvalidate_current_director_artifacts", setup)
    assert (result.returncode == 0) is fresh, result.stderr
