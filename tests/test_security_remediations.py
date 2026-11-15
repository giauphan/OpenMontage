import os
import tempfile
from pathlib import Path
import pytest

from lib.multishot_session import _file_hash
from lib.news_visual.asset_cache import VisualAssetCache
from lib.pipeline_loader import load_pipeline
from lib.qa_signing import verify_approval_record
from scripts.check_qa import duration, stream_info
from tools.graphics.svg_optimize import optimize_svg_file
from scripts.generate_vn_subtitles import get_audio_duration
from scripts.install_news_captions import install_captions


def test_file_hash_path_traversal(tmp_path):
    # Path traversal detection
    with pytest.raises(ValueError, match="Path traversal detected"):
        _file_hash(tmp_path / ".." / "foo.txt")

    # Missing file detection
    with pytest.raises(ValueError, match="File not found"):
        _file_hash(tmp_path / "nonexistent.txt")

    # Valid file hash
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"hello world")
    res = _file_hash(test_file)
    assert res.startswith("sha256:")


def test_visual_asset_cache_security(tmp_path):
    cache = VisualAssetCache(cache_dir=tmp_path / "cache")

    # Invalid cache key with path traversal
    with pytest.raises(ValueError, match="Invalid cache key"):
        cache.store_cached_asset("../traversal", tmp_path / "dummy.png")

    # Invalid source path with path traversal
    with pytest.raises(ValueError, match="Path traversal detected"):
        cache.store_cached_asset("validkey123", tmp_path / ".." / "outside.png")

    # Missing source file
    with pytest.raises(ValueError, match="Source file not found"):
        cache.store_cached_asset("validkey123", tmp_path / "missing.png")

    # Symlink source file
    real_src = tmp_path / "real.png"
    real_src.write_bytes(b"image")
    sym_src = tmp_path / "sym.png"
    sym_src.symlink_to(real_src)
    with pytest.raises(ValueError, match="Path traversal detected"):
        cache.store_cached_asset("validkey123", sym_src)

    # Invalid submission key
    with pytest.raises(ValueError, match="Invalid submission key"):
        cache.record_persisted_job("../badkey", "job123", "completed")

    # Invalid image_path with traversal
    with pytest.raises(ValueError, match="Path traversal detected"):
        cache.record_persisted_job("validsub", "job123", "completed", image_path="../secret.png")

    # Symlink image_path
    with pytest.raises(ValueError, match="Path traversal detected"):
        cache.record_persisted_job("validsub", "job123", "completed", image_path=str(sym_src))


def test_pipeline_loader_traversal():
    with pytest.raises(ValueError, match="Invalid pipeline name"):
        load_pipeline("../../etc/passwd")

    with pytest.raises(ValueError, match="Invalid pipeline name"):
        load_pipeline("subdir/pipeline")


def test_qa_signing_traversal(tmp_path):
    p_dir = tmp_path / "proj"
    p_dir.mkdir()
    meta_file = p_dir / "publish_metadata.json"
    meta_file.write_text('{"video_path": "../../secret.mp4"}', encoding="utf-8")

    passed, reason = verify_approval_record(
        approval_data={
            "approved": True,
            "signature": "invalid_sig",
        },
        project_id="proj",
        project_dir=p_dir,
    )
    # Should fail verification without escaping directory
    assert not passed
    assert "signature" in reason.lower() or "media" in reason.lower()


def test_check_qa_guards(tmp_path):
    # Non-existent or dash prefix in duration path
    assert duration(tmp_path / "nonexistent.mp4", "ffprobe") is None
    assert duration(tmp_path / "--flag.mp4", "ffprobe") is None

    # Missing file in stream_info
    assert stream_info(tmp_path / "missing.mp4", "ffprobe", "v:0") == "MISSING"

    # Command injection attempt in selector
    valid_file = tmp_path / "sample.mp4"
    valid_file.write_bytes(b"sample")
    assert stream_info(valid_file, "ffprobe", "v:0; rm -rf /") == "INVALID_SELECTOR"
    assert stream_info(valid_file, "ffprobe", "-show_data") == "INVALID_SELECTOR"

    # Fail closed when requested project path is rejected or invalid
    from scripts.check_qa import resolve_projects
    import argparse

    args_invalid = argparse.Namespace(projects=[str(tmp_path / ".." / "outside")], projects_root="projects")
    assert resolve_projects(args_invalid) is None

    args_missing = argparse.Namespace(projects=[str(tmp_path / "nonexistent")], projects_root="projects")
    assert resolve_projects(args_missing) is None

    good_dir = tmp_path / "proj"
    good_dir.mkdir()
    args_good = argparse.Namespace(projects=[str(good_dir)], projects_root="projects")
    res = resolve_projects(args_good)
    assert res == [good_dir.resolve()]


