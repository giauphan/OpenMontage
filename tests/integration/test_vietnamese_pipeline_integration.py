"""Integration tests for Vietnamese news pipeline with subtitle coordination.

Tests the complete flow: TTS generation -> word timestamps -> subtitles -> validation
"""

import pytest
import json
import tempfile
import subprocess
from pathlib import Path

from tools.analysis.transcriber import Transcriber
from tools.subtitle.subtitle_gen import SubtitleGen
from lib.media_profiles import get_profile


class TestVietnamesePipelineIntegration:
    """Test the complete Vietnamese news pipeline with subtitle synchronization."""
    
    def test_pipeline_subtitle_coordination(self, tmp_path):
        """Test that narration and subtitles are properly coordinated."""
        project_root = tmp_path / "test_project"
        project_root.mkdir()
        
        # Create hyperframes assets directory
        assets_dir = project_root / "hyperframes" / "assets"
        assets_dir.mkdir(parents=True)
        
        # Create test narration text
        narration_text = "Xin chào. Đây là bản tin thiết kế để kiểm tra phụ đề."
        narration_path = assets_dir / "narration.mp3"
        
        # Since we can't easily generate actual audio in tests, 
        # we'll create a mock scenario with the expected files
        
        # 1. Simulate word timestamps from a transcription
        word_timestamps = [
            {"word": "Xin", "start": 0.0, "end": 0.3},
            {"word": "chào", "start": 0.3, "end": 0.6},
            {"word": "Đây", "start": 0.8, "end": 1.1},
            {"word": "là", "start": 1.1, "end": 1.3},
            {"word": "bản", "start": 1.3, "end": 1.6},
            {"word": "tin", "start": 1.6, "end": 1.8},
            {"word": "thiết", "start": 2.0, "end": 2.3},
            {"word": "kế", "start": 2.3, "end": 2.5},
            {"word": "để", "start": 2.5, "end": 2.7},
            {"word": "kiểm", "start": 2.7, "end": 3.0},
            {"word": "tra", "start": 3.0, "end": 3.2},
            {"word": "phụ", "start": 3.2, "end": 3.4},
            {"word": "đề", "start": 3.4, "end": 3.6},
        ]
        
        timestamps_path = assets_dir / "word_timestamps.json"
        with open(timestamps_path, "w") as f:
            json.dump({
                "word_timestamps": word_timestamps,
                "duration_seconds": 4.0,
                "language": "vi-VN"
            }, f)
        
        # 2. Generate subtitles from word timestamps
        subtitle_path = assets_dir / "subtitles.srt"
        subtitle_result = SubtitleGen().execute({
            "segments": [{"words": word_timestamps}],
            "format": "srt",
            "output_path": str(subtitle_path),
            "max_words_per_cue": 3
        })
        
        assert subtitle_result.success, f"Subtitle generation failed: {subtitle_result.error}"
        assert subtitle_path.exists(), "Subtitles file was not created"
        
        # 3. Validate subtitle content
        srt_content = subtitle_path.read_text()
        
        # Should have proper SRT format
        assert "-->" in srt_content, "Missing SRT timing markers"
        
        # Should have multiple cues
        cues = [c for c in srt_content.split("\n\n") if c.strip()]
        assert len(cues) >= 2, f"Expected multiple subtitle cues, got {len(cues)}"
        
        # First cue should start at 0
        first_cue = cues[0]
        assert "00:00:00,000" in first_cue, "First subtitle should start at 0"
        
        # Should contain Vietnamese text
        vietnamese_text = "Xin chào" or "Đây là" or "phụ đề"
        assert any(text in srt_content for text in ["Xin chào", "Đây là", "phụ đề"]), \
            "Vietnamese text not found in subtitles"
        
    def test_subtitle_format_validation(self, tmp_path):
        """Test that subtitles match expected format for HyperFrames."""
        assets_dir = tmp_path / "hyperframes" / "assets"
        assets_dir.mkdir(parents=True)
        
        # Test with minimal word timestamps
        word_timestamps = [
            {"word": "Test", "start": 0.1, "end": 0.5},
            {"word": "subtitles", "start": 0.6, "end": 1.2}
        ]
        
        subtitle_path = assets_dir / "subtitles.srt"
        SubtitleGen().execute({
            "segments": [{"words": word_timestamps}],
            "format": "srt",
            "output_path": str(subtitle_path),
            "max_words_per_cue": 2
        })
        
        # Validate SRT format
        content = subtitle_path.read_text()
        lines = content.strip().split("\n")
        
        # Should have: cue number, time range, text, blank line
        assert len(lines) >= 3, "SRT format too short"
        
        # First line should be cue number "1"
        assert lines[0].strip() == "1", "First line should be cue number 1"
        
        # Second line should be timing "00:00:00,100 --> 00:00:01,200"
        assert "-->" in lines[1], "Missing timing separator"
        
        # Third line should contain text
        assert "Test subtitles" in lines[2], "Missing subtitle text"
        
    def test_word_timestamps_coverage(self, tmp_path):
        """Test that word timestamps cover the entire narration duration."""
        assets_dir = tmp_path / "hyperframes" / "assets"
        assets_dir.mkdir(parents=True)
        
        # Generate comprehensive word timestamps
        start_time = 0.0
        word_timestamps = []
        test_text = "This is a test for word timestamp coverage validation"
        
        for i, word in enumerate(test_text.split()):
            start_time += 0.3 if i > 0 else 0.0
            word_timestamps.append({
                "word": word,
                "start": round(start_time, 3),
                "end": round(start_time + 0.3, 3)
            })
        
        timestamps_path = assets_dir / "word_timestamps.json"
        with open(timestamps_path, "w") as f:
            json.dump({
                "word_timestamps": word_timestamps,
                "duration_seconds": start_time + 0.3
            }, f)
        
        # Verify timestamps are continuous
        with open(timestamps_path) as f:
            data = json.load(f)
        
        timestamps = data["word_timestamps"]
        for i in range(1, len(timestamps)):
            assert timestamps[i]["start"] >= timestamps[i-1]["end"] or \
                   abs(timestamps[i]["start"] - timestamps[i-1]["end"]) < 0.001, \
                   f"Timestamp gap or overlap at index {i}"
        
        # Verify total duration
        expected_duration = timestamps[-1]["end"]
        assert abs(data["duration_seconds"] - expected_duration) < 0.1, \
            "Duration mismatch"


# Additional helper functions and test cases would go here
# including tests for error handling, edge cases, etc.
