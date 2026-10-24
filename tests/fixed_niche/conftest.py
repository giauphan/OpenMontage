"""Pytest configuration and shared fixtures for fixed niche tests."""
import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES_PATH = ROOT / "tests/fixtures/fixed_niche_cases.yaml"
LOCKED_POLICY_PATH = ROOT / "config/niches/us-ai-agent-engineering.locked.yaml"
LOCKED_SCHEMA_PATH = ROOT / "schemas/niches/locked_niche.schema.json"


@pytest.fixture(autouse=True)
def set_offline_env(monkeypatch):
    """Ensure tests run strictly offline with no external telemetry or publishing."""
    monkeypatch.setenv("WANDB_MODE", "offline")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("FIXED_NICHE_ALLOW_PUBLISH", "0")
    monkeypatch.setenv("FIXED_NICHE_OUTPUT_VISIBILITY", "private")
