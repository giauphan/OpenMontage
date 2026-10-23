#!/usr/bin/env python3
"""Render production-grade verified en-US deliverables (Short 72s and Longform 360s).

Grounded in verified primary citations:
- SWE-bench (ICLR 2024, arXiv:2310.06770)
- MetaGPT (ICLR 2024, arXiv:2308.00352)
- ACM Rollback-Recovery Survey (DOI: 10.1145/568522.568525)
- Google Cloud DORA 2024 Report

Generates high-production technical graphic cards (replacing testsrc)
with exact 9:16 and 16:9 aspect ratios (setsar=1) and strict audio mixing.

NOTE: This script does NOT self-approve. Render outputs must be independently
inspected and approved by scripts/independent_editorial_qa.py.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SHORT_PROJECT = ROOT / "projects/us_ai_short_01"
LONG_PROJECT = ROOT / "projects/us_ai_longform_02"
MUSIC_BG = ROOT / "artifacts/us-migration/canaries/canary-short-en-us-01/assets/music-bg.mp3"

TMP_DIR = Path("/tmp/render_verified")
TMP_DIR.mkdir(parents=True, exist_ok=True)
GRAPHICS_DIR = Path("/tmp/scene_graphics")


def run(cmd: str):
    print(f"RUN: {cmd[:140]}...")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"FAILED (code {res.returncode}):")
        print(res.stderr)
        raise RuntimeError(f"Command failed: {cmd}")
    return res.stdout


def srt_to_ass(srt_path: Path, ass_path: Path, width: int, height: int, font_size: int, margin_v: int, alignment: int = 2):
    """Convert SRT cues to ASS with exact pixel PlayRes canvas to avoid top-screen overflow."""
    import re
    srt_text = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    dialogues = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        time_match = re.match(r"(\d+):(\d+):(\d+)[,\.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,\.](\d+)", lines[1])
        if not time_match:
            continue
        sh, sm, ss, sms, eh, em, es, ems = time_match.groups()
        start_ass = f"{int(sh)}:{sm}:{ss}.{int(sms)//10:02d}"
        end_ass = f"{int(eh)}:{em}:{es}.{int(ems)//10:02d}"
        text = " ".join(lines[2:])
        text = text.replace("{", "\\{").replace("}", "\\}")
        dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}")

    ass_content = f"""[Script Info]
Title: Synced Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,{alignment},80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(dialogues) + "\n"
    ass_path.write_text(ass_content, encoding="utf-8")


def ensure_graphics():
    print("\n=== GENERATING CONTEXTUAL SCENE GRAPHICS ===")
    from scripts.generate_scene_graphics import generate_short_graphics, generate_longform_graphics
    generate_short_graphics(GRAPHICS_DIR / "short")
    generate_longform_graphics(GRAPHICS_DIR / "long")


