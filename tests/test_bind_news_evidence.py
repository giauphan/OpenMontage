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


def test_bind_news_evidence_fixes_missing_section_ids(tmp_path: Path):
    project_dir = tmp_path / "cand_missing_ids"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    script_data = {
        "version": "1.0",
        "title": "Bản tin không có section id",
        "sections": [
            {"text_vi": "Đoạn 1 không có id."},
            {"id": "", "text_vi": "Đoạn 2 id rỗng."},
            {"id": "custom_3", "text_vi": "Đoạn 3 có id."},
        ],
    }
    (artifacts_dir / "script_vi.json").write_text(json.dumps(script_data, ensure_ascii=False), encoding="utf-8")
    (artifacts_dir / "research_brief.json").write_text(json.dumps({"topic": "Tin mới"}), encoding="utf-8")
    (project_dir / "project.json").write_text(json.dumps({"pipeline_type": "newsnow"}), encoding="utf-8")

    assert bind_news_evidence(project_dir) is True
    val_res = validate_news_evidence(project_dir, 24.0)
    assert val_res["ok"] is True
    assert not val_res["errors"]


def test_bind_news_evidence_rejects_unsubstantiated_en_us_figures_and_never_copies_script(tmp_path: Path):
    project_dir = tmp_path / "cand_en_us_unverified"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    script_data = {
        "version": "1.0",
        "title": "AI Desktop Agents",
        "total_duration_seconds": 70.0,
        "sections": [
            {
                "id": "sec_1",
                "text": "Multimodal desktop agents cut UI recognition errors below 12% across benchmarks.",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
            },
            {
                "id": "sec_2",
                "text": "However, 78% of unverified enterprise deployments fail within 99 hours.",
                "start_seconds": 10.0,
                "end_seconds": 20.0,
            },
        ],
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script_data, indent=2), encoding="utf-8")

    brief_data = {
        "version": "1.0",
        "topic": "AI Desktop Operating Layers",
        "data_points": [
            {
                "claim": "Recent desktop benchmarks report UI-recognition error rates below 12%.",
                "source_url": "https://arxiv.org/abs/2401.00001",
                "credibility": "high",
            }
        ],
        "sources": [
            {
                "url": "https://arxiv.org/abs/2401.00001",
                "title": "Desktop Agent Benchmark Paper",
                "used_for": "Benchmark error rate",
            }
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief_data, indent=2), encoding="utf-8")

    # Must fail closed because 78% and 99 are not in research_brief.json
    assert bind_news_evidence(project_dir) is False

    # Verify source_evidence_s1.txt NEVER contains the script's own prose
    snap_text = (artifacts_dir / "source_evidence_s1.txt").read_text(encoding="utf-8")
    assert "78% of unverified enterprise deployments" not in snap_text
    assert "Multimodal desktop agents cut UI recognition errors" not in snap_text

    # Verify claim_ledger.json records C001 as APPROVED and C002 as REJECTED/unverified
    ledger = json.loads((artifacts_dir / "claim_ledger.json").read_text(encoding="utf-8"))
    claims_by_id = {c["claim_id"]: c for c in ledger["claims"]}
    assert claims_by_id["C001"]["verdict"] == "APPROVED"
    assert claims_by_id["C001"]["confidence"] == "verified"
    assert claims_by_id["C002"]["verdict"] == "REJECTED"
    assert claims_by_id["C002"]["confidence"] == "unverified"


