"""Root test configuration and test isolation fixtures."""

import os
import pytest


@pytest.fixture(autouse=True)
def _isolate_platform_config(monkeypatch):
    """Isolate tests from repository publish_platforms.json unless explicitly tested."""
    if "OPENMONTAGE_PLATFORMS_CONFIG" not in os.environ and "ENABLED_PLATFORMS" not in os.environ:
        monkeypatch.setenv("OPENMONTAGE_PLATFORMS_CONFIG", "/nonexistent_for_tests/publish_platforms.json")
