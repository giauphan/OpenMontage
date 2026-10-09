"""Strict contract coverage; these tests never execute the production entrypoint."""
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.daily_news_acceptance_loop import (
    AcceptanceLoop, MARKER_NAME, MARKER_VALUE, REPORT_REL, SUITE, atomic_json,
    execute, source_fingerprint, verify_rehearsals,
)


def make_run(tmp_path, run_index, ids_override=None):
    root = tmp_path / f"isolated-{run_index}"
    (root / "logs").mkdir(parents=True)
    (root / MARKER_NAME).write_text(json.dumps(MARKER_VALUE), encoding="utf-8")
    ids = ids_override or [f"fixture-{run_index}-{i}" for i in range(1, 4)]
    evidence = {}
    for project_id in ids:
        name = f"logs/{project_id}.log"
        (root / name).write_text(f"actual shell log for {project_id}\n", encoding="utf-8")
        evidence[project_id] = [name]
    report = {
        "test_only": True, "shell_executed": True, "publication_enabled": False,
        "n5_complete": False, "requested_project_ids": ids,
        "successful_project_ids": ids, "failed_project_ids": [],
        "quarantined_project_ids": [], "terminal_exit_status": 0,
        "terminal_stage": "completed", "stage_evidence_paths": evidence,
    }
    report_path = root / REPORT_REL
    report_path.write_text(json.dumps(report), encoding="utf-8")
    failure = root / "logs/failure-observation.log"
    recovery = root / "logs/recovery-observation.log"
    failure.write_text("independent negative-path evidence\n", encoding="utf-8")
    recovery.write_text("independent recovery evidence\n", encoding="utf-8")
    manifest = tmp_path / f"manifest-{run_index}.json"
    manifest.write_text(json.dumps({"isolated_root": str(root), "report": str(report_path),
                                    "failure_evidence": str(failure.relative_to(root)),
                                    "recovery_evidence": str(recovery.relative_to(root))}), encoding="utf-8")
    return manifest, root, report_path


def test_requires_three_distinct_complete_full_shell_runs(tmp_path):
    entries = [make_run(tmp_path, n) for n in range(3)]
    ok, records, inputs = verify_rehearsals([item[0] for item in entries])
    assert ok and len(records) == 3
    assert all(any(path.name == "failure-observation.log" for path in inputs) for _ in [0])
    assert not verify_rehearsals([item[0] for item in entries[:2]])[0]
    assert not verify_rehearsals([entries[0][0], entries[0][0], entries[2][0]])[0]


def test_rejects_identical_requested_id_sets_across_roots(tmp_path):
    ids = ["shared-project-1", "shared-project-2", "shared-project-3"]
    entries = [make_run(tmp_path, n, ids) for n in range(3)]
    assert not verify_rehearsals([entry[0] for entry in entries])[0]


def test_rejects_replayed_report_and_evidence_across_roots(tmp_path):
    entries = [make_run(tmp_path, n) for n in range(3)]
    canonical = json.loads(entries[0][2].read_text(encoding="utf-8"))
    for manifest, root, report_path in entries[1:]:
        report_path.write_text(json.dumps(canonical), encoding="utf-8")
        for index in range(1, 4):
            (root / f"logs/fixture-0-{index}.log").write_text(
                f"actual shell log for fixture-0-{index}\n", encoding="utf-8")
        (root / "logs/failure-observation.log").write_text("independent negative-path evidence\n", encoding="utf-8")
        (root / "logs/recovery-observation.log").write_text("independent recovery evidence\n", encoding="utf-8")
    assert not verify_rehearsals([entry[0] for entry in entries])[0]


@pytest.mark.parametrize("mutation", [
    lambda report: report.update(terminal_exit_status=1),
    lambda report: report.update(publication_enabled=True),
    lambda report: report.update(shell_executed=False),
    lambda report: report.update(successful_project_ids=[]),
    lambda report: report.update(failed_project_ids=["fixture"]),
    lambda report: report.update(quarantined_project_ids=["fixture"]),
    lambda report: report.update(terminal_stage="incomplete_rehearsal"),
])
def test_rejects_reports_not_full_success(tmp_path, mutation):
    entries = [make_run(tmp_path, n) for n in range(3)]
    path = entries[1][2]
    report = json.loads(path.read_text(encoding="utf-8"))
    mutation(report)
    path.write_text(json.dumps(report), encoding="utf-8")
    assert not verify_rehearsals([entry[0] for entry in entries])[0]


