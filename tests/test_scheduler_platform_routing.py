from pathlib import Path

from scripts import publish_active_projects, publish_slot


def test_instagram_slot_command_calls_manual_authority_for_instagram_only(tmp_path):
    project_dir = tmp_path / "cand-example"

    assert publish_slot.build_publish_command(project_dir) == [
        str(publish_slot.PYTHON),
        str(publish_slot.MANUAL_PUBLISHER),
        str(project_dir),
        "--only-platform",
        "instagram",
    ]


def test_active_project_slot_publisher_uses_instagram_slot_runner(tmp_path):
    project_dir = tmp_path / "cand-example"

    assert publish_active_projects.PUBLISHER.name == "publish_slot.py"
    assert publish_active_projects.build_publish_command(project_dir) == [
        str(publish_active_projects.PYTHON),
        str(publish_active_projects.PUBLISHER),
        str(project_dir),
    ]
