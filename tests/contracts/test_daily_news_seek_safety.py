from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "validate_newsnow_director_artifacts",
    ROOT / "scripts" / "validate_newsnow_director_artifacts.py",
)
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


def composition_html(js: str) -> str:
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"></head><body>
  <main data-composition-id="main">Tin tức</main>
  <script>{js}</script>
</body></html>
"""


def write_pair(tmp_path: Path, html: str) -> None:
    for folder in ("hyperframes", "hyperframes_reels"):
        path = tmp_path / folder / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")


def test_valid_registered_finite_timeline_passes(tmp_path):
    write_pair(
        tmp_path,
        composition_html(
            "window.__timelines = window.__timelines || {}; "
            "const tl = gsap.timeline({paused: true}); "
            "tl.to('#scene', {opacity: 1, duration: 1}, 0); "
            "window.__timelines['main'] = tl;"
        ),
    )

    assert validator.validate_composition_seek_safety(tmp_path) == []


@pytest.mark.parametrize(
    ("js", "message"),
    [
        (
            "window.__timelines = {}; const tl = gsap.timeline({paused: true, repeat: -1}); "
            "tl.to('#scene', {opacity: 1}); window.__timelines['main'] = tl;",
            "infinite GSAP repeat",
        ),
        (
            "window.__timelines = {}; const tl = gsap.timeline({paused: true}); "
            "gsap.to('#scene', {opacity: 1}); tl.to('#scene', {x: 1}); "
            "window.__timelines['main'] = tl;",
            "standalone gsap animation",
        ),
        (
            "window.__timelines = {}; const tl = gsap.timeline({paused: true}); "
            "const duration = tl.duration(); tl.to('#scene', {opacity: 1}); "
            "window.__timelines['main'] = tl;",
            "timeline duration is read or set before child animations",
        ),
        (
            'var tl = window.__timelines["main"] = gsap.timeline({paused: true}); '
            "tl.duration(58); tl.to('#scene', {opacity: 1});",
            "timeline duration is read or set before child animations",
        ),
    ],
)
def test_unsafe_composition_is_rejected_with_actionable_error(tmp_path, js, message):
    write_pair(tmp_path, composition_html(js))

    errors = validator.validate_composition_seek_safety(tmp_path)

    assert len(errors) == 2
    assert all(message in error for error in errors)


def test_seek_errors_reach_retry_context_and_success_clears_them(tmp_path):
    pipeline = (ROOT / "scripts" / "run_daily_news_pipeline.sh").read_text(encoding="utf-8")
    start = pipeline.index("validate_current_director_artifacts() {")
    end = pipeline.index("\n}\n\nif [ \"$TEMPLATE_MODE\"", start) + 2
    validator_function = pipeline[start:end]
    append_retry_context = next(
        line.strip() for line in pipeline.splitlines()
        if line.strip().startswith('RETRY_PROMPT="$(printf')
    )

    stub = tmp_path / "validator-stub.sh"
    stub.write_text(
        '''#!/bin/sh
printf '%s\\n' "$VALIDATOR_OUTPUT"
exit "$VALIDATOR_STATUS"
''',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    log = tmp_path / "directors.log"
    harness = f"""{validator_function}
DIRECTORS_LOG={str(log)!r}
PY={str(stub)!r}
ROOT=/unused
PROJECT_ID=fixture
START_TS=1
DIRECTOR_VALIDATION_ERRORS=stale
VALIDATOR_STATUS=1
VALIDATOR_OUTPUT='ERROR: standalone gsap animation; regenerate on registered timeline'
export VALIDATOR_STATUS VALIDATOR_OUTPUT
validate_current_director_artifacts || true
RETRY_PROMPT='bounded repair prompt'
{append_retry_context}
printf 'failure=%s\\n' "$DIRECTOR_VALIDATION_ERRORS"
printf 'retry=%s\\n' "$RETRY_PROMPT"
VALIDATOR_STATUS=0
VALIDATOR_OUTPUT='validated'
validate_current_director_artifacts
printf 'success=<%s>\\n' "$DIRECTOR_VALIDATION_ERRORS"
"""
    result = subprocess.run(
        ["bash", "-c", harness],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert "failure=ERROR: standalone gsap animation; regenerate on registered timeline" in result.stdout
    assert "retry=bounded repair prompt" in result.stdout
    assert "Validation errors to fix in the composition HTML:" in result.stdout
    assert "ERROR: standalone gsap animation; regenerate on registered timeline" in result.stdout
    assert "success=<>" in result.stdout
    assert "Validation errors to fix in the composition HTML:" in pipeline
    assert '"$DIRECTOR_VALIDATION_ERRORS"' in pipeline
    assert 'MAX_DIRECTOR_RETRIES="${MAX_DIRECTOR_RETRIES:-3}"' in pipeline


def test_existing_director_prompt_assignment_is_safe_in_isolated_bash(tmp_path):
    script = (ROOT / "scripts" / "run_directors_for_existing.sh").read_text(encoding="utf-8")
    assignment = next(line for line in script.splitlines() if line.startswith("  PROMPT_STR=\""))

    assert "`" not in assignment
    harness = f'''PROJECT_ID=offline_fixture
{assignment.strip()}
printf '%s' "$PROMPT_STR"
'''
    result = subprocess.run(
        ["bash", "-c", harness], check=True, capture_output=True, text=True
    )

    assert "gsap.timeline({paused:true})" in result.stdout
    assert "window.__timelines['main']" in result.stdout
    assert "command not found" not in result.stderr


def test_director_prompts_specify_the_checked_seek_safety_contract():
    generate = (ROOT / "scripts" / "prompts" / "director_generate.prompt.md").read_text(
        encoding="utf-8"
    )
    retry = (ROOT / "scripts" / "prompts" / "director_retry.prompt.md").read_text(
        encoding="utf-8"
    )
    existing = (ROOT / "scripts" / "run_directors_for_existing.sh").read_text(
        encoding="utf-8"
    )

    for prompt in (generate, retry, existing):
        assert "paused: true" in prompt or "paused:true" in prompt
        assert "repeat: -1" in prompt or "repeat:-1" in prompt
        assert "decorative motion solely to evade the frozen-canvas check" in prompt
    assert "tl.duration()" in generate
    assert "tl.duration()" in retry
    assert "tl.duration()" in existing