def test_bind_news_evidence_approves_grounded_en_us_script(tmp_path: Path):
    project_dir = tmp_path / "cand_en_us_verified"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    script_data = {
        "version": "1.0",
        "title": "AI Desktop Agents",
        "total_duration_seconds": 70.0,
        "sections": [
            {
                "id": "sec_1",
                "text": "Multimodal desktop agents cut UI recognition errors below 12% across benchmarks.",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
            },
            {
                "id": "sec_2",
                "text": "Structured supervisor checkpoints bound rollback recovery within 50 milliseconds.",
                "start_seconds": 10.0,
                "end_seconds": 20.0,
            },
        ],
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script_data, indent=2), encoding="utf-8")

    brief_data = {
        "version": "1.0",
        "topic": "AI Desktop Operating Layers",
        "data_points": [
            {
                "claim": "Recent desktop benchmarks report UI-recognition error rates below 12% and recovery under 50 milliseconds.",
                "source_url": "https://arxiv.org/abs/2401.00001",
                "credibility": "high",
            }
        ],
        "sources": [
            {
                "url": "https://arxiv.org/abs/2401.00001",
                "title": "Desktop Agent Benchmark Paper",
                "used_for": "Benchmark error rate",
            }
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief_data, indent=2), encoding="utf-8")

    assert bind_news_evidence(project_dir) is True
    snap_text = (artifacts_dir / "source_evidence_s1.txt").read_text(encoding="utf-8")
    assert "Multimodal desktop agents cut UI recognition errors" not in snap_text
    assert "Recent desktop benchmarks report UI-recognition error rates below 12%" in snap_text
    val_res = validate_news_evidence(project_dir, 24.0)
    assert val_res["ok"] is True


def test_bind_news_evidence_rejects_non_numeric_ungrounded_claims(tmp_path: Path):
    project_dir = tmp_path / "cand_en_us_ungrounded_prose"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    script_data = {
        "version": "1.0",
        "title": "AI Desktop Operating Systems",
        "total_duration_seconds": 70.0,
        "sections": [
            {
                "id": "sec_1",
                "text": "Multimodal desktop agents streamline workflow automation across platforms.",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
            },
            {
                "id": "sec_2",
                # Completely ungrounded claim with NO numbers
                "text": "Astronauts discovered ancient fossilized pyramids on Mars yesterday afternoon.",
                "start_seconds": 10.0,
                "end_seconds": 20.0,
            },
        ],
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script_data, indent=2), encoding="utf-8")

    brief_data = {
        "version": "1.0",
        "topic": "AI Desktop Operating Layers",
        "data_points": [
            {
                "claim": "Multimodal desktop agents streamline workflow automation across modern platforms.",
                "source_url": "https://arxiv.org/abs/2401.00001",
                "credibility": "high",
            }
        ],
        "sources": [
            {
                "url": "https://arxiv.org/abs/2401.00001",
                "title": "Desktop Agent Benchmark Paper",
                "used_for": "Workflow automation",
            }
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief_data, indent=2), encoding="utf-8")

    # Must fail closed because the Mars claim has no grounding in the research brief
    assert bind_news_evidence(project_dir) is False

    # Check ledger recorded C002 as REJECTED
    ledger = json.loads((artifacts_dir / "claim_ledger.json").read_text(encoding="utf-8"))
    claims_by_id = {c["claim_id"]: c for c in ledger["claims"]}
    assert claims_by_id["C001"]["verdict"] == "APPROVED"
    assert claims_by_id["C002"]["verdict"] == "REJECTED"
    assert claims_by_id["C002"]["confidence"] == "unverified"


