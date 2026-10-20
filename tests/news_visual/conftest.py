"""Shared test fixtures for news visual pipeline tests.

All fixtures are strictly synthetic and isolated. Marked NOT_FOR_PUBLICATION.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Generator
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def demo_brief(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "demo_brief.json").read_text(encoding="utf-8"))


@pytest.fixture
def demo_script(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "demo_script_vi.json").read_text(encoding="utf-8"))


@pytest.fixture
def approved_claims(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "approved_test_claims.json").read_text(encoding="utf-8"))


@pytest.fixture
def rejected_claims(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "rejected_test_claims.json").read_text(encoding="utf-8"))


@pytest.fixture
def isolated_project(tmp_path: Path, demo_brief: dict[str, Any], demo_script: dict[str, Any]) -> Generator[Path, None, None]:
    """Create a fully initialized, safe, offline, synthetic project directory."""
    project_dir = tmp_path / "cand_test_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "assets" / "visuals").mkdir(parents=True, exist_ok=True)
    (project_dir / "hyperframes" / "assets").mkdir(parents=True, exist_ok=True)
    (project_dir / "hyperframes_reels" / "assets").mkdir(parents=True, exist_ok=True)
    (project_dir / "renders").mkdir(parents=True, exist_ok=True)

    # project.json
    (project_dir / "project.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "cand_test_project",
            "title": "DemoNode X (Synthetic Test)",
            "pipeline_type": "daily-news",
            "classification": "SYNTHETIC_NOT_FOR_PUBLICATION"
        }, indent=2),
        encoding="utf-8"
    )

    # research_brief.json
    (artifacts_dir / "research_brief.json").write_text(
        json.dumps(demo_brief, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # script_vi.json
    (artifacts_dir / "script_vi.json").write_text(
        json.dumps(demo_script, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # frozen source file
    source_content = (
        "DemoNode X là thiết bị máy tính AI cá nhân cục bộ. "
        "Thiết bị tích hợp NPU với băng thông bộ nhớ đồng nhất và suy luận ngoại tuyến."
    )
    source_file = project_dir / "assets" / "source_test_01.txt"
    source_file.write_text(source_content, encoding="utf-8")
    source_sha = hashlib.sha256(source_content.encode("utf-8")).hexdigest()

    # news_evidence.json
    script_bytes = (artifacts_dir / "script_vi.json").read_bytes()
    script_sha = hashlib.sha256(script_bytes).hexdigest()
    evidence_data = {
        "version": "2.0",
        "script_sha256": script_sha,
        "sources": [
            {
                "id": "source-test-01",
                "url": "https://example.com/test/source-1",
                "status": "available",
                "published_at": "2026-10-19T00:00:00+00:00",
                "retrieved_at": "2026-10-20T00:00:00+00:00",
                "content_path": "assets/source_test_01.txt",
                "content_sha256": source_sha,
                "excerpt": "DemoNode X là thiết bị máy tính AI cá nhân cục bộ."
            }
        ],
        "claims": [
            {
                "id": "claim-01",
                "section_id": "intro",
                "claim": "DemoNode X vận hành mô hình ngôn ngữ lớn cục bộ hoàn toàn ngoại tuyến",
                "classification": "reported_fact",
                "consequential": True,
                "authority_attested": True,
                "review_status": "approved",
                "reviewer": "test_editorial_reviewer",
                "reviewed_at": "2026-10-20T10:00:00+00:00",
                "sources": ["source-test-01"]
            }
        ],
        "contradictions": []
    }
    (artifacts_dir / "news_evidence.json").write_text(
        json.dumps(evidence_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    yield project_dir
