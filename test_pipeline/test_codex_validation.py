import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
"""Tests for Codex Agent Validation Pipeline."""

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.codex_agent_validation import (
    CodexAgentValidator,
    ValidationResult,
    parse_codex_review,
    resolve_codex_cli,
    resolve_ffprobe_ffmpeg,
)


class TestCodexAgentValidationPipeline:
    """Test suite for Codex Agent Validation Pipeline."""

    def setup_method(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.project_dir = self.test_dir / "test_project"
        self.project_dir.mkdir()
        self._create_test_files()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_files(self):
        (self.project_dir / "renders").mkdir()
        (self.project_dir / "artifacts").mkdir()
        (self.project_dir / "hyperframes").mkdir()

        for video_file in ["final_full_vi_9x16.mp4", "final_reels_vi_9x16.mp4"]:
            video_path = self.project_dir / "renders" / video_file
            with open(video_path, "wb") as f:
                f.write(b"\x00" * 1024 * 1024)

        metadata = {
            "title": "Bản tin công nghệ trí tuệ nhân tạo #tintuc #congnghe #ai",
            "description": "Cập nhật bản tin công nghệ trí tuệ nhân tạo mới nhất #tintuc #congnghe #ai",
            "yt_shorts": {"title": "Bản tin #Shorts"},
            "tiktok": {"title": "Bản tin"},
            "fb_video": {"title": "Bản tin"},
            "ig_reels": {"title": "Bản tin"},
        }
        with open(self.project_dir / "publish_metadata.json", "w") as f:
            json.dump(metadata, f)

        script = {
            "title": "Test Video",
            "sections": [
                {"id": "hook", "text_vi": "Chào bạn, đây là tin tức AI mới nhất."},
                {"id": "content", "text_vi": "Công nghệ AI đang phát triển mạnh mẽ."},
            ],
        }
        with open(self.project_dir / "artifacts" / "script_vi.json", "w") as f:
            json.dump(script, f)

        with open(self.project_dir / "hyperframes" / "index.html", "w") as f:
            f.write('<div class="scene" data-scene-id="scene1"><h1>Tin tức AI</h1></div>')

    def test_technical_contract_validation(self):
        validator = CodexAgentValidator(self.project_dir, strict_mode=True)
        video_path = self.project_dir / "renders" / "final_full_vi_9x16.mp4"
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "45.2\n"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            results = validator.validate_technical_contract(video_path)
            assert any(r.check_name == "Duration Check" and r.passed for r in results)

    def test_metadata_validation(self):
        validator = CodexAgentValidator(self.project_dir, strict_mode=True)
        meta_path = self.project_dir / "publish_metadata.json"
        results = validator.validate_metadata(meta_path)
        assert any(r.check_name == "Metadata Validation" and r.passed for r in results)

    def test_codex_agent_review_mocked(self):
        validator = CodexAgentValidator(self.project_dir, strict_mode=True)
        review_data = json.dumps({
            "visual_quality": {"passed": True, "score": 95, "notes": "Clear UI"},
            "audio_sync": {"passed": True, "score": 92, "notes": "Synced"},
            "content_appropriateness": {"passed": True, "score": 98, "notes": "Appropriate"},
            "brand_compliance": {"passed": True, "score": 94, "notes": "Clean"},
            "overall_passed": True,
            "summary": "Passed all gates",
        })
        with patch.object(validator, "_execute_cli_review") as mock_exec, \
             patch.object(validator, "_extract_frames", return_value=[Path("frame-1.png"), Path("frame-2.png"), Path("frame-3.png")]), \
             patch("scripts.codex_agent_validation.resolve_agent_cli", return_value="/usr/bin/codex"):
            mock_exec.return_value = [
                ValidationResult(check_name="Visual Quality", passed=True, message="ok"),
                ValidationResult(check_name="Audio Sync", passed=True, message="ok"),
                ValidationResult(check_name="Content Appropriateness", passed=True, message="ok"),
                ValidationResult(check_name="Brand Compliance", passed=True, message="ok"),
            ]
            video_path = self.project_dir / "renders" / "final_full_vi_9x16.mp4"
            results = validator.codex_agent_strict_review(video_path, self.project_dir / "publish_metadata.json")
            assert len(results) == 4
            assert all(r.passed for r in results)

    def test_codex_agent_autonomous_fallback(self):
        validator = CodexAgentValidator(self.project_dir, strict_mode=True)
        video_path = self.project_dir / "renders" / "final_full_vi_9x16.mp4"
        # Without CLI or when CLI fails, autonomous review should pass valid project
        results = validator._autonomous_quality_review(video_path, self.project_dir / "publish_metadata.json")
        assert len(results) == 4
        assert all(r.passed for r in results)
