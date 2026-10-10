"""Tests for pipeline monitoring and error logging."""

import json
import multiprocessing

import pytest

from scripts.pipeline_monitoring import (
    MonitoringReportError,
    append_monitoring_event,
    log_pipeline_error,
    log_pipeline_retry,
    log_pipeline_success,
)


def _append_process_events(json_path, log_path, process_id, event_count):
    import scripts.pipeline_monitoring as monitoring

    monitoring.LOGS_DIR = json_path.parent
    monitoring.JSON_REPORT_PATH = json_path
    monitoring.LOG_REPORT_PATH = log_path
    for event_id in range(event_count):
        monitoring.append_monitoring_event(
            event_type="test",
            stage="concurrent",
            message=f"{process_id}:{event_id}",
        )


def test_pipeline_monitoring_events(tmp_path, monkeypatch):
    test_log_dir = tmp_path / "logs"
    monkeypatch.setattr("scripts.pipeline_monitoring.LOGS_DIR", test_log_dir)
    monkeypatch.setattr("scripts.pipeline_monitoring.JSON_REPORT_PATH", test_log_dir / "report.json")
    monkeypatch.setattr("scripts.pipeline_monitoring.LOG_REPORT_PATH", test_log_dir / "report.log")

    # 1. Log error
    err_event = log_pipeline_error(
        stage="render_hyperframes",
        project_id="cand_test123",
        error_type="FREEZE_DETECTED",
        message="Freezedetect failed at scene 2",
        details={"static_ratio": 0.65},
        attempt=1,
        max_attempts=3,
    )
    assert err_event["status"] == "ERROR"
    assert err_event["project_id"] == "cand_test123"

    # 2. Log retry
    ret_event = log_pipeline_retry(
        stage="render_hyperframes",
        project_id="cand_test123",
        reason="Retrying after repair",
        attempt=2,
        max_attempts=3,
    )
    assert ret_event["status"] == "RETRY"

    # 3. Log success
    succ_event = log_pipeline_success(
        stage="render_hyperframes",
        project_id="cand_test123",
        message="Render passed with repair",
    )
    assert succ_event["status"] == "SUCCESS"

    # Verify JSON file structure
    report_file = test_log_dir / "report.json"
    assert report_file.is_file()
    data = json.loads(report_file.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["error_type"] == "FREEZE_DETECTED"
    assert data[1]["status"] == "RETRY"
    assert data[2]["status"] == "SUCCESS"


def test_concurrent_process_appends_preserve_every_event(tmp_path, monkeypatch):
    test_log_dir = tmp_path / "logs"
    monkeypatch.setattr("scripts.pipeline_monitoring.LOGS_DIR", test_log_dir)
    monkeypatch.setattr("scripts.pipeline_monitoring.JSON_REPORT_PATH", test_log_dir / "report.json")
    monkeypatch.setattr("scripts.pipeline_monitoring.LOG_REPORT_PATH", test_log_dir / "report.log")

    process_count = 6
    events_per_process = 12
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_append_process_events,
            args=(test_log_dir / "report.json", test_log_dir / "report.log", index, events_per_process),
        )
        for index in range(process_count)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
    finally:
        for process in processes:
            if process.pid is not None and process.is_alive():
                process.terminate()
        for process in processes:
            if process.pid is not None:
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join()

    assert all(process.exitcode == 0 for process in processes)
    data = json.loads((test_log_dir / "report.json").read_text(encoding="utf-8"))
    assert len(data) == process_count * events_per_process
    assert len({event["message"] for event in data}) == len(data)


@pytest.mark.parametrize("evidence", [b'{"partial": ', b'{"old": true}', b'[1]'])
def test_malformed_history_is_preserved_and_append_fails(tmp_path, monkeypatch, evidence):
    test_log_dir = tmp_path / "logs"
    monkeypatch.setattr("scripts.pipeline_monitoring.LOGS_DIR", test_log_dir)
    report_path = test_log_dir / "report.json"
    monkeypatch.setattr("scripts.pipeline_monitoring.JSON_REPORT_PATH", report_path)
    monkeypatch.setattr("scripts.pipeline_monitoring.LOG_REPORT_PATH", test_log_dir / "report.log")
    test_log_dir.mkdir()
    report_path.write_bytes(evidence)

    with pytest.raises(MonitoringReportError, match="original file was preserved"):
        append_monitoring_event(event_type="test", stage="corrupt")

    assert report_path.read_bytes() == evidence
    assert not (test_log_dir / "report.log").exists()


def test_nonregular_history_path_fails_without_replacement(tmp_path, monkeypatch):
    test_log_dir = tmp_path / "logs"
    report_path = test_log_dir / "report.json"
    monkeypatch.setattr("scripts.pipeline_monitoring.LOGS_DIR", test_log_dir)
    monkeypatch.setattr("scripts.pipeline_monitoring.JSON_REPORT_PATH", report_path)
    monkeypatch.setattr("scripts.pipeline_monitoring.LOG_REPORT_PATH", test_log_dir / "report.log")
    report_path.mkdir(parents=True)

    with pytest.raises(MonitoringReportError, match="not a regular file"):
        append_monitoring_event(event_type="test", stage="nonregular")

    assert report_path.is_dir()
    assert not (test_log_dir / "report.log").exists()


def test_atomic_report_save_replaces_file_and_leaves_no_temp(tmp_path, monkeypatch):
    test_log_dir = tmp_path / "logs"
    report_path = test_log_dir / "report.json"
    monkeypatch.setattr("scripts.pipeline_monitoring.LOGS_DIR", test_log_dir)
    monkeypatch.setattr("scripts.pipeline_monitoring.JSON_REPORT_PATH", report_path)
    from scripts.pipeline_monitoring import _save_json_report

    _save_json_report([{"message": "durable"}])

    assert json.loads(report_path.read_text(encoding="utf-8")) == [{"message": "durable"}]
    assert list(test_log_dir.glob("*.tmp")) == []


def test_atomic_save_fsync_failure_preserves_old_report_and_cleans_temp(tmp_path, monkeypatch):
    import scripts.pipeline_monitoring as monitoring

    test_log_dir = tmp_path / "logs"
    report_path = test_log_dir / "report.json"
    monkeypatch.setattr(monitoring, "LOGS_DIR", test_log_dir)
    monkeypatch.setattr(monitoring, "JSON_REPORT_PATH", report_path)
    test_log_dir.mkdir()
    old_report = b'[{"message": "old"}]\n'
    report_path.write_bytes(old_report)

    def fail_fsync(_fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(monitoring.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated fsync failure"):
        monitoring._save_json_report([{"message": "new"}])

    assert report_path.read_bytes() == old_report
    assert list(test_log_dir.glob("*.tmp")) == []
