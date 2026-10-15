from __future__ import annotations

import json
from pathlib import Path
from scripts.bind_news_evidence import bind_news_evidence
from lib.news_evidence import validate_news_evidence
from lib.news_release_gate import require_news_evidence


def test_bind_news_evidence_satisfies_all_gates(tmp_path: Path):
    project_dir = tmp_path / "cand_test_bind"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    script_data = {
        "version": "1.0",
        "title": "Bản tin AI cập nhật",
        "total_duration_seconds": 45.0,
        "sections": [
            {"id": "sec_0", "text_vi": "Chào mừng quý vị đến với tin tức công nghệ mới nhất.", "start_seconds": 0.0, "end_seconds": 15.0},
            {"id": "sec_1", "text_vi": "Hôm nay chúng ta tìm hiểu công nghệ sandbox cách ly an toàn.", "start_seconds": 15.0, "end_seconds": 30.0},
            {"id": "sec_2", "text_vi": "Đây là giải pháp đột phá cho lập trình viên toàn cầu.", "start_seconds": 30.0, "end_seconds": 45.0},
        ],
    }
    (artifacts_dir / "script_vi.json").write_text(json.dumps(script_data, ensure_ascii=False), encoding="utf-8")

    brief_data = {
        "version": "1.0",
        "topic": "Khám phá AI Sandboxes mới",
        "sources": [
            {"url": "https://news.ycombinator.com/item?id=123", "title": "Hacker News AI Discussion", "used_for": "Bối cảnh"},
            {"url": "https://github.com/features/actions", "title": "GitHub Isolation Tech", "used_for": "Kiểm chứng kỹ thuật"},
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief_data, ensure_ascii=False), encoding="utf-8")
    (project_dir / "project.json").write_text(json.dumps({"pipeline_type": "newsnow"}), encoding="utf-8")

    assert bind_news_evidence(project_dir) is True
    assert (artifacts_dir / "news_evidence.json").is_file()

    # Validate against lib.news_evidence
    val_res = validate_news_evidence(project_dir, 24.0)
    assert val_res["ok"] is True
    assert not val_res["errors"]

    # Validate against lib.news_release_gate
    rel_res = require_news_evidence(project_dir, "24")
    assert rel_res["ok"] is True
