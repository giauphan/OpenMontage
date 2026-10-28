"""Unit tests for tools.graphics.thumbnail_generator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tools.graphics.thumbnail_generator import ThumbnailGenerator
from tools.tool_registry import ToolRegistry


def test_thumbnail_generator_discovered_in_registry():
    registry = ToolRegistry()
    registry.discover()
    assert "thumbnail_generator" in registry._tools
    tool_cls = registry._tools["thumbnail_generator"]
    tool = tool_cls() if isinstance(tool_cls, type) else tool_cls
    assert tool.capability == "thumbnail_generation"
    assert tool.provider == "muse"


def test_thumbnail_generator_requires_inputs():
    tool = ThumbnailGenerator()
    res = tool.execute({})
    assert res.success is False
    assert "project_dir is required" in res.error

    res = tool.execute({"project_dir": "/tmp"})
    assert res.success is False
    assert "title is required" in res.error


def test_thumbnail_generator_success_execution(tmp_path: Path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()

    tool = ThumbnailGenerator()
    res = tool.execute({
        "project_dir": str(proj_dir),
        "title": "Quantum Computing Milestones #tech",
        "format": "short",
    })

    assert res.success is True
    assert res.data["thumbnail_status"] == "THUMBNAIL_READY"
    assert res.data["aspect_ratio"] == "9:16"
    assert Path(res.data["thumbnail_path"]).is_file()
    assert len(res.artifacts) == 1
