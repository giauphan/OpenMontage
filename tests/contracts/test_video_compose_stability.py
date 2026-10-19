"""Characterization contract test for VideoCompose tool stability.

Freezes public metadata, input schemas, operations, runtime policy,
and pure helper logic before and throughout refactoring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from tools.base_tool import BaseTool, ToolResult, ToolTier, ToolStability, ExecutionMode, Determinism
from tools.video.video_compose import VideoCompose
from tools.tool_registry import ToolRegistry


class TestVideoComposeStability:
    """Contract assertions for VideoCompose."""

    def test_metadata_contract(self):
        """ToolContract properties must remain strictly stable."""
        tool = VideoCompose()
        assert tool.name == "video_compose"
        assert tool.version == "0.1.0"
        assert tool.tier == ToolTier.CORE
        assert tool.capability == "video_post"
        assert tool.provider == "ffmpeg"
        assert tool.stability == ToolStability.EXPERIMENTAL
        assert tool.execution_mode == ExecutionMode.SYNC
        assert tool.determinism == Determinism.DETERMINISTIC
        assert "cmd:ffmpeg" in tool.dependencies
        assert "compose_cuts" in tool.capabilities
        assert "remotion_render" in tool.capabilities

    def test_input_schema_contract(self):
        """Input schema operations enum and properties must not drift."""
        schema = VideoCompose.input_schema
        assert schema["type"] == "object"
        assert "operation" in schema["required"]
        assert "properties" in schema

        ops = schema["properties"]["operation"]["enum"]
        expected_ops = ["compose", "render", "remotion_render", "burn_subtitles", "overlay", "encode"]
        assert sorted(ops) == sorted(expected_ops)

        for prop in [
            "input_path",
            "output_path",
            "edit_decisions",
            "asset_manifest",
            "proposal_packet",
            "preserve_existing_workspace",
        ]:
            assert prop in schema["properties"], f"Missing property {prop} in input_schema"

    def test_registry_discovery(self):
        """VideoCompose must be discoverable via registry without error."""
        reg = ToolRegistry()
        reg.discover()
        assert "video_compose" in reg._tools
        tool_instance = reg.get("video_compose")
        assert isinstance(tool_instance, VideoCompose)
        assert tool_instance.name == "video_compose"

    def test_get_info_structure(self):
        """get_info() returns expected status dictionary with render engines."""
        tool = VideoCompose()
        info = tool.get_info()
        assert "render_engines" in info
        assert "ffmpeg" in info["render_engines"]
        assert "remotion" in info["render_engines"]
        assert "hyperframes" in info["render_engines"]
        assert "remotion_note" in info
        assert "hyperframes_note" in info
        assert "runtime_governance" in info

    def test_invalid_input_fails_gracefully(self):
        """Invalid inputs return ToolResult with success=False, or raise KeyError for missing op."""
        tool = VideoCompose()
        # Missing operation raises KeyError in current implementation
        with pytest.raises(KeyError):
            tool.execute({})

        # Unknown operation returns ToolResult with success=False
        res = tool.execute({"operation": "unknown_op"})
        assert not res.success
        assert "unknown" in res.error.lower()

        # Render operation missing edit_decisions
        res = tool.execute({"operation": "render", "output_path": "/tmp/out.mp4"})
        assert not res.success
        assert "edit_decisions" in res.error.lower()

    def test_pure_helpers_atempo(self):
        """Test audio tempo filter string builder."""
        f1 = VideoCompose._build_atempo(1.0)
        assert f1 == "atempo=1.0000"

        # Multi-factor decomposition
        f3 = VideoCompose._build_atempo(200.0)
        assert "atempo=100.0" in f3

    def test_pure_helpers_is_image(self):
        """Test image extension check."""
        assert VideoCompose._is_image(Path("frame.png"))
        assert VideoCompose._is_image(Path("frame.JPG"))
        assert VideoCompose._is_image(Path("frame.webp"))
        assert not VideoCompose._is_image(Path("video.mp4"))
        assert not VideoCompose._is_image(Path("audio.mp3"))

    def test_pure_helpers_tokenizer_and_transcript_comparison(self, tmp_path):
        """Test tokenizer and transcript comparison logic."""
        tokens = VideoCompose._tokenize("Hello, World! Testing 123.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens
        assert "123" in tokens

        # Write a sample word-level transcript JSON
        transcript_file = tmp_path / "transcript.json"
        transcript_data = {
            "word_timestamps": [
                {"word": "Hello", "start": 0.0, "end": 0.5},
                {"word": "world", "start": 0.5, "end": 1.0},
            ]
        }
        transcript_file.write_text(json.dumps(transcript_data), encoding="utf-8")

        res = VideoCompose._compare_transcript_to_script(transcript_file, "Hello world")
        assert res["transcript_matches_script"] is True
        assert res["word_accuracy"] == 1.0

    def test_runtime_policy_fail_closed_on_missing_runtime(self, monkeypatch, tmp_path):
        """When selected runtime is unavailable, must fail closed without silent fallback."""
        tool = VideoCompose()
        # Force HyperFrames to be unavailable
        monkeypatch.setattr(tool, "_hyperframes_available", lambda: False)

        dummy_asset = tmp_path / "dummy.mp4"
        dummy_asset.write_bytes(b"dummy")

        inputs = {
            "operation": "render",
            "output_path": str(tmp_path / "test.mp4"),
            "edit_decisions": {
                "render_runtime": "hyperframes",
                "renderer_family": "hyperframes",
                "delivery_promise": "test promise",
                "cuts": [
                    {
                        "id": "cut_1",
                        "type": "video",
                        "source": "asset_1",
                        "duration": 2.0,
                    }
                ],
            },
            "asset_manifest": {
                "assets": [
                    {
                        "id": "asset_1",
                        "type": "video",
                        "path": str(dummy_asset),
                    }
                ]
            },
        }
        res = tool.execute(inputs)
        assert not res.success
        # Must report blocker about hyperframes, NOT quietly succeed via ffmpeg
        assert "hyperframes" in res.error.lower()
