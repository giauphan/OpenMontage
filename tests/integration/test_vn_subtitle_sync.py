"""Strict CI tests for Vietnamese subtitle synchronization in Docker pipeline."""

import pytest
import json
import tempfile
import subprocess
import sys
import os
from pathlib import Path

# Add scripts directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from generate_subtitles_from_text import (
    splitTextToWords, estimateWordDurations, generateSRTFromWordTimestamps, main
)


class TestVietnameseSubtitleGeneration:
    """Test Vietnamese subtitle generation functionality."""
    
    def test_vietnamese_word_splitting(self):
        """Test splitting Vietnamese text into words."""
        text = "Xin chào. Đây là một bản tin thiết kế kiểm tra phụ đề."
        words = splitTextToWords(text)

        # Check that words are properly split
        assert "Xin" in words
        assert "chào" in words  
        assert "Đây" in words
        assert "là" in words
        assert "." in words or "..." in " ".join(words)
        assert len(words) > 5
        
    def test_word_duration_estimation(self):
        """Test word duration estimation."""
        text = "Xin chào đây là bài kiểm tra"
        duration = 10.0  # 10 seconds

        word_timestamps = estimateWordDurations(text, duration)

        assert len(word_timestamps) > 0
        assert word_timestamps[0]["start"] == 0.0
        assert word_timestamps[-1]["end"] <= duration

        # Check all timestamps have required fields
        for timestamp in word_timestamps:
            assert "word" in timestamp
            assert "start" in timestamp
            assert "end" in timestamp
            assert timestamp["end"] >= timestamp["start"]
            
    def test_srt_generation(self):
        """Test SRT generation from word timestamps."""
        word_timestamps = [
            {"word": "Xin", "start": 0.0, "end": 0.5},
            {"word": "chào", "start": 0.5, "end": 1.0},
            {"word": "các", "start": 1.0, "end": 1.3},
            {"word": "bạn", "start": 1.3, "end": 1.6},
        ]
        
        srt_content = generateSRTFromWordTimestamps(word_timestamps, max_words_per_cue=2)
        
        # Should have proper SRT format
        assert "-->" in srt_content
        assert "Xin chào" in srt_content
        assert "các bạn" in srt_content
        
        # Should have cue numbers
        lines = srt_content.strip().split("\n")
        assert any("1" in line for line in lines)
        
    def test_srt_timing_format(self):
        """Test SRT timing format is correct."""
        word_timestamps = [
            {"word": "Test", "start": 0.123, "end": 1.456},
        ]

        srt_content = generateSRTFromWordTimestamps(word_timestamps)

        # Check timing format (uses comma for milliseconds separator)
        assert "00:00:00,123" in srt_content or "00:00:00.123" in srt_content
        assert "00:00:01,456" in srt_content or "00:00:01.456" in srt_content
        
    def test_empty_text_handling(self):
        """Test handling of empty text."""
        word_timestamps = estimateWordDurations("", 10.0)
        assert word_timestamps == []
        
        srt_content = generateSRTFromWordTimestamps([])
        assert srt_content == ""
        
    def test_punctuation_handling(self):
        """Test that punctuation is properly handled in word splitting."""
        text = "Xin chào! Làm thế nào? Test... ???"
        words = splitTextToWords(text)

        # Check that punctuation is preserved as separate tokens
        punctuation_found = any(punct in words for punct in ["!", "?", ".", "...", "???"])
        assert punctuation_found, f"No punctuation found in words: {words}"
        
        # Verify basic words are still there
        assert "Xin" in words
        assert "chào" in words
        
    def test_script_integration(self):
        """Integration test for the subtitle generation script."""
        # Test the functions directly instead of calling main()
        text = "Xin chào đây là bản tin kiểm tra phụ đề"
        duration = 5.0
        
        # Test word splitting
        words = splitTextToWords(text)
        assert len(words) > 0
        
        # Test duration estimation  
        word_timestamps = estimateWordDurations(text, duration)
        assert len(word_timestamps) > 0
        assert word_timestamps[-1]["end"] <= duration
        
        # Test SRT generation
        srt_content = generateSRTFromWordTimestamps(word_timestamps, max_words_per_cue=4)
        assert len(srt_content) > 0
        assert "1" in srt_content  # First subtitle number


class TestSubtitleSynchronization:
    """Test subtitle synchronization with narration timing."""
    
    def test_subtitle_narration_alignment(self):
        """Test that subtitles align properly with narration text."""
        text = "Xin chàoọi bạn đến với chương trình của chúng tôi"
        duration = 15.0
        
        word_timestamps = estimateWordDurations(text, duration)
        srt_content = generateSRTFromWordTimestamps(word_timestamps, max_words_per_cue=4)
        
        # Verify all words from original text appear in subtitles
        text_words = set(text.replace(" ICC", "").lower().split())
        srt_lines = srt_content.lower()
        
        for word in text_words:
            if len(word) > 2:  # Only check meaningful words
                assert word in srt_lines, f"Word '{word}' missing from subtitles"
                
    def test_cue_timing_alignment(self):
        """Test that subtitle cue timing aligns with word timestamps."""
        word_timestamps = [
            {"word": "Start", "start": 0.0, "end": 0.5},
            {"word": "middle", "start": 0.5, "end": 1.0},
            {"word": "end", "start": 1.0, "end": 1.5},
        ]
        
        srt_content = generateSRTFromWordTimestamps(word_timestamps)
        
        # Should have timing that covers the full duration
        assert "00:00:00,000" in srt_content  # Start time
        assert "00:00:01,500" in srt_content  # End time
        
    def test_long_text_handling(self):
        """Test handling of longer Vietnamese text."""
        text = """Xin kính chào quý vị khán giả. 
        đây là bản tin công nghệ mới nhất trong ngày hôm nay. 
        Chúng tôi sẽ cung cấp cho các bạn những thông tin mới nhất về sự phát triển của ngành công nghiệp."""
        
        duration = 30.0
        word_timestamps = estimateWordDurations(text, duration)
        srt_content = generateSRTFromWordTimestamps(word_timestamps, max_words_per_cue=5)
        
        # Should generate multiple cues
        cues = [c for c in srt_content.split("\n\n") if c.strip()]
        assert len(cues) >= 3, "Should have multiple subtitle cues for long text"
        
        # Should have proper word coverage
        words_in_text = set(text.split())
        words_in_subtitles = set()
        
        for cue in cues:
            for line in cue.split("\n"):
                if not line.strip().isdigit() and "-->" not in line:
                    words_in_subtitles.update(line.split())
        
        # Most words should be covered in subtitles
        coverage = len(words_in_subtitles & words_in_text) / len(words_in_text)
        assert coverage > 0.8, f"Low word coverage in subtitles: {coverage}"


# Additional edge case tests and error condition tests
class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_single_word_text(self):
        """Test with single word input."""
        text = "Test"
        word_timestamps = estimateWordDurations(text, 2.0)
        srt_content = generateSRTFromWordTimestamps(word_timestamps)
        
        assert "Test" in srt_content
        assert "00:00:00,000" in srt_content
        
    def test_very_short_duration(self):
        """Test with very short audio duration."""
        text = "Hi"
        word_timestamps = estimateWordDurations(text, 0.001)
        
        # Should still generate some timestamps
        assert len(word_timestamps) > 0
        
    def test_very_long_duration(self):
        """Test with very long audio duration."""
        text = "Test" * 10  # Repeated text
        word_timestamps = estimateWordDurations(text, 600.0)  # 10 minutes
        
        assert len(word_timestamps) > 0
        assert word_timestamps[-1]["end"] <= 600.0

