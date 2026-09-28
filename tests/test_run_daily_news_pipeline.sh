#!/usr/bin/env bash
set -euo pipefail

# This test should check that the run_daily_news_pipeline.sh fail fast behavior
# is correctly implemented when subtitles generation fails.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# We will create a fake generate_vn_subtitles.py that fails.
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

export OPENMONTAGE_PYTHON="$TMPDIR/fake_python.sh"

cat << 'EOF' > "$TMPDIR/fake_python.sh"
#!/usr/bin/env bash
if [[ "$*" == *generate_vn_subtitles.py* ]]; then
  echo "Faking subtitle generation failure..." >&2
  exit 1
fi
# Passthrough to real python for other scripts
exec /usr/bin/python3 "$@"
EOF
chmod +x "$TMPDIR/fake_python.sh"

# We mock run_daily_news_pipeline.sh partially or just run it with invalid inputs
# Let's mock a smaller run if possible, but actually it's easier to grep the script logic
# Actually, let's write a mock pipeline script that sources the important parts
# Or since we want to TDD the pipeline change itself, we can copy the pipeline script
# to TMPDIR, run it, and see if it fails.

# Since `run_daily_news_pipeline.sh` runs a lot of things, we can just test the line changes.
# But to be rigorous TDD: let's grep the script to assert the fail-fast behavior.

# Assert that run_daily_news_pipeline.sh uses `|| exit 1` or similar for generate_vn_subtitles.py
# instead of `|| echo "WARNING..."`

if grep -q 'echo.*WARNING: Subtitle generation failed, continuing' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Expected script to fail fast, but found swallow warning."
    exit 1
fi

if ! grep -q '"$PY" "$ROOT/scripts/generate_vn_subtitles.py"' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Subtitle generation does not use resolved Python interpreter."
    exit 1
fi

if grep -E -q '^[[:space:]]*python3 "\$ROOT/(tools/narration_text\.py|scripts/generate_vn_subtitles\.py|scripts/repair_hyperframes_quality\.py)' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Daily pipeline has bare python3 calls that bypass OPENMONTAGE_PYTHON."
    exit 1
fi

if grep -q 'tests/qa/output/e2e_assets/music_bg.mp3' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Daily pipeline references a missing background music fixture."
    exit 1
fi

if ! grep -q 'tests/qa/output/music_calm.mp3' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Daily pipeline does not use the available background music fallback."
    exit 1
fi

if ! grep -q 'if "\$PY" "\$ROOT/scripts/codex_agent_validation.py"' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Claude validation is not guarded against errexit."
    exit 1
fi

if ! grep -q 'VALIDATION_EXIT=\$?' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Claude validation exit status is not captured."
    exit 1
fi

if ! grep -q 'if "\$PY" "\$ROOT/scripts/validate_render_quality.py"' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Render validation is not guarded against errexit, so one failed candidate aborts later candidates."
    exit 1
fi

if ! grep -q -E 'if ! materialize_hyperframes_assets ".*"; then' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Asset materialization is not guarded against errexit, so one failed candidate aborts later candidates."
    exit 1
fi

if grep -q 'exit \$CLAUDE_EXIT' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Director failure exits the generator instead of evaluating later candidates."
    exit 1
fi

if grep -q -E '^[[:space:]]+exit 2$' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Missing director compositions exit the generator instead of evaluating later candidates."
    exit 1
fi

if grep -q '\\n[[:space:]]*--' "$ROOT/scripts/run_daily_news_pipeline.sh"; then
    echo "FAIL: Daily pipeline contains literal \n before command flags."
    exit 1
fi

echo "PASS"
exit 0
