"""Shared test helpers for HyperFrames compose unit tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def build_tiny_mp4(mp4_path: Path) -> Path:
    """Build a minimal 2s MP4 file for final_review probing."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=#000000:s=320x240:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(mp4_path),
        ],
        capture_output=True, check=True, timeout=30,
    )
    return mp4_path


def make_render_runner(payload: bytes = b"rendered", tamper_file: Path | None = None):
    """Create a mock _run_hf callback that writes payload to --output."""
    def _runner(args, *, cwd, timeout, check):
        if tamper_file is not None:
            tamper_file.write_text("<html><body>Tampered Page</body></html>", encoding="utf-8")
        output = Path(args[args.index("--output") + 1])
        rendered_output = output if output.is_absolute() else cwd / output
        rendered_output.parent.mkdir(parents=True, exist_ok=True)
        if payload:
            rendered_output.write_bytes(payload)
        else:
            rendered_output.touch()
        return subprocess.CompletedProcess(args, 0, "", "")

    return _runner


def valid_runtime_decision(options: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal schema-valid decision_log entry with given options."""
    return {
        "decision_id": "d-runtime-1",
        "stage": "proposal",
        "category": "render_runtime_selection",
        "subject": "composition runtime",
        "options_considered": options,
        "selected": options[0]["option_id"],
        "reason": "fit-for-brief",
    }


SAMPLE_PUNCTUATION_LEAK_TRANSCRIPT = {
    "word_timestamps": [
        {"word": "A", "start": 0.0, "end": 0.1},
        {"word": "computer", "start": 0.1, "end": 0.5},
        {"word": "just", "start": 0.5, "end": 0.7},
        {"word": "did", "start": 0.7, "end": 0.9},
        {"word": "in", "start": 0.9, "end": 1.0},
        {"word": "five", "start": 1.0, "end": 1.3},
        {"word": "minutes", "start": 1.3, "end": 1.7},
        {"word": "dot", "start": 1.7, "end": 1.9},
        {"word": "dot", "start": 1.9, "end": 2.1},
        {"word": "dot", "start": 2.1, "end": 2.3},
        {"word": "what", "start": 2.5, "end": 2.8},
        {"word": "would", "start": 2.8, "end": 3.0},
        {"word": "take", "start": 3.0, "end": 3.3},
        {"word": "every", "start": 3.3, "end": 3.6},
        {"word": "machine", "start": 3.6, "end": 4.0},
        {"word": "on", "start": 4.0, "end": 4.2},
        {"word": "Earth", "start": 4.2, "end": 4.6},
        {"word": "running", "start": 4.7, "end": 5.1},
        {"word": "since", "start": 5.1, "end": 5.4},
        {"word": "the", "start": 5.4, "end": 5.5},
        {"word": "Big", "start": 5.5, "end": 5.8},
        {"word": "Bang", "start": 5.8, "end": 6.2},
        {"word": "ten", "start": 6.2, "end": 6.5},
        {"word": "septillion", "start": 6.5, "end": 7.3},
        {"word": "years", "start": 7.3, "end": 7.7},
        {"word": "to", "start": 7.7, "end": 7.9},
        {"word": "finish", "start": 7.9, "end": 8.3},
        {"word": "dot", "start": 8.3, "end": 8.5},
        {"word": "We", "start": 9.0, "end": 9.2},
        {"word": "may", "start": 9.2, "end": 9.4},
        {"word": "have", "start": 9.4, "end": 9.6},
        {"word": "gotten", "start": 9.6, "end": 9.9},
        {"word": "help", "start": 9.9, "end": 10.3},
        {"word": "from", "start": 10.3, "end": 10.5},
        {"word": "parallel", "start": 10.5, "end": 11.0},
        {"word": "universes", "start": 11.0, "end": 11.7},
    ]
}

SAMPLE_CLEAN_TRANSCRIPT = {
    "word_timestamps": [
        {"word": "The", "start": 0.0, "end": 0.1},
        {"word": "quick", "start": 0.1, "end": 0.4},
        {"word": "brown", "start": 0.4, "end": 0.7},
        {"word": "fox", "start": 0.7, "end": 1.0},
        {"word": "jumps", "start": 1.0, "end": 1.3},
        {"word": "over", "start": 1.3, "end": 1.6},
        {"word": "the", "start": 1.6, "end": 1.7},
        {"word": "lazy", "start": 1.7, "end": 2.0},
        {"word": "dog", "start": 2.0, "end": 2.3},
    ]
}
