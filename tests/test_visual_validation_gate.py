import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from scripts.claude_agent_validation import CLAUDEAgentValidator
from scripts.publish_manual_video import validate_project_quality

ROOT = Path(__file__).resolve().parents[1]

def test_claude_validator_rejects_missing_html(tmp_path: Path):
    """CLAUDEAgentValidator must fail strict review when HyperFrames HTML is missing."""
    project_dir = tmp_path / "cand_missing_html"
    project_dir.mkdir(parents=True)
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_reels_vi_9x16.mp4").touch()
    (project_dir / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_missing_html",
        "title": "T #tintuc #congnghe #ai",
        "description": "D #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }))

    validator = CLAUDEAgentValidator(project_dir, strict_mode=True)
    results = validator.claude_agent_strict_review(
        renders_dir / "final_reels_vi_9x16.mp4",
        project_dir / "publish_metadata.json"
    )
    assert any("Missing HyperFrames HTML source" in r.message for r in results)
    assert not all(r.passed for r in results)


def test_claude_validator_rejects_frame_extraction_failure(tmp_path: Path):
    """CLAUDEAgentValidator must fail strict review when representative frames cannot be extracted."""
    project_dir = tmp_path / "cand_bad_frames"
    project_dir.mkdir(parents=True)
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    # 0-byte video or non-video file
    (renders_dir / "final_reels_vi_9x16.mp4").write_text("not a real mp4")

    hf_reels_dir = project_dir / "hyperframes_reels"
    hf_reels_dir.mkdir()
    (hf_reels_dir / "index.html").write_text("<html><body>Polished Video</body></html>")

    (project_dir / "publish_metadata.json").write_text(json.dumps({
        "id": "cand_bad_frames",
        "title": "T #tintuc #congnghe #ai",
        "description": "D #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }))

    validator = CLAUDEAgentValidator(project_dir, strict_mode=True)
    results = validator.claude_agent_strict_review(
        renders_dir / "final_reels_vi_9x16.mp4",
        project_dir / "publish_metadata.json"
    )
    assert any("Frame extraction failed" in r.message for r in results)
    assert not all(r.passed for r in results)


def test_claude_validator_prompt_contains_html_and_images(tmp_path: Path):
    """CLAUDEAgentValidator must supply full composition HTML and frame references in prompt."""
    project_dir = tmp_path / "cand_prompt_check"
    project_dir.mkdir(parents=True)
    renders_dir = project_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "final_reels_vi_9x16.mp4").write_bytes(b"video")

    hf_reels_dir = project_dir / "hyperframes_reels"
    hf_reels_dir.mkdir()
    unique_html_content = "<div class='scene' data-scene-id='scene_1'>UNIQUE_TEST_SCENE</div>"
    (hf_reels_dir / "index.html").write_text(unique_html_content)

    meta_path = project_dir / "publish_metadata.json"
    meta_path.write_text(json.dumps({
        "id": "cand_prompt_check",
        "title": "T #tintuc #congnghe #ai",
        "description": "D #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }))

    validator = CLAUDEAgentValidator(project_dir, strict_mode=True)

    captured_prompt = []
    fake_frame = tmp_path / "fake_frame.png"
    fake_frame.touch()

    with patch.dict("os.environ", {"CLAUDE_AGENT_VALIDATION_MOCK": "0"}), \
         patch.object(validator, "_extract_frames", return_value=[fake_frame]), \
         patch("scripts.claude_agent_validation.resolve_claude_cli", return_value="claude"), \
         patch("scripts.claude_agent_validation.subprocess.run") as mock_subproc:

        mock_subproc.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "visual_quality": {"passed": True, "score": 95, "notes": "ok"},
                "audio_sync": {"passed": True, "score": 95, "notes": "ok"},
                "content_appropriateness": {"passed": True, "score": 95, "notes": "ok"},
                "brand_compliance": {"passed": True, "score": 95, "notes": "ok"},
                "overall_passed": True,
                "summary": "ok"
            })
        )

        results = validator.claude_agent_strict_review(
            renders_dir / "final_reels_vi_9x16.mp4",
            meta_path
        )

        assert mock_subproc.call_count >= 1
        call_kwargs = mock_subproc.call_args[1]
        prompt_used = call_kwargs.get("input", "")

        # Verify prompt includes actual HTML and frame info
        assert "UNIQUE_TEST_SCENE" in prompt_used
        assert "[Attached image: fake_frame.png]" in prompt_used
        assert "DO NOT attempt to open or view" not in prompt_used


def test_validate_project_quality_raises_when_claude_validator_fails(tmp_path: Path):
    """validate_project_quality must fail closed before publishing when strict validator exits non-zero."""
    project_dir = tmp_path / "cand_pub_fail"
    project_dir.mkdir(parents=True)
    meta_path = project_dir / "publish_metadata.json"
    meta_path.write_text(json.dumps({
        "id": "cand_pub_fail",
        "title": "T #tintuc #congnghe #ai",
        "description": "D #tintuc #congnghe #ai",
        "yt_shorts": "renders/final_reels_vi_9x16.mp4",
        "ig_reels": "renders/final_reels_vi_9x16.mp4",
        "fb_video": "renders/final_full_vi_9x16.mp4",
    }))

    def fake_subprocess_run(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        if "validate_publish_metadata.py" in cmd_str:
            return MagicMock(returncode=0)
        if "claude_agent_validation.py" in cmd_str:
            return MagicMock(returncode=1, stdout="Visual validation rejected static layout", stderr="")
        return MagicMock(returncode=0)

    with patch("scripts.publish_manual_video.subprocess.run", side_effect=fake_subprocess_run):
        with pytest.raises(RuntimeError) as excinfo:
            validate_project_quality(project_dir, strict=True)
        assert "CLAUDE Agent strict validation failed" in str(excinfo.value)
        assert "Visual validation rejected static layout" in str(excinfo.value)
