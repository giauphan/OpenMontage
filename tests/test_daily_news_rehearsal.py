from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PIPELINE = REPO / "scripts" / "run_daily_news_pipeline.sh"
HELPER = REPO / "scripts" / "prepare_daily_news_rehearsal.py"
ROOT_MARKER = {"test_only": True, "purpose": "daily-news-rehearsal"}
REVIEW = {
    "visual_quality": {"passed": True, "score": 4, "notes": "fixture only"},
    "audio_sync": {"passed": True, "score": 4, "notes": "fixture only"},
    "content_appropriateness": {"passed": True, "score": 4, "notes": "fixture only"},
    "brand_compliance": {"passed": True, "score": 4, "notes": "fixture only"},
    "overall_passed": True,
    "summary": "Synthetic reviewer reply",
}


def _isolated_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "staging"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(PIPELINE, scripts / PIPELINE.name)
    shutil.copy2(HELPER, scripts / HELPER.name)
    (root / ".openmontage-rehearsal-root.json").write_text(json.dumps(ROOT_MARKER), encoding="utf-8")
    return root


def _env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    env.pop("NEWS_MAX_SOURCE_AGE_HOURS", None)
    env.pop("PRODUCTION_RELEASE", None)
    env.pop("STRICT_PRODUCTION", None)
    env.update(extra)
    return env


def _run_pipeline(root: Path, *args: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / PIPELINE.name), *args],
        cwd=root,
        env=_env(**env_overrides),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_preparer(root: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / HELPER.name), "--manifest", str(manifest), "--root", str(root), "--max-source-age-hours", "24"],
        cwd=root,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _make_bundle(root: Path, index: int) -> dict[str, str]:
    project_id = f"fixture-project-{index}"
    bundle = root / "bundles" / project_id
    artifacts = bundle / "artifacts"
    assets = bundle / "assets"
    (artifacts).mkdir(parents=True)
    assets.mkdir()
    (bundle / "hyperframes").mkdir()
    (bundle / "hyperframes_reels").mkdir()
    docs = {
        "research_brief.json": {"topic": f"Fixture topic {index}"},
        "script_vi.json": {"sections": [{"text_vi": f"Nội dung kiểm thử {index}"}]},
        "proposal_packet.json": {"concept_options": []},
        "selector_reply.json": {
            "selected_candidate_id": f"candidate-{index}",
            "research_draft": {"title": f"Synthetic news topic {index}"},
        },
        "director_reply.json": {"is_error": False, "result": "fixture-only"},
        "reviewer_reply.json": REVIEW,
        "news_evidence.json": {"version": "2.0", "fixture_only": True},
    }
    for filename, document in docs.items():
        (artifacts / filename).write_text(json.dumps(document), encoding="utf-8")
    (assets / "narration.mp3").write_bytes(b"fixture narration bytes")
    (assets / "music-bg.mp3").write_bytes(b"fixture music bytes")
    (bundle / "hyperframes" / "index.html").write_text("<main>fixture full</main>", encoding="utf-8")
    (bundle / "hyperframes_reels" / "index.html").write_text("<main>fixture reels</main>", encoding="utf-8")
    return {"project_id": project_id, "project_dir": f"bundles/{project_id}"}


def _write_manifest(root: Path) -> Path:
    (root / "bundles").mkdir(exist_ok=True)
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"version": 1, "bundles": [_make_bundle(root, i) for i in range(1, 4)]}), encoding="utf-8")
    return manifest


