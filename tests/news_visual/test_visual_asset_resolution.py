"""T03, T04, T11: Verify visual asset plan and asset resolver contracts.

Baseline failure (RED):
lib/news_visual package does not exist yet.
Schemas schemas/news/news_visual_plan.schema.json and schemas/news/news_visual_assets.schema.json
do not exist yet.
Missing asset resolution and safety validation logic before render.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_t03_visual_plan_and_assets_schemas_exist():
    """T03: Schemas for news_visual_plan and news_visual_assets must exist (R3, R5)."""
    plan_schema_path = ROOT / "schemas" / "news" / "news_visual_plan.schema.json"
    assets_schema_path = ROOT / "schemas" / "news" / "news_visual_assets.schema.json"

    assert plan_schema_path.is_file(), (
        "FAIL: schemas/news/news_visual_plan.schema.json does not exist. "
        "Missing typed visual plan schema."
    )
    assert assets_schema_path.is_file(), (
        "FAIL: schemas/news/news_visual_assets.schema.json does not exist. "
        "Missing typed visual assets manifest schema."
    )


def test_t03_lib_news_visual_module_exists():
    """T03: lib/news_visual module must provide plan contract and resolver (R3)."""
    try:
        import lib.news_visual.plan_contract as plan_contract
        import lib.news_visual.asset_resolver as asset_resolver
    except ImportError as e:
        pytest.fail(f"FAIL: lib.news_visual module is missing: {e}")


def test_t04_asset_resolver_rejects_path_traversal(tmp_path: Path):
    """T04: Asset resolver must reject path traversal or files outside workspace."""
    try:
        from lib.news_visual.asset_resolver import validate_asset_file
    except ImportError:
        pytest.fail("FAIL: lib.news_visual.asset_resolver not implemented.")


def test_t11_asset_resolver_fault_handling():
    """T11: Asset resolver must handle retry and interrupted states safely."""
    try:
        from lib.news_visual.asset_resolver import resolve_visual_assets
    except ImportError:
        pytest.fail("FAIL: lib.news_visual.asset_resolver not implemented.")
