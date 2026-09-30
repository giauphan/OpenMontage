"""Exercise the wrapper's real preflight without cleanup or production stages."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _run_preflight(tmp_path: Path, *, codex: bool, claude: bool):
    wrapper = (ROOT / "scripts" / "run_strict_docker_publish.sh").read_text(encoding="utf-8")
    start = wrapper.index('stage 0 "preflight"')
    end = wrapper.index("# ===== STAGE 1:", start)
    preflight = wrapper[start:end]

    bash = shutil.which("bash")
    assert bash is not None, "bash is required to test the shell preflight"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Use a closed PATH so an installed host CLI cannot satisfy the check.
    for name, output in {
        "python3": "Python 3.12.0",
        "ffmpeg": "",
        "ffprobe": "",
        "hostname": "preflight-test",
        **({"codex": "codex-test 1.0"} if codex else {}),
        **({"claude": "claude-test 1.0"} if claude else {}),
    }.items():
        executable = binaries / name
        executable.write_text(f"#!{bash}\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
        executable.chmod(0o755)
    for name in ("awk", "head"):
        executable = shutil.which(name)
        assert executable is not None, f"{name} is required for the preflight version report"
        (binaries / name).symlink_to(executable)

    # Extract only stage zero. In particular, never source the wrapper or its
    # destructive cleanup function; the next-stage marker is a harmless stand-in.
    harness = """set -euo pipefail
stage() { printf 'STAGE %s %s\n' "$1" "$2"; }
cleanup_system_disk_space() { printf 'CLEANUP_STUB\n'; }
log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*"; exit 1; }
write_state() { printf 'STATE %s %s\n' "$1" "$2"; }
""" + preflight + "\nprintf 'PRODUCTION_REACHED\\n'\n"
    return subprocess.run(
        [bash, "--noprofile", "--norc", "-c", harness],
        cwd=tmp_path,
        env={"PATH": str(binaries), "STRICT_PUBLISH_SKIP_DOCKER_CHECK": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_preflight_source_does_not_require_claude(tmp_path: Path):
    wrapper = (ROOT / "scripts" / "run_strict_docker_publish.sh").read_text(encoding="utf-8")
    start = wrapper.index('stage 0 "preflight"')
    end = wrapper.index("# ===== STAGE 1:", start)
    preflight = wrapper[start:end]
    assert 'command -v claude' not in preflight
    assert 'command -v codex' in preflight


def test_preflight_passes_with_codex_and_without_claude(tmp_path: Path):
    result = _run_preflight(tmp_path, codex=True, claude=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "preflight OK" in result.stdout
    assert "codex=codex-test 1.0" in result.stdout
    assert "STATE preflight ok" in result.stdout
    assert "PRODUCTION_REACHED" in result.stdout
    assert "CLEANUP_STUB" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("claude", [False, True], ids=["no-cli", "claude-only"])
def test_preflight_missing_codex_stops_before_production(tmp_path: Path, claude: bool):
    result = _run_preflight(tmp_path, codex=False, claude=claude)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR: codex CLI missing" in result.stdout
    assert "preflight OK" not in result.stdout
    assert "STATE preflight ok" not in result.stdout
    assert "PRODUCTION_REACHED" not in result.stdout
    assert "CLEANUP_STUB" in result.stdout
    assert result.stderr == ""