def test_symlink_manifest_blocks_evidence_but_still_runs_suite(tmp_path, monkeypatch):
    entries = [make_run(tmp_path, n) for n in range(3)]
    symlink_manifest = tmp_path / "symlink-manifest.json"
    symlink_manifest.symlink_to(entries[0][0])
    calls = []

    def fake_execute(argv, cwd, log, timeout, junit):
        calls.append(argv)
        return _fake_suite_result(argv, cwd, log, timeout, junit)

    monkeypatch.setattr("lib.daily_news_acceptance_loop.execute", fake_execute)
    state_dir = tmp_path / "state"
    manifests = [symlink_manifest, entries[1][0], entries[2][0]]
    assert AcceptanceLoop(ROOT, state_dir, manifests, 1, 30, 10).run() == 2
    assert len(calls) == 1
    report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked_missing_rehearsal_inputs"
    assert report["plan_complete"] is False


def test_rejects_missing_or_unsafe_evidence_and_bad_marker(tmp_path):
    entries = [make_run(tmp_path, n) for n in range(3)]
    manifest, root, _report_path = entries[0]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["failure_evidence"] = "logs/not-real.log"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert not verify_rehearsals([entry[0] for entry in entries])[0]
    data["failure_evidence"] = "../outside.log"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert not verify_rehearsals([entry[0] for entry in entries])[0]
    data["failure_evidence"] = "logs/failure-observation.log"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    (root / MARKER_NAME).write_text("{}", encoding="utf-8")
    assert not verify_rehearsals([entry[0] for entry in entries])[0]


def test_rejects_unsafe_project_ids(tmp_path):
    entries = [make_run(tmp_path, n) for n in range(3)]
    path = entries[0][2]
    report = json.loads(path.read_text(encoding="utf-8"))
    report["requested_project_ids"][0] = "../unsafe"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert not verify_rehearsals([entry[0] for entry in entries])[0]


def test_source_fingerprint_covers_all_fixed_suite_and_controller_sources():
    hashes = source_fingerprint(ROOT, [])
    assert str(ROOT / "lib/daily_news_acceptance_loop.py") in hashes
    assert str(ROOT / "scripts/write_daily_news_rehearsal_report.py") in hashes
    assert all((ROOT / path).is_file() and str(ROOT / path) in hashes for path in SUITE)
    assert not any(".pyc" in path or "__pycache__" in path for path in hashes)