def test_empty_manifest_argument_fails_immediately(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    sentinel = root / "env-was-sourced"
    (root / ".env").write_text(f"touch {sentinel}\n", encoding="utf-8")

    result = _run_pipeline(root, "--rehearsal-bundle", "", NEWS_MAX_SOURCE_AGE_HOURS="24")

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert not sentinel.exists()
    assert not (root / "logs").exists()


def test_missing_manifest_fails_before_env_or_live_acquisition(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    result = _run_pipeline(root, "--rehearsal-bundle", "missing.json", NEWS_MAX_SOURCE_AGE_HOURS="24")

    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert "news_pipeline_cli.py fetch" not in result.stdout + result.stderr
    assert not (root / "logs").exists()


def test_malformed_manifest_fails_before_live_acquisition(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    (root / "bad.json").write_text("{broken", encoding="utf-8")

    result = _run_pipeline(root, "--rehearsal-bundle", "bad.json", NEWS_MAX_SOURCE_AGE_HOURS="24")

    assert result.returncode != 0
    assert "cannot parse manifest" in result.stderr
    assert not (root / "logs").exists()
    assert not (root / "projects").exists()


def test_missing_or_invalid_freshness_fails_before_bundle_copy(tmp_path: Path):
    for value in (None, "nan", "0", "721"):
        root = _isolated_checkout(tmp_path / str(value))
        _write_manifest(root)
        overrides = {} if value is None else {"NEWS_MAX_SOURCE_AGE_HOURS": value}
        result = _run_pipeline(root, "--rehearsal-bundle", "manifest.json", **overrides)
        assert result.returncode == 2
        assert "NEWS_MAX_SOURCE_AGE_HOURS" in result.stderr
        assert not (root / "projects").exists()
        assert not (root / "logs").exists()


def test_production_mode_refuses_rehearsal_before_bundle_copy(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    _write_manifest(root)
    env = _env(NEWS_MAX_SOURCE_AGE_HOURS="24", PRODUCTION_RELEASE="1")
    result = subprocess.run(
        ["bash", str(root / "scripts" / PIPELINE.name), "--rehearsal-bundle", "manifest.json"],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "forbidden in production" in result.stderr
    assert not (root / "projects").exists()
    assert not (root / "logs").exists()


def test_dotenv_git_live_schedule_and_symlinked_root_are_refused(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    manifest = _write_manifest(root)
    (root / ".env").write_text("touch SHOULD_NOT_RUN\n", encoding="utf-8")
    result = _run_preparer(root, manifest)
    assert result.returncode == 2 and ".env" in result.stderr
    (root / ".env").unlink()

    (root / ".git").write_text("gitdir: /somewhere\n", encoding="utf-8")
    result = _run_preparer(root, manifest)
    assert result.returncode == 2 and "git checkout/worktree" in result.stderr
    (root / ".git").unlink()

    schedule = root / "config" / "publish_schedule.json"
    schedule.parent.mkdir()
    schedule.write_text("{}", encoding="utf-8")
    result = _run_preparer(root, manifest)
    assert result.returncode == 2 and "live publish schedule" in result.stderr
    schedule.unlink()

    link = tmp_path / "root-link"
    link.symlink_to(root, target_is_directory=True)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / HELPER.name), "--manifest", str(manifest), "--root", str(link), "--max-source-age-hours", "24"],
        cwd=root, env=_env(), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and "symlink" in result.stderr


def test_symlinked_manifest_or_bundle_is_refused(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    manifest = _write_manifest(root)
    manifest_link = root / "manifest-link.json"
    manifest_link.symlink_to(manifest)
    result = _run_preparer(root, manifest_link)
    assert result.returncode == 2 and "symlink" in result.stderr
    manifest_link.unlink()

    bundle = root / "bundles" / "fixture-project-1"
    (root / "bundles" / "linked-project").symlink_to(bundle, target_is_directory=True)
    manifest.write_text(json.dumps({"version": 1, "bundles": [
        {"project_id": f"p{i}", "project_dir": "bundles/linked-project"} for i in range(1, 4)
    ]}), encoding="utf-8")
    result = _run_preparer(root, manifest)
    assert result.returncode == 2 and "symlink" in result.stderr
    assert not (root / "projects").exists()


def test_valid_bundle_manifest_stages_three_marked_projects(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    manifest = _write_manifest(root)

    result = _run_preparer(root, manifest)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["fixture-project-1", "fixture-project-2", "fixture-project-3"]
    for project_id in result.stdout.splitlines():
        project = root / "projects" / project_id
        assert (project / "OFFLINE_REHEARSAL_TEST_ONLY.json").is_file()
        assert (project / ".openmontage-test-only").is_file()
        assert (project / "hyperframes" / "index.html").is_file()
    schedule = json.loads((root / "config" / "publish_schedule.json").read_text(encoding="utf-8"))
    assert schedule["active_projects"] == []


def test_reviewer_fixture_transport_requires_release_blocking_marker(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".openmontage-test-only").write_text("test only", encoding="utf-8")
    reply = tmp_path / "review.json"
    reply.write_text(json.dumps(REVIEW), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "codex_agent_validation.py"),
         str(project), "--test-review-reply", str(reply)],
        cwd=REPO,
        env=_env(OPENMONTAGE_REHEARSAL="1"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "canonical release-blocking marker" in result.stderr


def test_no_argument_uses_default_path_without_rehearsal_or_network(tmp_path: Path):
    root = _isolated_checkout(tmp_path)
    fake_bin = root / "fake-bin"
    fake_bin.mkdir()
    for command in ("ffprobe", "ffmpeg", "hyperframes"):
        executable = fake_bin / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    fake_python = fake_bin / "python-block"
    fake_python.write_text("#!/bin/sh\nexit 93\n", encoding="utf-8")
    fake_python.chmod(0o755)
    sentinel = root / "default-env-sourced"
    (root / ".env").write_text(f"NEWS_MAX_SOURCE_AGE_HOURS=24\ntouch {sentinel}\n", encoding="utf-8")
    env = _env(OPENMONTAGE_PYTHON=str(fake_python), PATH=f"{fake_bin}:{os.environ.get('PATH', '')}")

    result = subprocess.run(
        ["bash", str(root / "scripts" / PIPELINE.name)], cwd=root, env=env,
        capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    assert sentinel.exists()
    assert "news_pipeline_cli.py fetch" not in result.stdout + result.stderr
    assert (root / "logs").is_dir()


def test_default_invocation_retains_live_acquisition_path_and_director_guard():
    source = PIPELINE.read_text(encoding="utf-8")
    rehearsal_gate = source.index(
        'if [ -n "$REHEARSAL_MANIFEST" ]; then\n  REHEARSAL_TERMINAL_STAGE="directors_and_validation"'
    )
    gateway_path = source.index('DAILY_NEWS_GATEWAY_URL=')
    produce_path = source.index('tools/news/news_pipeline_cli.py produce')
    director = source.index("run_directors() {")
    guard = source.index('director invocation is disabled in rehearsal mode', director)
    call = source.index('run_directors > "$DIRECTORS_JSON"', guard)
    assert rehearsal_gate < gateway_path < produce_path
    assert 'tools/news/news_pipeline_cli.py fetch' not in source
    assert 'else\n# Step 0: Select current Gateway candidates directly, or use a curated backlog.' in source
    assert 'MIN_INITIALIZED_COUNT="${EXPECTED_SUCCESS_COUNT:-5}"' in source
    assert 'if [[ "${#PROJECT_IDS[@]}" -lt "$MIN_INITIALIZED_COUNT" ]]; then' in source
    assert 'ERROR: Expected at least $MIN_INITIALIZED_COUNT initialized projects, got ${#PROJECT_IDS[@]}.' in source
    assert 'got ${#PROJECT_IDS[@]}." >&2' in source
    assert guard < call
    assert 'if [ -d "$PROJECT_DIR" ] && [ -z "$REHEARSAL_MANIFEST" ]; then' in source
