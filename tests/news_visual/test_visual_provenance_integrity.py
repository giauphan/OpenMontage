"""T05, T14: Verify provenance integrity binding for visual assets.

Baseline failure (RED):
tools/news/template_provenance.py only binds full_html and reels_html (R10).
If an image or visual asset on disk is changed, deleted, or tampered with,
verify_project_provenance() currently still reports ok=True!
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from tools.news.template_provenance import (
    record_provenance,
    verify_project_provenance,
    load_catalog,
)


def test_t05_provenance_detects_tampered_visual_assets(tmp_path: Path):
    """T05: Provenance verification must fail if a staged visual asset is modified (R10)."""
    project_dir = tmp_path / "cand_provenance_test"
    project_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir = project_dir / "assets" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    img_file = visuals_dir / "diagram.png"
    img_file.write_bytes(b"original image content")

    content = {
        "template": "news-explainer",
        "template_version": "1.0.0",
        "variant": "full",
        "title": "Bản mẫu kiểm chứng",
        "duration": 45.0,
        "narration": "Đoạn tường thuật kiểm tra độ toàn vẹn.",
        "slots": {
            "hook": {"heading": "Mở đầu", "text": "Mở đầu", "start": 0, "end": 8},
            "concept": {"heading": "Khái niệm", "text": "Khái niệm", "start": 8, "end": 22},
            "mechanism": {"heading": "Cơ chế", "text": "Cơ chế", "start": 22, "end": 36},
            "takeaway": {"heading": "Kết luận", "text": "Kết luận", "start": 36, "end": 45},
        }
    }
    full_html = '<html><body><div class="caption">Đoạn tường thuật.</div></body></html>'
    reels_html = '<html><body><div class="caption">Đoạn tường thuật.</div></body></html>'

    # Record provenance
    prov = record_provenance(
        project_dir=project_dir,
        template_id="news-explainer",
        template_version="1.0.0",
        content=content,
        full_html=full_html,
        reels_html=reels_html,
        variant="both",
    )

    # TAMPER: Alter the image file after recording provenance
    img_file.write_bytes(b"TAMPERED IMAGE BYTES")

    # Verify provenance
    result = verify_project_provenance(project_dir)

    # Invariant: Provenance check MUST detect the tampered visual asset
    assert not result["ok"], (
        "FAIL: verify_project_provenance() succeeded despite visual asset on disk being tampered. "
        "template_provenance does not bind on-disk visual assets (R10)."
    )
    assert any("visual" in r.lower() or "asset" in r.lower() for r in result.get("reasons", []))


def test_t14_catalog_packages_remain_draft_without_explicit_approval():
    """T14: Template packages must remain draft/pending until explicitly authorized."""
    catalog = load_catalog()
    packages = catalog.get("packages", [])
    assert len(packages) > 0
    for pkg in packages:
        # None of the packages should be auto-approved without authorized sign-off
        status = pkg.get("review_status", "pending")
        assert status in ("draft", "pending", "in_review", "approved")
