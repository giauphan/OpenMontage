"""QA helper contracts: source metadata is never copied into fixture bundles."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.qa_daily_news_replay import _prepare_case, _valid_review_reply


def test_prepare_case_uses_synthetic_metadata_and_ignores_secret_source_metadata(tmp_path: Path):
    project = tmp_path / "historical-project"
    (project / "artifacts").mkdir(parents=True)
    (project / "hyperframes").mkdir()
    (project / "renders").mkdir()
    (project / "artifacts/script_vi.json").write_text(
        json.dumps({"sections": [{"text": "HISTORICAL SAMPLE; NOT FACT-CHECKED"}]}),
        encoding="utf-8",
    )
    (project / "hyperframes/index.html").write_text("<main>historical technical sample</main>", encoding="utf-8")
    video = project / "renders/historical_full.mp4"
    video.write_bytes(b"unit-fixture-media-bytes; not a video")
    secret = "SYNTHETIC_SHOULD_NEVER_BE_COPIED_TOKEN_12345"
    source_metadata = project / "publish_metadata.json"
    source_metadata.write_text(json.dumps({"api_token": secret}), encoding="utf-8")

    manifest, copy_scope = _prepare_case(
        tmp_path / "case",
        project_root=project,
        video_source=video,
        video_relative=Path("renders/historical_full.mp4"),
        reviewer_reply=_valid_review_reply(),
    )

    fixture_project = manifest.parent / "project"
    staged_metadata = json.loads((fixture_project / "metadata.json").read_text(encoding="utf-8"))
    assert staged_metadata == {
        "fixture_only": True,
        "title": "SYNTHETIC QA ONLY — NOT FOR PUBLICATION",
        "description": "Synthetic metadata used only to exercise the offline review parser.",
        "tags": ["SYNTHETIC TEST ONLY"],
    }
    staged_bytes = b"".join(path.read_bytes() for path in fixture_project.rglob("*") if path.is_file())
    assert secret.encode() not in staged_bytes
    assert json.loads(source_metadata.read_text(encoding="utf-8"))["api_token"] == secret
    assert copy_scope == [
        "OFFLINE_REHEARSAL_TEST_ONLY.json",
        "artifacts/script_vi.json",
        "hyperframes/index.html",
        "metadata.json",
        "renders/historical_full.mp4",
    ]
    assert not (fixture_project / "publish_metadata.json").exists()
