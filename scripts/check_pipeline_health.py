#!/usr/bin/env python3
"""Read-only pipeline health check.

Run after any pipeline run to verify the system is healthy before the next cron cycle.

Exit codes:
  0 = all checks pass
  1 = one or more checks failed (details printed)
  2 = cannot connect to sandbox-video (network or SSH)
  3 = syntax error in critical scripts
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def ssh(cmd: str) -> tuple[int, str, str]:
    """Run a command on sandbox-video via SSH. Returns (rc, stdout, stderr)."""
    full = [
        "ssh", "-F", "/home/ubuntu/.ssh/ssh-sandbox-video",
        "-i", "/home/ubuntu/.ssh/tunnel_key",
        "sandbox-video", cmd
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def check_containers() -> list[str]:
    """Check all required containers are running."""
    errors = []
    rc, out, err = ssh('docker ps --format "{{.Names}}|{{.Status}}"')
    if rc != 0:
        return [f"SSH failed to sandbox-video (rc={rc})"]
    running = {}
    for line in out.strip().splitlines():
        if "|" in line:
            name, status = line.split("|", 1)
            running[name] = status
    for container in ("openmontage_scheduler", "openmontage_worker"):
        if container not in running:
            errors.append(f"Container not running: {container}")
    return errors


def check_pythonpath_fix() -> list[str]:
    """Verify PYTHONPATH fix is present in publish_active_projects.py."""
    errors = []
    rc, out, err = ssh(
        "grep -c 'PYTHONPATH.*ROOT' /home/ubuntu/OpenMontage/scripts/publish_active_projects.py"
    )
    if rc != 0 or int(out.strip() or "0") < 1:
        errors.append("PYTHONPATH fix MISSING in publish_active_projects.py")
    return errors


def check_render_ready() -> list[str]:
    """Count render-ready candidates with valid metadata."""
    errors = []
    script = """
import json, sys
from pathlib import Path
root = Path("/home/ubuntu/OpenMontage/projects")
ready = 0
for d in sorted(root.iterdir()):
    if not d.is_dir(): continue
    renders = d / "renders"
    if not renders.is_dir(): continue
    mp4s = [f for f in renders.iterdir() if f.suffix == ".mp4" and f.stat().st_size > 0]
    if not mp4s: continue
    meta = d / "publish_metadata.json"
    ready += 1 if meta.is_file() else 0
print("READY=" + str(ready))
"""
    full = [
        "ssh", "-F", "/home/ubuntu/.ssh/ssh-sandbox-video",
        "-i", "/home/ubuntu/.ssh/tunnel_key",
        "sandbox-video",
        "python3", "-c", script
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=120)
    rc, out = r.returncode, r.stdout
    if rc == 0:
        for line in out.strip().splitlines():
            if line.startswith("READY="):
                n = int(line.split("=")[1])
                if n == 0:
                    errors.append(f"No render-ready candidates (need renders + metadata)")
                else:
                    print(f"  render-ready candidates: {n}")
    else:
        errors.append(f"Cannot count render-ready candidates (rc={rc})")
    return errors


def check_pipeline_log() -> list[str]:
    """Check latest pipeline log for FATAL lines."""
    errors = []
    rc, out, err = ssh(
        "grep -c '^.*FATAL.*type=' /home/ubuntu/OpenMontage/logs/cron_pipeline.log 2>/dev/null || echo 0"
    )
    if rc == 0:
        n = int(out.strip() or "0")
        if n > 0:
            errors.append(f"{n} FATAL line(s) in cron_pipeline.log — pipeline failures detected")
            # Also show the FATAL lines
            rc2, fatals, _ = ssh(
                "grep '^.*FATAL.*type=' /home/ubuntu/OpenMontage/logs/cron_pipeline.log 2>/dev/null | tail -5"
            )
            if fatals.strip():
                errors.append("  " + "\n  ".join(fatals.strip().splitlines()[:5]))
    else:
        errors.append(f"Cannot read cron_pipeline.log (rc={rc})")
    return errors


def check_publish_log() -> list[str]:
    """Check latest publish log for errors."""
    errors = []
    rc, out, err = ssh(
        "grep -c 'FAILED\\|ERROR\\|SKIPPED.*duplicate' /home/ubuntu/OpenMontage/logs/cron_publish.log 2>/dev/null || echo 0"
    )
    if rc == 0:
        n = int(out.strip() or "0")
        if n > 0:
            errors.append(f"{n} error/skipped line(s) in cron_publish.log")
    return errors


def check_git_head() -> list[str]:
    """Check git HEAD matches origin/main."""
    errors = []
    rc, out, _ = ssh("cd /home/ubuntu/OpenMontage && git rev-parse --short HEAD")
    if rc == 0:
        head = out.strip()
        print(f"  server HEAD: {head}")
        rc2, behind, _ = ssh(
            f"cd /home/ubuntu/OpenMontage && git rev-list --count HEAD..origin/main 2>/dev/null || echo 0"
        )
        if rc2 == 0:
            n = int(behind.strip() or "0")
            if n > 0:
                errors.append(f"Server is {n} commit(s) behind origin/main — needs git pull")
    else:
        errors.append(f"Cannot read git HEAD on server (rc={rc})")
    return errors


def main() -> int:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] Pipeline Health Check")
    print("=" * 60)

    all_errors = []

    print("\n[1] Containers")
    all_errors.extend(check_containers())

    print("\n[2] PYTHONPATH fix")
    all_errors.extend(check_pythonpath_fix())

    print("\n[3] Render-ready candidates")
    all_errors.extend(check_render_ready())

    print("\n[4] Pipeline log (FATAL check)")
    all_errors.extend(check_pipeline_log())

    print("\n[5] Publish log (errors check)")
    all_errors.extend(check_publish_log())

    print("\n[6] Git HEAD")
    all_errors.extend(check_git_head())

    print("\n" + "=" * 60)
    if all_errors:
        print(f"STATUS: FAIL ({len(all_errors)} issue(s))")
        for e in all_errors:
            print(f"  ❌ {e}")
        return 1
    else:
        print("STATUS: PASS — pipeline is healthy")
        return 0


if __name__ == "__main__":
    sys.exit(main())
