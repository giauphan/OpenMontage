import json
from pathlib import Path

import pytest

from tools.video.multishot import Multishot


@pytest.fixture
def tool() -> Multishot:
    return Multishot()


def write_marker(project_dir: Path, **values: str) -> None:
    marker = {"project_id": project_dir.name, "pipeline_type": "multi-shot"}
    marker.update(values)
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(json.dumps(marker), encoding="utf-8")


def test_valid_project_path_and_marker_are_accepted(tool: Multishot, tmp_path: Path) -> None:
    project_dir = tmp_path / "valid_project"
    write_marker(project_dir)

    resolved = tool._get_project_dir({"project_id": project_dir.name, "root_dir": str(tmp_path)})

    assert resolved == project_dir.resolve()
    tool._validate_project_marker(resolved)


@pytest.mark.parametrize("project_id", ["../sibling", "valid/../sibling"])
def test_project_path_traversal_is_rejected(
    tool: Multishot, tmp_path: Path, project_id: str
) -> None:
    with pytest.raises(ValueError, match="Unsafe project_id"):
        tool._get_project_dir({"project_id": project_id, "root_dir": str(tmp_path)})


def test_sibling_prefix_cannot_escape_resolved_root(tool: Multishot, tmp_path: Path) -> None:
    root_dir = tmp_path / "projects"
    sibling_dir = tmp_path / "projects_evil"
    sibling_dir.mkdir()

    resolved = tool._get_project_dir({"project_id": "project", "root_dir": str(root_dir)})

    assert resolved == (root_dir / "project").resolve()
    assert not resolved.is_relative_to(sibling_dir.resolve())


def test_existing_project_symlink_is_rejected_without_following_it(
    tool: Multishot, tmp_path: Path
) -> None:
    root_dir = tmp_path / "projects"
    target_dir = tmp_path / "outside"
    root_dir.mkdir()
    target_dir.mkdir()
    (root_dir / "linked").symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        tool._get_project_dir({"project_id": "linked", "root_dir": str(root_dir)})

    assert not (target_dir / "project.json").exists()


def test_init_does_not_follow_existing_project_symlink(
    tool: Multishot, tmp_path: Path
) -> None:
    root_dir = tmp_path / "projects"
    target_dir = tmp_path / "outside"
    root_dir.mkdir()
    target_dir.mkdir()
    (root_dir / "linked").symlink_to(target_dir, target_is_directory=True)

    result = tool.execute(
        {
            "operation": "init",
            "project_id": "linked",
            "root_dir": str(root_dir),
            "planning_artifacts": {"request": {}},
        }
    )

    assert not result.success
    assert "symlink" in result.error.lower()
    assert not (target_dir / "project.json").exists()


@pytest.mark.parametrize(
    ("marker", "message"),
    [
        ({"project_id": "other", "pipeline_type": "multi-shot"}, "identity"),
        ({"project_id": "project", "pipeline_type": "animated-explainer"}, "identity"),
    ],
)
def test_marker_identity_and_pipeline_must_match(
    tool: Multishot, tmp_path: Path, marker: dict[str, str], message: str
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "project.json").write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        tool._validate_project_marker(project_dir)


def test_malformed_marker_is_rejected(tool: Multishot, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "project.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="readable JSON"):
        tool._validate_project_marker(project_dir)