def render_short():
    print("\n=== RENDERING US SHORT (72s, 1080x1920, 9:16, SAR 1:1) ===")
    narration_txt = SHORT_PROJECT / "artifacts/narration_en_US_text.txt"
    raw_audio = TMP_DIR / "short_narration_raw.mp3"
    mixed_audio = TMP_DIR / "short_mixed_audio.mp3"
    concat_video = TMP_DIR / "short_concat_raw.mp4"
    final_video = TMP_DIR / "final_short_en_US_9x16.mp4"

    # 1. TTS audio
    run(f'ffmpeg -y -loglevel error -f lavfi -i "flite=textfile={narration_txt}:voice=slt" -af "apad=whole_dur=72.0" {raw_audio}')

    # 2. Mix with music (narration volume 1.0, background music 0.15)
    run(f'ffmpeg -y -loglevel error -i {raw_audio} -stream_loop -1 -i {MUSIC_BG} '
        f'-filter_complex "[0:a]volume=1.0[a0];[1:a]volume=0.15[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=3[out]" '
        f'-map "[out]" -t 72.0 {mixed_audio}')

    # 3. Render scene segments and concatenate
    s_dir = GRAPHICS_DIR / "short"
    scenes = [
        ("scene_01_hook.png", 12.0),
        ("scene_02_benchmark.png", 14.0),
        ("scene_03_coordination.png", 15.0),
        ("scene_04_sandboxing.png", 14.0),
        ("scene_05_verification.png", 17.0),
    ]
    seg_files = []
    for idx, (img_name, dur) in enumerate(scenes):
        seg_path = TMP_DIR / f"short_seg_{idx}.mp4"
        run(f'ffmpeg -y -loglevel error -loop 1 -framerate 30 -t {dur} -i {s_dir / img_name} '
            f'-vf "pad=1084:1924:2:2:color=#0b0f19,crop=1080:1920:\'2+1.5*sin(t*0.5)\':\'2+1.5*cos(t*0.5)\',setsar=1" '
            f'-c:v libx264 -preset fast -pix_fmt yuv420p {seg_path}')
        seg_files.append(seg_path)

    list_path = TMP_DIR / "short_concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in seg_files:
            f.write(f"file '{p}'\n")

    run(f'ffmpeg -y -loglevel error -f concat -safe 0 -i {list_path} -c copy {concat_video}')

    # 4. Final compositing: Overlay audio, top subtitle container, burned-in synchronized subtitles
    srt_short = SHORT_PROJECT / "artifacts/captions_en_US.srt"
    ass_short = TMP_DIR / "short_captions.ass"
    srt_to_ass(srt_short, ass_short, width=1080, height=1920, font_size=38, margin_v=95, alignment=8)
    vf = (
        "drawbox=x=60:y=60:w=960:h=180:color=#0b0f19@0.92:t=fill,"
        "drawbox=x=60:y=60:w=960:h=180:color=#38bdf8@0.6:t=2,"
        f"ass={ass_short},"
        "setsar=1"
    )

    run(f'ffmpeg -y -loglevel error -i {concat_video} -i {mixed_audio} '
        f'-vf "{vf}" -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -t 72.0 {final_video}')

    # Copy to project directory
    (SHORT_PROJECT / "assets").mkdir(parents=True, exist_ok=True)
    (SHORT_PROJECT / "renders").mkdir(parents=True, exist_ok=True)
    shutil.copy2(mixed_audio, SHORT_PROJECT / "assets/narration.mp3")
    shutil.copy2(final_video, SHORT_PROJECT / "renders/final_short_en_US_9x16.mp4")
    shutil.copy2(ass_short, SHORT_PROJECT / "artifacts/captions_en_US.ass")
    now = time.time()
    os.utime(SHORT_PROJECT / "assets/narration.mp3", (now, now))
    os.utime(SHORT_PROJECT / "renders/final_short_en_US_9x16.mp4", (now + 1.0, now + 1.0))

    # Sample frames
    frame_dir = SHORT_PROJECT / "renders/frame_samples"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for sec, name in [(0, "frame_00s_hook.png"), (15, "frame_15s_benchmark.png"),
                      (30, "frame_30s_evidence.png"), (45, "frame_45s_architecture.png"),
                      (60, "frame_60s_takeaway.png")]:
        run(f'ffmpeg -y -loglevel error -ss {sec} -i {final_video} -vframes 1 {frame_dir / name}')

    # Generate ffprobe
    probe = run(f'ffprobe -v quiet -print_format json -show_format -show_streams {final_video}')
    (SHORT_PROJECT / "renders/ffprobe.json").write_text(probe, encoding="utf-8")
    print("Short render complete!")