def test_malformed_state_fails_closed_without_overwriting(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "state.json"
    state_file.write_text("{bad", encoding="utf-8")
    before = state_file.read_bytes()
    loop = AcceptanceLoop(ROOT, state_dir, [], 1, 30, 10)
    assert loop.run() == 2
    assert state_file.read_bytes() == before
    report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked_malformed_state"
    assert report["plan_complete"] is False


def test_finite_limits_are_required():
    with pytest.raises(ValueError):
        AcceptanceLoop(ROOT, Path("unused"), [], 1, math.inf, 10)
    with pytest.raises(ValueError):
        AcceptanceLoop(ROOT, Path("unused"), [], 3, 10, 5)


def test_subprocess_timeout_kills_process_group_children(tmp_path):
    marker = tmp_path / "child-done"
    child = "import time; time.sleep(2); open(r'" + str(marker) + "','w').close()"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(10)"
    result = execute([sys.executable, "-c", parent], tmp_path, tmp_path / "run.log", 0.1, tmp_path / "run.xml")
    assert result["outcome"] == "timeout"
    assert not marker.exists()


def test_lock_prevents_overlap(tmp_path):
    import fcntl
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    lock = (state_dir / "controller.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert AcceptanceLoop(ROOT, state_dir, [], 1, 10, 5).run() == 73
    finally:
        lock.close()


def test_junit_policy_rejects_zero_tests_and_any_skip(tmp_path):
    for index, (xml, expected) in enumerate((
        ('<testsuite tests="0" failures="0" errors="0" skipped="0"/>', "failed"),
        ('<testsuite tests="2" failures="0" errors="0" skipped="1"/>', "failed"),
        ('<testsuite tests="2" failures="0" errors="0" skipped="0"/>', "passed"),
    )):
        log, junit = tmp_path / f"suite-{index}.log", tmp_path / f"suite-{index}.xml"
        writer = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(" + repr(xml) + ")"
        result = execute([sys.executable, "-c", writer, str(junit)], tmp_path, log, 5, junit)
        assert result["outcome"] == expected


def test_stale_fingerprint_does_not_reuse_old_attempt(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    atomic_json(state_dir / "state.json", {"schema": 2, "attempts": [], "total_attempt_count": 0,
                "fingerprint": {"old-source": "0" * 64}, "started_at": time.time(),
                "superseded_attempts": [], "superseded_fingerprints": []})
    calls = []

    def fake_execute(argv, cwd, log, timeout, junit):
        calls.append(argv)
        log.write_text("accepted", encoding="utf-8")
        junit.write_text('<testsuite tests="4" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
        from lib.daily_news_acceptance_loop import sha256
        return {"argv": argv, "outcome": "passed", "exit_code": 0, "log": str(log),
                "log_sha256": sha256(log), "junit": str(junit), "junit_sha256": sha256(junit),
                "junit_summary": {"tests": 4, "failures": 0, "errors": 0, "skipped": 0}}

    monkeypatch.setattr("lib.daily_news_acceptance_loop.execute", fake_execute)
    assert AcceptanceLoop(ROOT, state_dir, [], 1, 30, 10).run() == 2
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert len(calls) == 1 and state["attempts"][0]["status"] == "passed"
    assert state["superseded_fingerprints"] == [{"old-source": "0" * 64}]


def test_state_directory_symlink_is_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        AcceptanceLoop(ROOT, alias, [], 1, 30, 10).run()


def test_valid_attempt_reparses_junit_and_checks_fixed_argv(tmp_path):
    state_dir = tmp_path / "state"
    attempt_dir = state_dir / "attempt-unique"
    attempt_dir.mkdir(parents=True)
    loop = AcceptanceLoop(ROOT, state_dir, [], 1, 30, 10)
    log, junit = attempt_dir / "acceptance.log", attempt_dir / "junit.xml"
    log.write_text("suite output", encoding="utf-8")
    junit.write_text('<testsuite tests="2" failures="0" errors="0" skipped="1"/>', encoding="utf-8")
    from lib.daily_news_acceptance_loop import sha256
    fingerprint = {"source": "frozen"}
    attempt = {"status": "passed", "fingerprint": fingerprint, "exit_code": 0,
               "directory": str(attempt_dir), "log": str(log), "junit": str(junit),
               "log_sha256": sha256(log), "junit_sha256": sha256(junit),
               "junit_summary": {"tests": 2, "failures": 0, "errors": 0, "skipped": 0},
               "argv": [sys.executable, "-m", "pytest", "-q", "--strict-markers", "-o", "addopts=",
                        "--junitxml", str(junit), *SUITE]}
    assert not loop._valid_attempt(attempt, fingerprint)
    attempt["junit_summary"]["skipped"] = 1
    attempt["argv"][0] = "arbitrary-python"
    assert not loop._valid_attempt(attempt, fingerprint)


def test_sigterm_kills_suite_process_group_and_persists_interruption(tmp_path):
    fake_pytest = tmp_path / "fake"
    fake_pytest.mkdir()
    child_pid_file = tmp_path / "child.pid"
    child_done = tmp_path / "child.done"
    child_code = f"import time; time.sleep(30); open({str(child_done)!r}, 'w').close()"
    (fake_pytest / "pytest.py").write_text(
        "import pathlib,subprocess,sys,time\n"
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(subprocess.Popen([sys.executable,'-c',{child_code!r}]).pid))\n"
        "time.sleep(30)\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    controller_code = (
        "from pathlib import Path; from lib.daily_news_acceptance_loop import AcceptanceLoop; "
        f"raise SystemExit(AcceptanceLoop(Path({str(ROOT)!r}), Path({str(state_dir)!r}), [], 2, 60, 50).run())"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(fake_pytest), str(ROOT)))
    controller = subprocess.Popen([sys.executable, "-c", controller_code], cwd=ROOT, env=env)
    try:
        deadline = time.monotonic() + 10
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert child_pid_file.exists(), "fake pytest child did not start"
        os.kill(controller.pid, signal.SIGTERM)
        assert controller.wait(timeout=10) == 130
        state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
        assert state["total_attempt_count"] == 1
        assert len(state["attempts"]) == 1
        assert state["attempts"][-1]["status"] == "runner_interrupted"
        time.sleep(0.2)
        assert not child_done.exists()
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=5)
        if child_pid_file.exists():
            try:
                os.kill(int(child_pid_file.read_text(encoding="utf-8")), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def test_state_lock_and_subprocess_outputs_reject_symlinks(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    target = tmp_path / "target"
    target.write_text("", encoding="utf-8")
    (state_dir / "controller.lock").symlink_to(target)
    with pytest.raises(OSError):
        AcceptanceLoop(ROOT, state_dir, [], 1, 10, 5).run()
    log, junit = tmp_path / "log", tmp_path / "junit.xml"
    log.symlink_to(target)
    with pytest.raises(ValueError, match="nonsymlink"):
        execute([sys.executable, "-c", "pass"], tmp_path, log, 5, junit)


def _fake_suite_result(argv, _cwd, log, _timeout, junit, outcome="passed"):
    from lib.daily_news_acceptance_loop import sha256
    log.write_text(f"{outcome}\n", encoding="utf-8")
    code = 0 if outcome == "passed" else 124
    if outcome == "passed":
        junit.write_text('<testsuite tests="5" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
    return {"argv": argv, "outcome": outcome, "exit_code": code, "log": str(log),
            "log_sha256": sha256(log), "junit": str(junit),
            "junit_sha256": sha256(junit) if junit.exists() else None,
            "junit_summary": {"tests": 5 if outcome == "passed" else 0, "failures": 0,
                              "errors": 0, "skipped": 0}}


def test_mutation_between_verification_and_fingerprint_blocks_evidence_pass(tmp_path, monkeypatch):
    import lib.daily_news_acceptance_loop as loop_module

    entries = [make_run(tmp_path, n) for n in range(3)]
    report_path = entries[0][2]
    real_fingerprint = loop_module.source_fingerprint
    mutated = False

    def mutate_after_verify(root, inputs):
        nonlocal mutated
        if not mutated:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["post_snapshot_mutation"] = True
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            mutated = True
        return real_fingerprint(root, inputs)

    monkeypatch.setattr(loop_module, "source_fingerprint", mutate_after_verify)
    monkeypatch.setattr(loop_module, "execute", _fake_suite_result)
    state_dir = tmp_path / "state"
    assert AcceptanceLoop(ROOT, state_dir, [entry[0] for entry in entries], 1, 30, 10).run() == 2
    report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked_evidence_changed"
    assert report["plan_complete"] is False
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["attempts"][-1]["status"] == "evidence_changed"


def test_mutation_after_suite_blocks_evidence_pass(tmp_path, monkeypatch):
    entries = [make_run(tmp_path, n) for n in range(3)]
    evidence = entries[0][1] / "logs" / "fixture-0-1.log"

    def mutate_after_suite(argv, cwd, log, timeout, junit):
        result = _fake_suite_result(argv, cwd, log, timeout, junit)
        evidence.write_text("mutated after suite", encoding="utf-8")
        return result

    monkeypatch.setattr("lib.daily_news_acceptance_loop.execute", mutate_after_suite)
    state_dir = tmp_path / "state"
    assert AcceptanceLoop(ROOT, state_dir, [entry[0] for entry in entries], 1, 30, 10).run() == 2
    report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked_evidence_changed"
    assert report["plan_complete"] is False


def test_timeout_retries_once_in_same_invocation_then_passes(tmp_path, monkeypatch):
    calls = []

    def fake_execute(argv, cwd, log, timeout, junit):
        calls.append(timeout)
        return _fake_suite_result(argv, cwd, log, timeout, junit,
                                  "timeout" if len(calls) == 1 else "passed")

    monkeypatch.setattr("lib.daily_news_acceptance_loop.execute", fake_execute)
    state_dir = tmp_path / "state"
    assert AcceptanceLoop(ROOT, state_dir, [], 2, 30, 20).run() == 2
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert [attempt["status"] for attempt in state["attempts"]] == ["timeout", "passed"]
    report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked_missing_rehearsal_inputs"
    assert report["plan_complete"] is False
    assert report["next_action"]["required_runs"] == 3


def test_timeout_exhaustion_stops_at_two_attempts_with_next_action(tmp_path, monkeypatch):
    calls = []

    def timeout_suite(argv, cwd, log, timeout, junit):
        calls.append(timeout)
        return _fake_suite_result(argv, cwd, log, timeout, junit, "timeout")

    monkeypatch.setattr("lib.daily_news_acceptance_loop.execute", timeout_suite)
    state_dir = tmp_path / "state"
    assert AcceptanceLoop(ROOT, state_dir, [], 2, 30, 20).run() == 2
    report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert len(calls) == 2 and report["status"] == "suite_timeout"
    assert "Investigate runtime load" in report["next_action"]["action"]
    assert json.loads((state_dir / "next-action.json").read_text(encoding="utf-8")) == report["next_action"]


def test_wall_budget_prevents_retry_after_timeout(tmp_path, monkeypatch):
    import lib.daily_news_acceptance_loop as loop_module

    class Clock:
        now = 1000.0

        def time(self):
            return self.now

        def time_ns(self):
            return int(self.now * 1_000_000_000)

    clock = Clock()
    monkeypatch.setattr(loop_module, "time", clock)
    calls = []

    def timeout_spends_budget(argv, cwd, log, timeout, junit):
        calls.append(timeout)
        clock.now += 2
        return _fake_suite_result(argv, cwd, log, timeout, junit, "timeout")

    monkeypatch.setattr(loop_module, "execute", timeout_spends_budget)
    state_dir = tmp_path / "state"
    assert AcceptanceLoop(ROOT, state_dir, [], 2, 1, 10).run() == 2
    assert calls == [1]
    assert json.loads((state_dir / "report.json").read_text(encoding="utf-8"))["status"] == "suite_timeout"


def test_deterministic_failure_waits_for_changed_fingerprint_before_retry(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    manifest = tmp_path / "input.json"
    manifest.write_text("{\"generation\":1}", encoding="utf-8")
    calls = []

    def fail_suite(*args):
        calls.append(args)
        return {"outcome": "failed", "exit_code": 1, "log": "", "junit": "",
                "log_sha256": "", "junit_sha256": None,
                "junit_summary": {"tests": 1, "failures": 1, "errors": 0, "skipped": 0}}

    monkeypatch.setattr("lib.daily_news_acceptance_loop.execute", fail_suite)
    loop = AcceptanceLoop(ROOT, state_dir, [manifest], 2, 30, 10)
    assert loop.run() == 2
    assert loop.run() == 2
    assert len(calls) == 1
    failed_report = json.loads((state_dir / "report.json").read_text(encoding="utf-8"))
    assert failed_report["status"] == "acceptance_failed"
    assert "fix the failing source locally" in failed_report["next_action"]["action"]
    manifest.write_text("{\"generation\":2}", encoding="utf-8")
    assert loop.run() == 2
    assert len(calls) == 2
    state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["total_attempt_count"] == 2
    assert len(state["superseded_attempts"]) == 1


def test_atomic_json_is_durable_and_parseable(tmp_path):
    path = tmp_path / "nested/state.json"
    atomic_json(path, {"attempts": []})
    assert json.loads(path.read_text(encoding="utf-8")) == {"attempts": []}
    assert not list(path.parent.glob("*.tmp"))
