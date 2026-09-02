#!/usr/bin/env python3
"""
Generate Vietnamese subtitles for Docker pipeline.
Simple script to generate word timestamps and SRT subtitles from narration text.
"""

import json
import os
import sys
import subprocess
from pathlib import Path


def estimate_subtitles(text, audio_duration, max_words=3):
    """Generate basic SRT subtitles with estimated timing for Vietnamese text."""
    words = text.strip().split()
    if not words or audio_duration <= 0:
        return [], {}
    
    avg_duration = audio_duration / max(1, len(words))
    word_timestamps = []
    current_time = 0.0
    
    for word in words:
        duration_factor = min(len(word) / 4, 2.0) if len(word) > 1 else 1.0
        word_duration = avg_duration * duration_factor
        
        word_timestamps.append({
            'word': word,
            'start': round(current_time, 3),
            'end': round(current_time + word_duration, 3)
        })
        current_time += word_duration
    
    cues = []
    current_cue_words = []
    current_start = 0.0
    cue_number = 1
    
    for i, timestamp in enumerate(word_timestamps):
        current_cue_words.append(timestamp)
        if (len(current_cue_words) >= max_words or 
            (current_time - current_start) >= 4.0):
            cues.append({
                'number': cue_number,
                'start': current_cue_words[0]['start'],
                'end': current_cue_words[-1]['end'],
                'text': ' '.join(w['word'] for w in current_cue_words)
            })
            cue_number += 1
            current_cue_words = []
            current_start = current_time
    
    if current_cue_words:
        cues.append({
            'number': cue_number,
            'start': current_cue_words[0]['start'],
            'end': current_cue_words[-1]['end'],
            'text': ' '.join(w['word'] for w in current_cue_words)
        })
    
    return cues, word_timestamps


def format_srt(cues):
    """Format cues as SRT content."""
    srt_content = ""
    for cue in cues:
        start_ms = int(round((cue['start'] * 1000) % 1000))
        end_ms = int(round((cue['end'] * 1000) % 1000))
        
        start_str = f"{int(cue['start'] // 3600):02d}:{int((cue['start'] % 3600) // 60):02d}:{int(cue['start'] % 60):02d},{start_ms:03d}"
        end_str = f"{int(cue['end'] // 3600):02d}:{int((cue['end'] % 3600) // 60):02d}:{int(cue['end'] % 60):02d},{end_ms:03d}"
        
        srt_content += f"{cue['number']}\n{start_str} --> {end_str}\n{cue['text']}\n\n"
    return srt_content


def get_audio_duration(audio_path):
    """Get audio file duration in seconds."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', str(audio_path)
        ], capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def main():
    if len(sys.argv) < 4:
        print("Usage: generate_vn_subtitles.py <text_path> <audio_path> <output_srt> [output_json] [max_words]")
        return 1
    
    text_path = sys.argv[1]
    audio_path = sys.argv[2]
    output_srt = sys.argv[3]
    output_json = sys.argv[4] if len(sys.argv) > 4 else None
    max_words = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    
    # Read text
    try:
        with open(text_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"Error reading text file: {e}")
        return 1
    
    text = text.strip()
    if not text:
        print("Error: Empty text file")
        return 1
    
    # Get audio duration
    duration = get_audio_duration(audio_path)
    if duration <= 0:
        duration = max(10.0, len(text) * 0.15)
    
    # Generate subtitles
    cues, word_timestamps = estimate_subtitles(text, duration, max_words)
    
    # Save SRT
    srt_content = format_srt(cues)
    Path(output_srt).parent.mkdir(parents=True, exist_ok=True)
    with open(output_srt, 'w', encoding='utf-8') as f:
        f.write(srt_content)
    
    # Save JSON if requested
    if output_json:
        Path(output_json).parent.mkdir(parents=True, exist_ok=True)
        data = {
            'word_timestamps': word_timestamps,
            'duration_seconds': round(duration, 3),
            'language': 'vi-VN'
        }
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Generated {len(cues)} subtitle cues")
    return 0


if __name__ == "__main__":
    sys.exit(main())