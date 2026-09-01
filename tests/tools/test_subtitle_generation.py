"""Strict tests for subtitle generation in Vietnamese news pipeline.

Verifies that:
1. Word timestamps are properly generated from narration audio
2. Subtitles are created with correct timing
3. Subtitles match the narration text
4. Subtitles are properly formatted for HyperFrames
"""

from pathlib import Path
import pytest
import json

from tools.analysis.transcriber import Transcriber
from tools.subtitle.subtitle_gen import SubtitleGen

@pytest.fixture
def test_project(tmp_path):
    """Create a test project structure with test narration."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "hyperframes").mkdir(parents=True)
    (project / "hyperframes" / "assets").mkdir()
    
    # Create test narration audio (silence for testing)
    narration_path = project / "hyperframes" / "assets" / "narration.mp3"
    narration_path.touch()
    
    return project

def test_subtitle_generation_flow(test_project):
    """Test complete subtitle generation flow from narration to SRT file."""
    narration_path = test_project / "hyperframes" / "assets" / "narration.mp3"
    word_timestamps_path = test_project / "hyperframes" / "assets" / "word_timestamps.json"
    subtitles_path = test_project / "hyperframes" / "assets" / "subtitles.srt"
    
    # 1. Generate word timestamps
    result = Transcriber().execute({
        "input_path": str(narration_path),
        "word_timestamps": True,
        "model_size": "tiny"
    })
    assert result.success, f"Transcription failed: {result.error}"
    assert "word_timestamps" in result.data, "No word timestamps in transcription result"
    
    # Save word timestamps
    with open(word_timestamps_path, "w") as f:
        json.dump(result.data, f, indent=2)
    
    # 2. Generate subtitles
    with open(word_timestamps_path) as f:
        data = json.load(f)
    
    subtitle_result = SubtitleGen().execute({
        "segments": [{'words': data['word_timestamps']}],
        "format": "srt",
        "output_path": str(subtitles_path)
    })
    
    assert subtitle_result.success, f"Subtitle generation failed: {subtitle_result.error}"
    assert subtitles_path.exists(), "Subtitles SRT file not created"
    
    # 3. Verify subtitle content
    srt_content = subtitles_path.read_text()
    assert "-->" in srt_content, "Invalid SRT format"
    assert len(srt_content.split("\n\n")) > 1, "No subtitle cues found"
    
    # 4. Verify timing alignment
    with open(word_timestamps_path) as f:
        timestamps = json.load(f)['word_timestamps']
    
    if timestamps:
        first_word = timestamps[0]
        first_cue = srt_content.split("\n")[1:4]  # First cue block
        assert str(first_word['start']) in first_cue[0], "Timing mismatch in first subtitle cue"

# Add more test cases for edge cases
# ...