def test_svg_optimize_security(tmp_path):
    # Path traversal in input
    with pytest.raises(ValueError, match="Path traversal detected in input_path"):
        optimize_svg_file(tmp_path / ".." / "in.svg")

    # Missing input file
    with pytest.raises(FileNotFoundError):
        optimize_svg_file(tmp_path / "nonexistent.svg")

    # Path traversal in output
    valid_svg = tmp_path / "valid.svg"
    valid_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>', encoding="utf-8")
    with pytest.raises(ValueError, match="Path traversal detected in output_path"):
        optimize_svg_file(valid_svg, tmp_path / ".." / "out.svg")

    # Successful optimization
    out = tmp_path / "optimized.svg"
    res = optimize_svg_file(valid_svg, out)
    assert res == out
    assert out.is_file()


def test_generate_vn_subtitles_guards(tmp_path):
    with pytest.raises(ValueError, match="Invalid audio path with path traversal"):
        get_audio_duration(tmp_path / ".." / "audio.mp3")

    with pytest.raises(ValueError, match="Audio file does not exist"):
        get_audio_duration(tmp_path / "nonexistent.mp3")


def test_install_news_captions_guards(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("dummy")

    with pytest.raises(ValueError, match="Path traversal detected"):
        install_captions(root / ".." / "outside.html", tmp_path / "audio.mp3", tmp_path / "timings.json")

    with pytest.raises(ValueError, match="Path escapes allowed root"):
        install_captions(outside, tmp_path / "audio.mp3", tmp_path / "timings.json", allowed_root=root)

    # Symlink detection
    sym_comp = root / "sym.html"
    sym_comp.symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink detected in argument"):
        install_captions(sym_comp, tmp_path / "audio.mp3", tmp_path / "timings.json")


def test_local_director_handoff_guards(tmp_path):
    from scripts.local_director_handoff import run_director_handoff, HandoffError

    # Symlink project dir
    real_dir = tmp_path / "real_proj"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym_proj"
    sym_dir.symlink_to(real_dir)

    with pytest.raises(HandoffError, match="invalid project directory"):
        run_director_handoff(sym_dir, tmp_path / "handoff", "prompt", "system", timeout_seconds=1.0)

    # Traversal project dir
    with pytest.raises(HandoffError, match="invalid project directory"):
        run_director_handoff(tmp_path / ".." / "outside", tmp_path / "handoff", "prompt", "system", timeout_seconds=1.0)


def test_fix_narration_timing_voice_guards(tmp_path):
    from scripts.fix_narration_timing import synth

    code, err = synth("-v; dangerous_flag", "hello", tmp_path / "out.mp3", "1.0")
    assert code == 1
    assert "invalid voice identifier" in err

    code, err = synth("voice\nother", "hello", tmp_path / "out.mp3", "1.0")
    assert code == 1
    assert "invalid voice identifier" in err

    code, err = synth("valid_voice", "hello", tmp_path / "out.mp3", "1.0; rm -rf")
    assert code == 1
    assert "invalid rate format" in err


def test_visual_asset_cache_symlink_dir(tmp_path):
    from lib.news_visual.asset_cache import _secure_cache_dir

    target = tmp_path / "actual_cache"
    target.mkdir()
    sym = tmp_path / "sym_cache"
    sym.symlink_to(target)

    with pytest.raises(PermissionError, match=r"Cache directory cannot.*symlink"):
        _secure_cache_dir(sym)

    # When instantiated with a symlink, VisualAssetCache rejects it and falls back
    cache = VisualAssetCache(cache_dir=sym)
    assert cache.cache_dir != sym


def test_validation_status_symlink(tmp_path, monkeypatch, capsys):
    from scripts.validation_status import main

    real_details = tmp_path / "real.json"
    real_details.write_text('{"foo": "bar"}', encoding="utf-8")
    sym_details = tmp_path / "sym.json"
    sym_details.symlink_to(real_details)

    monkeypatch.setattr("sys.argv", ["validation_status.py", "proj123", "PASS", "--details", str(sym_details)])
    ret = main()
    assert ret == 1
    captured = capsys.readouterr()
    assert "Symlink detected" in captured.err


def test_narration_text_bidi_and_cli_guards(tmp_path):
    from tools.narration_text import normalize_text, main as narration_main

    # Bidi characters are still rejected by _FORBIDDEN_PATTERN using \uXXXX escapes
    with pytest.raises(ValueError, match="unrenderable characters"):
        normalize_text("Xin chào \u202e thế giới")

    # CLI path traversal blocked
    ret = narration_main(["--in-file", str(tmp_path / ".." / "secret.txt")])
    assert ret == 1


def test_comfyui_random_seed_csprng():
    from tools._comfyui.client import ComfyUIClient

    seed = ComfyUIClient.random_seed()
    assert isinstance(seed, int)
    assert 0 <= seed < 2**32


def test_dashscope_asr_url_validation():
    from tools.analysis.dashscope_asr import DashscopeAsr

    assert DashscopeAsr._is_public_url("https://example.com/audio.mp3")
    assert DashscopeAsr._is_public_url("http://example.com/audio.mp3")
    assert not DashscopeAsr._is_public_url("/etc/passwd")
    assert not DashscopeAsr._is_public_url("file:///tmp/audio.mp3")


def test_template_selector_and_provenance_guards(tmp_path):
    from tools.news.template_selector import _validate_safe_brief_path
    from tools.news.template_provenance import record_provenance

    with pytest.raises(ValueError, match="Path traversal detected"):
        _validate_safe_brief_path(tmp_path / ".." / "brief.json")

    with pytest.raises(ValueError, match="Path traversal detected"):
        record_provenance(
            tmp_path / ".." / "proj",
            "news-explainer",
            "1.0.0",
            {"title": "test"},
            None,
            None,
            "short",
        )


def test_multishot_media_probe_clip_traversal(tmp_path):
    from lib.multishot_media import probe_clip

    res = probe_clip(tmp_path / ".." / "outside.mp4")
    assert res["decode_ok"] is False
    assert any("invalid or unsafe file path" in err for err in res["errors"])



# ---------------------------------------------------------------------------
# Remediations for 13 SonarQube Security Findings
# ---------------------------------------------------------------------------

from lib.checkpoint import (
    CheckpointValidationError,
    _checkpoint_path,
    _decision_log_path,
    _archive_superseded_checkpoint,
    _merge_decision_log,
    write_checkpoint,
)
from lib.news_visual.qa import run_news_visual_qa
from lib.audio.narration_orchestrator import NarrationOrchestrator
from lib.local_agent_handoff import (
    HandoffError,
    submit_local_response,
    _atomic_json,
    _validate_safe_root,
)
from scripts.validate_render_quality import validate_video, _read_safe_narration_text


class TestCheckpointSecurity:
    """Security tests for lib/checkpoint.py."""

    def test_checkpoint_path_rejects_traversal(self, tmp_path: Path):
        with pytest.raises(CheckpointValidationError):
            _checkpoint_path(tmp_path, "../escaped", "script")

        with pytest.raises(CheckpointValidationError):
            _checkpoint_path(tmp_path, "proj", "../escaped")

        with pytest.raises(CheckpointValidationError):
            _checkpoint_path(tmp_path, "proj\x00null", "script")

    def test_decision_log_path_rejects_traversal(self, tmp_path: Path):
        with pytest.raises(CheckpointValidationError):
            _decision_log_path(tmp_path, "../../etc")

    def test_write_checkpoint_rejects_traversal_project_id(self, tmp_path: Path):
        with pytest.raises(CheckpointValidationError):
            write_checkpoint(
                tmp_path,
                "../../escaped",
                "script",
                "completed",
                artifacts={"script": {"title": "Test"}},
            )

    def test_archive_superseded_sanitizes_crlf_log(self, tmp_path: Path, caplog):
        malicious_path = tmp_path / "checkpoint_test\r\nINJECTED_LOG_LINE:admin\n.json"
        with caplog.at_level("WARNING"):
            _archive_superseded_checkpoint(malicious_path, "script\r\nINJECTED")
        for record in caplog.records:
            assert "\r" not in record.message
            assert "\n" not in record.message

    def test_merge_decision_log_rejects_symlink(self, tmp_path: Path):
        proj_dir = tmp_path / "test_proj"
        proj_dir.mkdir(parents=True)
        target = tmp_path / "secret.json"
        target.write_text("{}", encoding="utf-8")
        symlink_log = proj_dir / "decision_log.json"
        symlink_log.symlink_to(target)

        with pytest.raises(CheckpointValidationError, match="(?i)symlink"):
            _merge_decision_log(tmp_path, "test_proj", {"decisions": [{"decision_id": "d1"}]})


class TestNewsVisualQASecurity:
    """Security tests for lib/news_visual/qa.py."""

    def test_run_news_visual_qa_rejects_path_traversal(self, tmp_path: Path):
        traversal_path = tmp_path / ".." / "escaped_project"
        report = run_news_visual_qa(traversal_path, mode="strict")
        assert report["passed"] is False
        assert "INVALID_PROJECT_DIR" in report["failure_categories"]

    def test_run_news_visual_qa_rejects_symlinked_report_path(self, tmp_path: Path):
        proj_dir = tmp_path / "proj"
        art_dir = proj_dir / "artifacts"
        art_dir.mkdir(parents=True)
        target = tmp_path / "external_report.json"
        target.write_text("{}", encoding="utf-8")
        symlink_report = art_dir / "news_visual_qa_report.json"
        symlink_report.symlink_to(target)

        with pytest.raises(ValueError, match="Invalid news visual QA report path"):
            run_news_visual_qa(proj_dir, mode="strict")


class TestNarrationOrchestratorSecurity:
    """Security tests for lib/audio/narration_orchestrator.py."""

    def test_invoke_flite_rejects_dash_prefixed_output(self, tmp_path: Path):
        orchestrator = NarrationOrchestrator()
        dash_output = tmp_path / "-malicious_flag.mp3"
        res = orchestrator._invoke_flite("Hello world", dash_output, "slt")
        assert res.success is False
        assert "Invalid output path" in res.error or "begins with dash" in res.error

    def test_invoke_flite_rejects_null_byte_output(self, tmp_path: Path):
        orchestrator = NarrationOrchestrator()
        null_output = tmp_path / "test\x00out.mp3"
        res = orchestrator._invoke_flite("Hello world", null_output, "slt")
        assert res.success is False


class TestLocalAgentHandoffSecurity:
    """Security tests for lib/local_agent_handoff.py."""

    def test_validate_safe_root_rejects_null_byte_and_dash(self):
        with pytest.raises(HandoffError):
            _validate_safe_root("/tmp/path\x00evil")

        with pytest.raises(HandoffError):
            _validate_safe_root("-dash_dir")

    def test_submit_local_response_rejects_symlink_dir(self, tmp_path: Path):
        root = tmp_path / "handoff"
        root.mkdir()
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        symlink_req = root / "0123456789abcdef0123456789abcdef"
        symlink_req.symlink_to(secret_dir)

        with pytest.raises(HandoffError, match="symlink"):
            submit_local_response(
                root,
                "0123456789abcdef0123456789abcdef",
                "dummy_sha",
                {"action": "test"},
            )

    def test_atomic_json_rejects_symlink_parent_or_target(self, tmp_path: Path):
        secret_file = tmp_path / "secret.json"
        secret_file.write_text("{}", encoding="utf-8")
        symlink_target = tmp_path / "symlink.json"
        symlink_target.symlink_to(secret_file)

        with pytest.raises(HandoffError):
            _atomic_json(symlink_target, {"key": "val"})


class TestValidateRenderQualitySecurity:
    """Security tests for scripts/validate_render_quality.py."""

    def test_read_safe_narration_text_rejects_traversal_and_symlinks(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unsafe path traversal token"):
            _read_safe_narration_text(tmp_path / ".." / "secret.txt")

        with pytest.raises(ValueError, match="Unsafe path traversal token"):
            _read_safe_narration_text(tmp_path / "-flag.txt")

        # Symlink rejection
        real_file = tmp_path / "real.txt"
        real_file.write_text("Valid narration text", encoding="utf-8")
        symlink_file = tmp_path / "symlink.txt"
        symlink_file.symlink_to(real_file)

        with pytest.raises(ValueError, match="Symlink rejected"):
            _read_safe_narration_text(symlink_file)

    def test_validate_video_handles_unsafe_narration_path_gracefully(self, tmp_path: Path):
        dummy_video = tmp_path / "video.mp4"
        dummy_video.write_bytes(b"test" * 100)
        dummy_audio = tmp_path / "audio.mp3"
        dummy_audio.write_bytes(b"test" * 100)
        unsafe_narration = tmp_path / ".." / "secret.txt"

        errors = validate_video(
            dummy_video,
            dummy_audio,
            ffprobe="ffprobe",
            ffmpeg="ffmpeg",
            min_duration=1.0,
            tolerance=1.0,
            expected_dimensions=(1080, 1920),
            narration_text=unsafe_narration,
        )
        assert any("Unsafe path traversal token" in e for e in errors)
