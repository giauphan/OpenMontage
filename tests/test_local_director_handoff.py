import json
from pathlib import Path

import pytest


def _director_module():
    try:
        from scripts import local_director_handoff
    except ImportError:
        pytest.fail("local director handoff is not implemented")
    return local_director_handoff


def test_director_handoff_installs_only_returned_project_artifacts(tmp_path, monkeypatch):
    module = _director_module()
    project = tmp_path / "projects" / "cand_1"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "research_brief.json").write_text('{"title":"test"}')
    files = {"artifacts/script_vi.json": '{"title":"test"}',
             "hyperframes/index.html": "<main>full</main>",
             "hyperframes_reels/index.html": "<main>short</main>"}
    seen = []
    monkeypatch.setattr(module, "request_local_agent", lambda root, kind, payload, **kwargs: seen.append(payload) or {"files": files})
    module.run_director_handoff(project, tmp_path / "requests", "generate", "system", timeout_seconds=2)
    assert (project / "hyperframes" / "index.html").read_text() == "<main>full</main>"
    assert json.loads((project / "artifacts" / "script_vi.json").read_text())["title"] == "test"
    assert json.loads(seen[0]["research_brief"])["title"] == "test"


def test_director_handoff_rejects_paths_outside_project(tmp_path, monkeypatch):
    module = _director_module()
    project = tmp_path / "projects" / "cand_1"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "research_brief.json").write_text("{}")
    monkeypatch.setattr(module, "request_local_agent", lambda *args, **kwargs: {"files": {"../../application.py": "bad"}})
    with pytest.raises(module.HandoffError, match="artifact"):
        module.run_director_handoff(project, tmp_path / "requests", "generate", "system", timeout_seconds=2)
    assert not (tmp_path / "application.py").exists()


def test_director_handoff_includes_captured_source_text(tmp_path, monkeypatch):
    module = _director_module()
    project = tmp_path / "cand_1"
    captures = project / "artifacts" / "news_source_capture"
    captures.mkdir(parents=True)
    (project / "artifacts" / "research_brief.json").write_text('{}')
    (captures / "source.extracted.json").write_text(json.dumps({"text": "Git worktrees use separate working directories."}))
    seen = []
    monkeypatch.setattr(module, "request_local_agent", lambda root, kind, payload, **kwargs: seen.append(payload) or {"files": {"artifacts/script.json": "{}"}})
    module.run_director_handoff(project, tmp_path / "requests", "generate", "system", timeout_seconds=2)
    assert "Git worktrees use separate working directories." in seen[0]["captured_source_text"]


def test_director_handoff_rejects_symlinked_output_directory(tmp_path, monkeypatch):
    module = _director_module()
    project = tmp_path / "projects" / "cand_1"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "research_brief.json").write_text("{}")
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "hyperframes").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(module, "request_local_agent", lambda *args, **kwargs: {"files": {"hyperframes/index.html": "bad"}})
    with pytest.raises(module.HandoffError, match="artifact"):
        module.run_director_handoff(project, tmp_path / "requests", "generate", "system", timeout_seconds=2)
    assert not (outside / "index.html").exists()
