from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.materialize_news_template import materialize, load_package_schema, validate_content
from tools.news import template_provenance


def _fixture(name: str, pkg: str = "news-debate") -> dict:
    path = ROOT / "templates" / "news" / "packages" / pkg / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_catalog_integrity_hashes_match_package_files() -> None:
    """Catalog integrity fields must be real hashes of the committed package HTML."""
    catalog = template_provenance.load_catalog()
    pkgs = {p["id"]: p for p in catalog["packages"]}
    assert set(pkgs) == {"news-debate", "news-evidence", "news-explainer"}
    for pid, pkg in pkgs.items():
        full = ROOT / "templates" / "news" / pkg["package_dir"] / "hyperframes" / "index.html"
        short = ROOT / "templates" / "news" / pkg["package_dir"] / "hyperframes_reels" / "index.html"
        expected_full = hashlib.sha256(full.read_bytes()).hexdigest()
        expected_short = hashlib.sha256(short.read_bytes()).hexdigest()
        assert pkg["integrity"]["full_html_sha256"] == expected_full, f"{pid} full hash stale"
        assert pkg["integrity"]["short_html_sha256"] == expected_short, f"{pid} short hash stale"


def test_materialization_is_byte_stable(tmp_path: Path) -> None:
    """Same content + variant must produce byte-identical compositions and provenance."""
    content = _fixture("full_story_1.json")
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    prov1 = materialize("news-debate", content, out1, "both")
    prov2 = materialize("news-debate", content, out2, "both")
    assert prov1["full_html_sha256"] == prov2["full_html_sha256"]
    assert prov1["reels_html_sha256"] == prov2["reels_html_sha256"]
    assert prov1["content_instance_sha256"] == prov2["content_instance_sha256"]
    # Byte-identical files on disk
    assert (out1 / "hyperframes" / "index.html").read_bytes() == (out2 / "hyperframes" / "index.html").read_bytes()
    assert (out1 / "hyperframes_reels" / "index.html").read_bytes() == (out2 / "hyperframes_reels" / "index.html").read_bytes()


def test_valid_content_materializes_with_verified_captions(tmp_path: Path) -> None:
    content = _fixture("full_story_1.json")
    proj = tmp_path / "proj"
    prov = materialize("news-debate", content, proj, "both")
    assert prov["caption_display_verified"] is True
    # Provenance verification passes on the freshly materialized project
    verified = template_provenance.verify_project_provenance(proj)
    assert verified["ok"] is True, verified["reasons"]
    assert verified["template_id"] == "news-debate"


@pytest.mark.parametrize("pkg,fixture", [
    ("news-debate", "full_story_1.json"),
    ("news-debate", "short_story_1.json"),
    ("news-evidence", "full_story_1.json"),
    ("news-explainer", "full_story_1.json"),
])
def test_each_package_fixture_passes_schema(tmp_path: Path, pkg: str, fixture: str) -> None:
    content = _fixture(fixture, pkg)
    validate_content(content, pkg)  # should not raise
    prov = materialize(pkg, content, tmp_path / pkg, "both")
    assert prov["caption_display_verified"] is True


def test_schema_rejects_missing_required_slots(tmp_path: Path) -> None:
    content = _fixture("full_story_1.json")
    content.pop("slots")
    with pytest.raises(ValueError):
        validate_content(content, "news-debate")


def test_schema_rejects_malformed_media_src() -> None:
    content = _fixture("full_story_1.json")
    content["media"] = [{"src": "https://evil.com/x.mp4", "start": 0, "end": 1}]
    with pytest.raises(ValueError):
        validate_content(content, "news-debate")


def test_schema_rejects_short_variant_over_duration_cap() -> None:
    content = _fixture("short_story_1.json")
    content["variant"] = "short"
    content["duration"] = 59.0  # > 58s cap
    with pytest.raises(ValueError):
        validate_content(content, "news-debate")


def test_short_variant_requires_narration_short() -> None:
    content = _fixture("full_story_1.json")
    content["variant"] = "short"
    content["duration"] = 30
    content.pop("narration_short", None)
    with pytest.raises(ValueError):
        validate_content(content, "news-debate")


def test_stale_provenance_is_rejected(tmp_path: Path) -> None:
    """If composition bytes change after record_provenance, verification must fail."""
    content = _fixture("full_story_1.json")
    proj = tmp_path / "proj"
    prov = materialize("news-debate", content, proj, "both")
    assert template_provenance.verify_project_provenance(proj)["ok"] is True

    # Tamper: append a comment to the full composition.
    full = proj / "hyperframes" / "index.html"
    full.write_text(full.read_text() + "<!-- tampered -->\n", encoding="utf-8")
    verified = template_provenance.verify_project_provenance(proj)
    assert verified["ok"] is False
    assert any("full composition hash mismatch" in r for r in verified["reasons"])


def test_missing_provenance_is_rejected(tmp_path: Path) -> None:
    proj = tmp_path / "empty"
    proj.mkdir()
    verified = template_provenance.verify_project_provenance(proj)
    assert verified["ok"] is False
    assert any("missing" in r for r in verified["reasons"])


def test_unknown_template_id_is_rejected(tmp_path: Path) -> None:
    content = _fixture("full_story_1.json")
    proj = tmp_path / "proj"
    materialize("news-debate", content, proj, "both")
    # Overwrite template_id with an unapproved value, keep everything else.
    ppath = proj / "template_provenance.json"
    data = json.loads(ppath.read_text(encoding="utf-8"))
    data["template_id"] = "news-bogus"
    ppath.write_text(json.dumps(data), encoding="utf-8")
    verified = template_provenance.verify_project_provenance(proj)
    assert verified["ok"] is False
    assert any("unknown template_id" in r for r in verified["reasons"])


def test_non_vietnamese_caption_is_rejected(tmp_path: Path) -> None:
    """Materializer + provenance must flag captions that are not Vietnamese."""
    content = _fixture("full_story_1.json")
    content["caption_lines"] = [
        {"text": "This is definitely English, not Vietnamese", "start": 0, "end": 10},
        {"text": "Also English filler caption", "start": 10, "end": 20},
        {"text": "Third English line too", "start": 20, "end": 30},
    ]
    prov = materialize("news-debate", content, tmp_path / "proj", "full")
    assert prov["caption_display_verified"] is False


def test_data_label_caption_is_allowed(tmp_path: Path) -> None:
    """Numeric/metric labels are acceptable without Vietnamese prose (data-label carve-out)."""
    content = _fixture("full_story_1.json")
    content["caption_lines"] = [
        {"text": "70% doanh nghiệp", "start": 0, "end": 10},
        {"text": "+47% so với 2024", "start": 10, "end": 20},
        {"text": "1.6x mức trung bình", "start": 20, "end": 30},
    ]
    prov = materialize("news-debate", content, tmp_path / "proj", "full")
    assert prov["caption_display_verified"] is True
