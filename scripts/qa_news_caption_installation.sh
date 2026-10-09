#!/usr/bin/env bash
# Bounded HyperFrames QA for the caption installer; synthetic fixture data only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${OPENMONTAGE_PYTHON:-python3}"
PROJECTS="$ROOT/projects"
mkdir -p "$PROJECTS"
QA_DIR="$(mktemp -d "$PROJECTS/qa-caption-installation.XXXXXX")"
mkdir -p "$QA_DIR/assets" "$QA_DIR/renders"
cp "$ROOT/tests/fixtures/news_caption_hyperframes_qa.html.fixture" "$QA_DIR/index.html"
printf '%s' 'synthetic caption installer QA audio bytes; not a media asset' > "$QA_DIR/assets/narration.mp3"

"$PY" - "$QA_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
audio = project / "assets" / "narration.mp3"
words = [
    {"word": "Synthetic", "start": 0.5, "end": 1.0},
    {"word": "QA", "start": 1.1, "end": 1.4},
    {"word": "caption", "start": 1.5, "end": 2.0},
    {"word": "sample.", "start": 3.0, "end": 3.7},
]
payload = {
    "timing_source": "asr",
    "timing_verified": False,
    "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
    "duration_seconds": 10.0,
    "word_timestamps": words,
}
(project / "assets" / "word_timestamps.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
)
PY

"$PY" "$ROOT/scripts/install_news_captions.py" \
  "$QA_DIR/index.html" \
  "$QA_DIR/assets/narration.mp3" \
  "$QA_DIR/assets/word_timestamps.json"

HYPERFRAMES_BIN="$(command -v hyperframes || true)"
if [ -z "$HYPERFRAMES_BIN" ] && [ -x "$ROOT/node_modules/.bin/hyperframes" ]; then
  HYPERFRAMES_BIN="$ROOT/node_modules/.bin/hyperframes"
fi
if [ -z "$HYPERFRAMES_BIN" ]; then
  echo "ERROR: HyperFrames CLI must already be installed; refusing npx/network fallback" >&2
  exit 1
fi

# Use the documented current-directory command forms and bound every runtime command.
printf 'Capture command: (cd %q && timeout 180 %q snapshot --at %q)\n' \
  "$QA_DIR" "$HYPERFRAMES_BIN" "0.7,1.7,3.4,9.5"
printf 'Render command (optional review artifact): (cd %q && timeout 300 %q render --quality draft --strict --browser-timeout 30 --output renders/caption-qa.mp4)\n' \
  "$QA_DIR" "$HYPERFRAMES_BIN"
pushd "$QA_DIR" >/dev/null
timeout 180 "$HYPERFRAMES_BIN" lint
timeout 180 "$HYPERFRAMES_BIN" validate
timeout 180 "$HYPERFRAMES_BIN" inspect --at 0.7,1.7,3.4,9.5
timeout 180 "$HYPERFRAMES_BIN" snapshot --at 0.7,1.7,3.4,9.5
if [ "${1:-}" = "--render" ]; then
  timeout 300 "$HYPERFRAMES_BIN" render --quality draft --strict \
    --browser-timeout 30 --output renders/caption-qa.mp4
fi
popd >/dev/null
printf 'Caption QA project retained at %s\n' "$QA_DIR"
printf 'Fixture/timing data is synthetic; it makes no ASR-accuracy or editorial-quality claim.\n'
