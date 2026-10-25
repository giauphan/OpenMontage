"""Tests for validate_display_language script."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.validate_display_language import _subtitle_blocks, _text_errors


def test_subtitle_blocks_from_sections_json(tmp_path: Path):
    script_data = {
        "version": "1.0",
        "title": "Autonomous AI Coding Agents: Why Sandbox Tool Governance Matters",
        "total_duration_seconds": 65,
        "sections": [
            {
                "id": "hook",
                "start_seconds": 0.0,
                "end_seconds": 6.0,
                "text": "What happens when autonomous AI agents start asking for your production database passwords?",
            },
            {
                "id": "solution",
                "start_seconds": 6.0,
                "end_seconds": 18.0,
                "text": "In modern enterprise cloud environments, machine identities outnumber human accounts.",
            },
        ],
    }
    script_file = tmp_path / "script_en_US.json"
    script_file.write_text(json.dumps(script_data), encoding="utf-8")

    blocks = _subtitle_blocks(script_file)
    assert len(blocks) == 1
    line, text = blocks[0]
    assert "What happens when autonomous AI agents" in text
    assert "machine identities outnumber human accounts" in text

    errors = _text_errors(script_file, blocks, locale="en-US")
    assert not errors


def test_subtitle_blocks_rejects_vietnamese_in_en_us_script(tmp_path: Path):
    bad_data = {
        "version": "1.0",
        "title": "Bad Script",
        "sections": [
            {
                "id": "hook",
                "text": "Hôm nay chúng ta sẽ tìm hiểu về tintuc congnghe AI mới nhất.",
            }
        ],
    }
    script_file = tmp_path / "bad_script_en_US.json"
    script_file.write_text(json.dumps(bad_data), encoding="utf-8")

    blocks = _subtitle_blocks(script_file)
    errors = _text_errors(script_file, blocks, locale="en-US")
    assert errors
    assert any("Vietnamese" in err for err in errors)


def test_subtitle_blocks_from_word_timestamps_json(tmp_path: Path):
    ts_data = {
        "word_timestamps": [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]
    }
    ts_file = tmp_path / "word_timestamps.json"
    ts_file.write_text(json.dumps(ts_data), encoding="utf-8")

    blocks = _subtitle_blocks(ts_file)
    assert len(blocks) == 1
    assert blocks[0][1] == "Hello world"
