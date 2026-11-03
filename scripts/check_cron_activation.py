#!/usr/bin/env python3
"""Read-only verification for the Docker daily cron activation contract."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def check_static_contract(root: Path) -> list[str]:
    """Return static activation defects without changing the checkout or Docker."""
    errors: list[str] = []
    cron = root / "deploy" / "openmontage.cron"
    compose = root / "docker-compose.yml"
    if not cron.is_file():
        return ["missing deploy/openmontage.cron"]
    if not compose.is_file():
        errors.append("missing docker-compose.yml")
    else:
        text = compose.read_text(encoding="utf-8")
        if not re.search(r"^\s*scheduler:\s*(?:$|\{)", text, re.M):
            errors.append("compose scheduler service missing")
        if "healthcheck:" not in text:
            errors.append("compose scheduler healthcheck missing")
    for line in cron.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\d+ \d+ \* \* \* ", line):
            continue
        for target in re.findall(r"(?:\./|/)scripts/([A-Za-z0-9_.-]+)", line):
            rel = Path("scripts") / target
            if not (root / rel).is_file():
                errors.append(f"missing cron target: {rel}")
    return errors


def check_installed(container: str, cron_file: Path) -> list[str]:
    """Read installed scheduler state through Docker without mutating it."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        return ["invalid scheduler container name"]
    errors: list[str] = []
    inspect = subprocess.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", "--", container], text=True, capture_output=True)
    if inspect.returncode or inspect.stdout.strip() != "healthy":
        errors.append(f"scheduler is not healthy: {inspect.stdout.strip() or inspect.stderr.strip()}")
        return errors
    installed = subprocess.run(["docker", "exec", "--", container, "crontab", "-l"], text=True, capture_output=True)
    if installed.returncode:
        errors.append("scheduler has no readable installed crontab")
    elif cron_file.read_text(encoding="utf-8").strip() != installed.stdout.strip():
        errors.append("installed crontab differs from deploy/openmontage.cron")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--container", help="Also inspect this running scheduler container")
    args = parser.parse_args()
    root = args.root.resolve()
    errors = check_static_contract(root)
    if args.container and not errors:
        errors.extend(check_installed(args.container, root / "deploy" / "openmontage.cron"))
    if errors:
        print("CRON ACTIVATION CHECK FAILED")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("CRON ACTIVATION CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
