"""Tests for pipeline monitoring and error logging."""

import json
from pathlib import Path
from scripts.pipeline_monitoring import (
    append_monitoring_event,
    log_pipeline_error,
    log_pipeline_retry,
    log_pipeline_success,
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
