"""Contract test for ToolRegistry parity and stability.

Ensures that refactorings and extractions do not break dynamic tool discovery,
pollute the registry with private helper classes, or mutate tool contracts.
"""

from __future__ import annotations

import pytest
from tools.base_tool import BaseTool
from tools.tool_registry import ToolRegistry


class TestToolRegistryParity:
    """Parity tests for tool discovery and registry API."""

    def test_discovery_baseline(self):
        """Registry must discover at least 109 tools without unhandled exceptions."""
        reg = ToolRegistry()
        reg.discover()
        assert len(reg._tools) >= 109, f"Expected at least 109 tools, found {len(reg._tools)}"

    def test_all_tools_inherit_base_tool(self):
        """Every tool discovered must be a concrete BaseTool subclass."""
        reg = ToolRegistry()
        reg.discover()
        for name, tool in reg._tools.items():
            assert isinstance(tool, BaseTool), f"Tool {name} ({type(tool)}) does not inherit from BaseTool"
            assert tool.name == name, f"Tool instance name '{tool.name}' mismatch with registry key '{name}'"

    def test_core_capabilities_exist(self):
        """Essential capability groupings must contain expected tools."""
        reg = ToolRegistry()
        reg.discover()

        video_post = reg.get_by_capability("video_post")
        video_post_names = [t.name for t in video_post]
        assert "video_compose" in video_post_names
        assert "video_stitch" in video_post_names

        tts = reg.get_by_capability("tts")
        assert len(tts) >= 3

        vid_gen = reg.get_by_capability("video_generation")
        assert len(vid_gen) >= 5

        img_gen = reg.get_by_capability("image_generation")
        assert len(img_gen) >= 4

    def test_provider_menu_summary_structure(self):
        """provider_menu_summary returns expected high-level structure."""
        reg = ToolRegistry()
        reg.discover()
        summary = reg.provider_menu_summary()
        assert "composition_runtimes" in summary
        assert "capabilities" in summary
        assert "setup_offers" in summary
        assert "runtime_warnings" in summary

    def test_no_private_helper_tools_registered(self):
        """No internal private helper classes (e.g. from _compose) should register as tools."""
        reg = ToolRegistry()
        reg.discover()
        for name, tool in reg._tools.items():
            assert not tool.__class__.__module__.endswith("._compose"), (
                f"Private module registered tool: {name} from {tool.__class__.__module__}"
            )
            assert not name.startswith("_"), f"Tool name starts with underscore: {name}"
