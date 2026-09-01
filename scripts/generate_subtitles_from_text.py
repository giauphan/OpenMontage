#!/usr/bin/env python3
"""Generate subtitles for Vietnamese news pipeline.

This script generates properly timed subtitles from narration text
when word-level timestamps are not available from TTS.

Usage:
    python3 generate_subtitles_from_text.py \
        --narration-text "path/to/narration_text.txt" \
        --audio-path "path/to/narration.mp3" \
        --output-srt "path/to/subtitles.srt" \
        --output-json "path/to/word_timestamps.json"
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Optional


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration using ffprobe."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", 
            "format=duration", "-of", "csv=p=0", str(audio_path)
        ], capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def splitTextToWords(text: str) -> List[str]:
    """Split Vietnamese text into words, preserving punctuation."""
    # Handle Vietnamese text - it uses spaces but also has some special cases
    # For now, simple space-based splitting should work for most cases
    words = []
    current_word = ""
    
    for char in text:
        if char.isalnum() or char in "àáâãăăivalentu السفلا":
            current_word += char
        else:
            if current_word:
                words.append(current_word)
                current_word = ""
            if char in ".!?,;":
                words.append(char)
    
    if current_word:
        words.append(current_word)
    
    return words


def estimateWordDurations(text: str, total_duration: float) -> List[Dict]:
    """Estimate word durations based on text length and total audio duration."""
    words = splitTextToWords(text)
    
    if not words or total_duration <= 0:
        return []
    
    # Estimate average word duration
    avg_duration = total_duration / len(words)
    
    word_timestamps = []
    current_time = 0.0
    
    for i, word in enumerate(words):
        # Estimate this word's duration
        # Longer words get slightly more time
        word_length_factor = min(len(word) / 5, 1.5) if word.strip() else 0.5
        word_duration = avg_duration * word_length_factor
        
        # Punctuation marks get shorter duration
        if word in ".!?":
            word_duration = avg_duration * 0.3
        elif word in ",;:":
            word_duration = avg_duration * 0.5
        
        word_timestamps.append({
            "word": word,
            "start": round(current_time, 3),
            "end": round(current_time + word_duration, 3)
        })
        
        current_time += word_duration
    
    return word_timestamps


def generateSRTFromWordTimestamps(word_timestamps: List[Dict], max_words_per_cue: int = 3) -> str:
    """Generate SRT subtitles from word timestamps."""
    srt_content = ""
    cue_counter = 1
    
    # Group words into subtitle cues
    cues = []
    current_cue_words = []
    current_cue_start = None
    current_cue_end = None
    
    for i, timestamp in enumerate(word_timestamps):
        if not current_cue_words:
            current_cue_words = [timestamp]
            current_cue_start = timestamp["start"]
            current_cue_end = timestamp["end"]
        else:
            current_cue_words.append(timestamp)
            current_cue_end = timestamp["end"]
            
            # Split cue if we have enough words or reached a timing threshold
            if (len(current_cue_words) >= max_words_per_cue or 
                (current_cue_end - current_cue_start) >= 3.0):  # Max 3 seconds per cue
                cues.append({
                    "number": cue_counter,
                    "start": current_cue_start,
                    "end": current_cue_end,
                    "text": " ".join(w["word"] for w in current_cue_words)
                })
                cue_counter += 1
                current_cue_words = []
                current_cue_start = None
                current_cue_end = None
    
    # Add the last cue
    if current_cue_words:
        cues.append({
            "number": cue_counter,
            "start": current_cue_start,
            "end": current_cue_end,
            "text": " ".join(w["word"] for w in current_cue_words)
        })
    
    # Format SRT content
    for cue in cues:
        start_str = f"{int(cue['start'] // 3600):02d}:{int((cue['start'] % 3600) // 60):02d}:{int(cue['start'] % 60):02d},{int((cue['start'] % 1) * 1000):03d}"
        end_str = f"{int(cue['end'] // 3600):02d}:{int((cue['end'] % 3600) // 60):02d}:{int(cue['end'] % 60):02d},{int((cue['end'] % 1) * 1000):03d}"
        
        srt_content += f"{cue['number']}\n"
        srt_content += f"{start_str} --> {end_str}\n"
        srt_content += f"{cue['text']}\n\n"
    
    return srt_content


def main():
    parser = argparse.ArgumentParser(description="Generate subtitles from Vietnamese narration text")
    parser.add_argument("--narration-text", required=True, help="Path to narration text file")
    parser.add_argument("--audio-path", required=True, help="Path to narration audio file")
    parser.add_argument("--output-srt", required=True, help="Path to output SRT subtitle file")
    parser.add_argument("--output-json", help="Path to output word timestamps JSON file")
    parser.add_argument("--max-words-per-cue", type=int, default=3, help="Maximum words per subtitle cue")
    
    args = parser.parse_args()
    
    # Read narration text
    with open(args.narration_text, "r", encoding="utf-8") as f:
        text = f.read().strip()
    
    if not text:
        print("Error: Empty narration text file")
        return 1
    
    # Get audio duration
    audio_duration = get_audio_duration(Path(args.audio_path))
    if audio_duration <= 0:
        print("Error: Could not determine audio duration")
        return 1
    
    # Generate word timestamps
    word_timestamps = estimateWordDurations(text, audio_duration)
    
    if not word_timestamps:
        print("Error: Could not generate word timestamps")
        return 1
    
    # Save word timestamps JSON
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump({
                "word_timestamps": word_timestamps,
                "duration_seconds": round(audio_duration, 3),
                "language": "vi-VN",
                "provider": "estimated_from_audio"
            }, f, indent=2, ensure_ascii=False)
        print(f"Word timestamps saved to: {args.output_json}")
    
    # Generate SRT subtitles
    srt_content = generateSRTFromWordTimestamps(word_timestamps, args.max_words_per_cue)
    
    # Save SRT file
    with open(args.output_srt, "w", encoding="utf-8") as f:
        f.write(srt_content)
    
    print(f"Subtitles saved to: {args.output_srt}")
    print(f"Generated {len(word_timestamps)} word timestamps")
    print(f"Generated {len(srt_content.split(chr(10)+chr(10)))-1} subtitle cues")
    
    return 0


if __name__ == "__main__":
    exit(main())