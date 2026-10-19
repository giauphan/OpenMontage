"""Architecture fitness functions and boundary enforcement tests.

Guarantees that:
1. Internal helper modules (_compose, _hyperframes) never reverse-import their parent tool facades.
2. Internal helper modules never declare concrete BaseTool subclasses (which would pollute ToolRegistry).
3. New modular extracts remain focused (bounded size).
4. Public facades maintain their contract and supported operations.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

from tools.base_tool import BaseTool
from tools.video.video_compose import VideoCompose
from tools.video.hyperframes_compose import HyperFramesCompose


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


class TestArchitectureFitness:
    """Automated architecture fitness functions enforcing dependency directions."""

    def test_compose_helpers_do_not_import_facade(self):
        """_compose modules must be leaf utilities and never import video_compose."""
        compose_dir = WORKSPACE_ROOT / "tools" / "video" / "_compose"
        assert compose_dir.is_dir(), "tools/video/_compose directory must exist"

        for py_file in compose_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "video_compose" not in alias.name, (
                            f"Forbidden import: {py_file.name} imports {alias.name}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert "video_compose" not in module, (
                        f"Forbidden import: {py_file.name} imports from {module}"
                    )
                    for alias in node.names:
                        assert alias.name != "VideoCompose", (
                            f"Forbidden import: {py_file.name} imports VideoCompose"
                        )

    def test_hyperframes_helpers_do_not_import_facade(self):
        """_hyperframes modules must be leaf utilities and never import hyperframes_compose."""
        hf_dir = WORKSPACE_ROOT / "tools" / "video" / "_hyperframes"
        assert hf_dir.is_dir(), "tools/video/_hyperframes directory must exist"

        for py_file in hf_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "hyperframes_compose" not in alias.name, (
                            f"Forbidden import: {py_file.name} imports {alias.name}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert "hyperframes_compose" not in module, (
                        f"Forbidden import: {py_file.name} imports from {module}"
                    )
                    for alias in node.names:
                        assert alias.name != "HyperFramesCompose", (
                            f"Forbidden import: {py_file.name} imports HyperFramesCompose"
                        )

    def test_internal_helpers_do_not_subclass_basetool(self):
        """Internal helper packages must not define concrete BaseTool subclasses.

        This ensures dynamic tool discovery in ToolRegistry does not mistakenly
        register internal helpers as public tools.
        """
        helper_dirs = [
            WORKSPACE_ROOT / "tools" / "video" / "_compose",
            WORKSPACE_ROOT / "tools" / "video" / "_hyperframes",
        ]
        for hdir in helper_dirs:
            if not hdir.is_dir():
                continue
            for py_file in hdir.glob("*.py"):
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        base_names = [
                            base.id for base in node.bases if isinstance(base, ast.Name)
                        ]
                        base_attr_names = [
                            base.attr for base in node.bases if isinstance(base, ast.Attribute)
                        ]
                        all_bases = set(base_names + base_attr_names)
                        assert "BaseTool" not in all_bases, (
                            f"Helper class {node.name} in {py_file.name} must not inherit BaseTool"
                        )

    def test_modular_extracts_loc_budget(self):
        """Extracted helper files must remain bounded and cohesive (<= 500 LOC)."""
        helper_dirs = [
            WORKSPACE_ROOT / "tools" / "video" / "_compose",
            WORKSPACE_ROOT / "tools" / "video" / "_hyperframes",
        ]
        for hdir in helper_dirs:
            if not hdir.is_dir():
                continue
            for py_file in hdir.glob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                loc = len(py_file.read_text(encoding="utf-8").splitlines())
                assert loc <= 500, (
                    f"Modular helper {py_file.name} has {loc} lines, exceeding the 500 LOC limit. "
                    "Split further if responsibility is expanding."
                )

    def test_facades_maintain_required_operations(self):
        """Public facades maintain their declared contract operations."""
        vc = VideoCompose()
        assert isinstance(vc, BaseTool)
        vc_ops = vc.input_schema.get("properties", {}).get("operation", {}).get("enum", [])
        assert "render" in vc_ops
        assert "preview" in vc_ops
        assert "validate" in vc_ops
        assert "status" in vc_ops

        hfc = HyperFramesCompose()
        assert isinstance(hfc, BaseTool)
        hfc_ops = hfc.input_schema.get("properties", {}).get("operation", {}).get("enum", [])
        assert "render" in hfc_ops
        assert "preview" in hfc_ops
        assert "lint" in hfc_ops
        assert "validate" in hfc_ops
        assert "scaffold" in hfc_ops
