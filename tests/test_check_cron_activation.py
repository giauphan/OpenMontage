from pathlib import Path


def test_check_activation_reports_valid_static_contract(tmp_path: Path) -> None:
    from scripts.check_cron_activation import check_static_contract

    (tmp_path / "deploy").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "deploy" / "openmontage.cron").write_text(
        "PATH=/usr/bin\n0 23 * * * cd /app && ./scripts/job.sh >> logs/x.log 2>&1\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "job.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  scheduler:\n    healthcheck:\n      test: [CMD, pgrep, cron]\n",
        encoding="utf-8",
    )

    assert check_static_contract(tmp_path) == []


def test_check_activation_rejects_missing_cron_target(tmp_path: Path) -> None:
    from scripts.check_cron_activation import check_static_contract

    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "openmontage.cron").write_text(
        "0 23 * * * cd /app && ./scripts/missing.sh >> logs/x.log 2>&1\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services:\n  scheduler: {}\n", encoding="utf-8")

    assert "missing cron target: scripts/missing.sh" in check_static_contract(tmp_path)