def render_long():
    print("\n=== RENDERING US LONG-FORM (360s, 1920x1080, 16:9, SAR 1:1) ===")
    narration_txt = LONG_PROJECT / "artifacts/narration_en_US_text.txt"
    raw_audio = TMP_DIR / "long_narration_raw.mp3"
    mixed_audio = TMP_DIR / "long_mixed_audio.mp3"
    concat_video = TMP_DIR / "long_concat_raw.mp4"
    final_video = TMP_DIR / "final_long_en_US_16x9.mp4"

    # 1. TTS audio
    run(f'ffmpeg -y -loglevel error -f lavfi -i "flite=textfile={narration_txt}:voice=slt" -af "apad=whole_dur=360.0" {raw_audio}')

    # 2. Mix with music
    run(f'ffmpeg -y -loglevel error -i {raw_audio} -stream_loop -1 -i {MUSIC_BG} '
        f'-filter_complex "[0:a]volume=1.0[a0];[1:a]volume=0.15[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=3[out]" '
        f'-map "[out]" -t 360.0 {mixed_audio}')

    # 3. Render chapter segments and concatenate
    l_dir = GRAPHICS_DIR / "long"
    chapters = [
        ("ch01_prompt_bottleneck.png", 40.0),
        ("ch02_memory_hierarchy.png", 45.0),
        ("ch03_tool_sandboxing.png", 50.0),
        ("ch04_rollback_checkpoints.png", 50.0),
        ("ch05_supervisors_vs_swarms.png", 50.0),
        ("ch06_quality_gates.png", 45.0),
        ("ch07_cost_token_circuits.png", 45.0),
        ("ch08_zero_mutation_blueprint.png", 35.0),
    ]
    seg_files = []
    for idx, (img_name, dur) in enumerate(chapters):
        seg_path = TMP_DIR / f"long_seg_{idx}.mp4"
        run(f'ffmpeg -y -loglevel error -loop 1 -framerate 30 -t {dur} -i {l_dir / img_name} '
            f'-vf "pad=1924:1084:2:2:color=#0b0f19,crop=1920:1080:\'2+1.5*sin(t*0.5)\':\'2+1.5*cos(t*0.5)\',setsar=1" '
            f'-c:v libx264 -preset fast -pix_fmt yuv420p {seg_path}')
        seg_files.append(seg_path)

    list_path = TMP_DIR / "long_concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in seg_files:
            f.write(f"file '{p}'\n")

    run(f'ffmpeg -y -loglevel error -f concat -safe 0 -i {list_path} -c copy {concat_video}')

    # 4. Final compositing: Overlay audio, static subtitle container, burned-in synchronized subtitles
    srt_long = LONG_PROJECT / "artifacts/captions_en_US.srt"
    ass_long = TMP_DIR / "long_captions.ass"
    srt_to_ass(srt_long, ass_long, width=1920, height=1080, font_size=28, margin_v=65)
    vf = (
        "drawbox=x=120:y=960:w=1680:h=70:color=#0b0f19@0.9:t=fill,"
        "drawbox=x=120:y=960:w=1680:h=70:color=#38bdf8@0.5:t=2,"
        f"ass={ass_long},"
        "setsar=1"
    )

    run(f'ffmpeg -y -loglevel error -i {concat_video} -i {mixed_audio} '
        f'-vf "{vf}" -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -t 360.0 {final_video}')

    # Copy to project directory
    (LONG_PROJECT / "assets").mkdir(parents=True, exist_ok=True)
    (LONG_PROJECT / "renders").mkdir(parents=True, exist_ok=True)
    shutil.copy2(mixed_audio, LONG_PROJECT / "assets/narration.mp3")
    shutil.copy2(final_video, LONG_PROJECT / "renders/final_long_en_US_16x9.mp4")
    shutil.copy2(ass_long, LONG_PROJECT / "artifacts/captions_en_US.ass")
    now = time.time()
    os.utime(LONG_PROJECT / "assets/narration.mp3", (now, now))
    os.utime(LONG_PROJECT / "renders/final_long_en_US_16x9.mp4", (now + 1.0, now + 1.0))

    # Sample frames
    frame_dir = LONG_PROJECT / "renders/frame_samples"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for sec, name in [(10, "frame_01_ch1_prompt_bottleneck.png"),
                      (50, "frame_02_ch2_memory_hierarchy.png"),
                      (100, "frame_03_ch3_tool_sandboxing.png"),
                      (150, "frame_04_ch4_checkpoints.png"),
                      (200, "frame_05_ch5_supervisors.png"),
                      (250, "frame_06_ch6_quality_gates.png"),
                      (300, "frame_07_ch7_cost_circuits.png"),
                      (340, "frame_08_ch8_zero_mutation.png")]:
        run(f'ffmpeg -y -loglevel error -ss {sec} -i {final_video} -vframes 1 {frame_dir / name}')

    # Generate ffprobe
    probe = run(f'ffprobe -v quiet -print_format json -show_format -show_streams {final_video}')
    (LONG_PROJECT / "renders/ffprobe.json").write_text(probe, encoding="utf-8")
    print("Longform render complete!")


def invalidate_stale_approvals(short_only: bool = False):
    """Invalidate stale approval records upon fresh media render.

    Ensures that newly rendered deliverables are not mistakenly marked approved
    until scripts/independent_editorial_qa.py conducts a fresh audit.
    """
    targets = [SHORT_PROJECT] if short_only else [SHORT_PROJECT, LONG_PROJECT]
    for proj in targets:
        app = proj / "approval.json"
        if app.is_file():
            data = json.loads(app.read_text(encoding="utf-8"))
            data["approved"] = False
            data["status"] = "PENDING_INDEPENDENT_QA"
            data["timestamp"] = "2026-10-23T06:00:00Z"
            app.write_text(json.dumps(data, indent=2), encoding="utf-8")
        val = proj / "validation_status.json"
        if val.is_file():
            val_data = json.loads(val.read_text(encoding="utf-8"))
            for entry in (val_data if isinstance(val_data, list) else [val_data]):
                entry["status"] = "PENDING_INDEPENDENT_QA"
                entry["strict_quality_pass"] = False
            val.write_text(json.dumps(val_data, indent=2), encoding="utf-8")
    print("Invalidated stale approval records pending independent QA audit.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--short-only", action="store_true", help="Render only the US Short deliverable")
    args = parser.parse_args()

    ensure_graphics()
    render_short()
    if not args.short_only:
        render_long()
    invalidate_stale_approvals(short_only=args.short_only)
    print("\nALL REQUESTED DELIVERABLES SUCCESSFULLY RENDERED!")
    print("Next step: Run scripts/independent_editorial_qa.py for independent verification.")