def test_bind_news_evidence_approves_cta_opinion_section(tmp_path: Path):
    project_dir = tmp_path / "cand_en_us_cta"
    artifacts_dir = project_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)

    script_data = {
        "version": "1.0",
        "title": "AI Agent Engineering Patterns",
        "total_duration_seconds": 70.0,
        "sections": [
            {
                "id": "s1",
                "text": "Multimodal desktop agents cut UI recognition errors below 12% across benchmarks.",
                "start_seconds": 0.0,
                "end_seconds": 35.0,
            },
            {
                "id": "s2",
                "text": "Follow for daily AI agent engineering patterns, and star the repo for the complete defensive blueprint.",
                "start_seconds": 35.0,
                "end_seconds": 70.0,
            },
        ],
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script_data, indent=2), encoding="utf-8")

    brief_data = {
        "version": "1.0",
        "topic": "AI Desktop Operating Layers",
        "data_points": [
            {
                "claim": "Recent desktop benchmarks report UI-recognition error rates below 12%.",
                "source_url": "https://arxiv.org/abs/2401.00001",
                "credibility": "high",
            }
        ],
        "sources": [
            {
                "url": "https://arxiv.org/abs/2401.00001",
                "title": "Desktop Agent Benchmark Paper",
                "used_for": "Benchmark error rate",
            }
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief_data, indent=2), encoding="utf-8")

    assert bind_news_evidence(project_dir) is True

    evidence = json.loads((artifacts_dir / "news_evidence.json").read_text(encoding="utf-8"))
    c2 = next(c for c in evidence["claims"] if c["section_id"] == "s2")
    assert c2["classification"] == "opinion"
    assert c2["review_status"] == "approved"

    ledger = json.loads((artifacts_dir / "claim_ledger.json").read_text(encoding="utf-8"))
    claims_by_id = {c["claim_id"]: c for c in ledger["claims"]}
    assert claims_by_id["C002"]["verdict"] == "APPROVED"
    assert claims_by_id["C002"]["confidence"] == "verified"

    val_res = validate_news_evidence(project_dir, 24.0)
    assert val_res["ok"] is True


def test_bind_news_evidence_extracted_json_capture_hash_and_long_excerpt(tmp_path: Path, monkeypatch):
    import hashlib
    monkeypatch.setenv("REQUIRE_AUTHENTIC_CAPTURES", "1")
    project_dir = tmp_path / "cand_en_us_capture_json"
    artifacts_dir = project_dir / "artifacts"
    capture_dir = artifacts_dir / "news_source_capture"
    capture_dir.mkdir(parents=True)

    # Simulate 4200 chars of HTML navigation header before the README content with figures
    nav_header = ("Navigation Menu\nSign in\nProducts\n" * 130)[:4200]
    readme_body = (
        "\nAuto Ontology is a Python framework for semantic layers over enterprise data.\n"
        "Inference runs through NVIDIA NIM using Nemotron 3.5 Lightning 30B for reasoning.\n"
    )
    cap_file = capture_dir / "834f867a45207691-test.extracted.json"
    cap_bytes = (json.dumps({"text": nav_header + readme_body}, indent=2) + "\n").encode("utf-8")
    cap_file.write_bytes(cap_bytes)
    expected_file_sha = hashlib.sha256(cap_bytes).hexdigest()

    script_data = {
        "version": "1.0",
        "title": "NVIDIA Auto Ontology",
        "total_duration_seconds": 65.0,
        "sections": [
            {
                "id": "sec-1",
                "text": "NVIDIA Auto Ontology uses Nemotron 3.5 Lightning 30B for reasoning over enterprise data.",
                "start_seconds": 0.0,
                "end_seconds": 65.0,
            }
        ],
    }
    (artifacts_dir / "script_en_US.json").write_text(json.dumps(script_data, indent=2), encoding="utf-8")
    brief_data = {
        "version": "1.0",
        "topic": "NVIDIA Auto Ontology",
        "sources": [
            {
                "url": "https://github.com/NVIDIA/auto-ontology/blob/main/README.md",
                "title": "NVIDIA Auto Ontology README",
                "used_for": "Architecture and model defaults",
            }
        ],
    }
    (artifacts_dir / "research_brief.json").write_text(json.dumps(brief_data, indent=2), encoding="utf-8")

    assert bind_news_evidence(project_dir) is True
    ledger = json.loads((artifacts_dir / "claim_ledger.json").read_text(encoding="utf-8"))
    claim = ledger["claims"][0]
    assert claim["source"]["snapshot_file"] == "news_source_capture/834f867a45207691-test.extracted.json"
    assert claim["source"]["snapshot_sha256"] == expected_file_sha
    assert "3.5" in claim["evidence_excerpt"]

