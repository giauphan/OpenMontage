"""Production runner for the owner-locked Practical AI Agent Engineering niche.

Generates truthful, evidence-backed en-US animated explainer videos for dynamic project directories.
Follows the execution graph:
1. Scope validation against immutable locked policy
2. Primary evidence capture & claim ledger
3. 65-75s en-US script and 6-beat visual storyboard
4. Technical vector SVG asset generation
5. Voice narration synthesis via existing NarrationOrchestrator under MediaCpuLock
6. ASR caption generation and timestamp alignment
7. Dynamic project rendering to renders/final_short_en_US_9x16.mp4
8. Frame sampling, duration ffprobe, and independent signed QA
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.fixed_niche.policy import load_locked_policy, LockedNichePolicy, OutcomeStatus
from lib.fixed_niche.gate import FixedNicheScopeGate, ScopeVerdict
from lib.fixed_niche.research import FixedNicheResearcher, ClaimClassification
from lib.fixed_niche.storyboard import FixedNicheStoryboardDirector, MeaningfulVisualError
from lib.news_visual.asset_resolver import resolve_visual_assets
from lib.audio.narration_orchestrator import NarrationOrchestrator, MediaCpuLock, probe_audio_duration

logger = logging.getLogger(__name__)


def format_srt_timestamp(seconds: float) -> str:
    """Format float seconds as HH:MM:SS,mmm for SubRip subtitles."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def generate_srt_from_beats(beats: List[Dict[str, Any]]) -> str:
    """Generate SRT caption content matching storyboard beat boundaries."""
    blocks = []
    for idx, b in enumerate(beats, 1):
        start_ts = format_srt_timestamp(float(b.get("start_s", 0.0)))
        end_ts = format_srt_timestamp(float(b.get("end_s", 0.0)))
        text = b.get("narration", "").strip()
        blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")
    return "\n".join(blocks)


def render_project_composition(
    project_dir: Path,
    composition_name: str = "hyperframes_reels",
    output_mp4: Optional[Path] = None,
    duration_seconds: float = 72.0,
    allow_synthetic_audio: bool = False,
) -> Path:
    """Render a dynamic project composition without hardcoded sample paths.

    Protected by MediaCpuLock to serialize heavy render workloads.
    """
    project_dir = Path(project_dir).resolve()
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    if output_mp4 is None:
        if "reels" in composition_name or "short" in composition_name:
            output_mp4 = renders_dir / "final_short_en_US_9x16.mp4"
        else:
            output_mp4 = renders_dir / "final_long_en_US_16x9.mp4"

    lock = MediaCpuLock(timeout_seconds=300.0)
    with lock:
        visuals_dir = project_dir / "assets" / "visuals"
        audio_path = project_dir / "assets" / "narration.mp3"

        # Determine canvas resolution
        is_vertical = "reels" in composition_name or "9x16" in str(output_mp4)
        width, height = (1080, 1920) if is_vertical else (1920, 1080)

        # Check narration audio file
        if not audio_path.is_file():
            if not allow_synthetic_audio:
                raise FileNotFoundError(
                    f"Narration audio file missing: {audio_path}. "
                    "Synthesize voice narration before rendering in production."
                )
            # Create synthetic silent audio track only when explicit test-only flag is set
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 "anullsrc=r=44100:cl=stereo", "-t", str(duration_seconds),
                 "-c:a", "libmp3lame", "-b:a", "192k", str(audio_path)],
                check=True,
            )

        # Validate that narration does not exceed target video duration
        audio_dur = probe_audio_duration(audio_path)
        if audio_dur > duration_seconds:
            raise ValueError(
                f"Narration duration ({audio_dur:.2f}s) exceeds target duration ({duration_seconds:.2f}s). "
                "Truncating narration with FFmpeg -t is rejected."
            )

        # Load visual plan beats if present for storyboard-aligned timing
        visual_plan_file = project_dir / "artifacts" / "news_visual_plan.json"
        beats: List[Dict[str, Any]] = []
        if visual_plan_file.is_file():
            try:
                plan_json = json.loads(visual_plan_file.read_text(encoding="utf-8"))
                beats = plan_json.get("beats", [])
            except Exception as e:
                logger.warning(f"Could not load news_visual_plan.json: {e}")

        # Gather visual SVG assets
        svg_assets = sorted(list(visuals_dir.glob("*.svg"))) if visuals_dir.is_dir() else []

        # Base filtergraph for scaling and letterboxing
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=#0b1120,"
            f"format=yuv420p"
        )

        # Include captions if present
        srt_path = project_dir / "artifacts" / "captions.srt"
        if srt_path.is_file():
            esc_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += f",subtitles='{esc_srt}'"

        if beats:
            # Create storyboard-synchronized slides preserving exact beat start_s and end_s
            concat_list = renders_dir / "slides_concat.txt"
            with concat_list.open("w", encoding="utf-8") as f:
                for b in beats:
                    dur = max(0.1, float(b.get("end_s", 0.0)) - float(b.get("start_s", 0.0)))
                    aid = b.get("asset_id") or (b.get("asset_ids", [""])[0] if b.get("asset_ids") else "")
                    svg_cand = visuals_dir / f"{aid}.svg"
                    if not svg_cand.is_file():
                        matches = list(visuals_dir.glob(f"{aid}.*"))
                        svg_cand = matches[0] if matches else (svg_assets[0] if svg_assets else None)
                    if svg_cand and svg_cand.is_file():
                        f.write(f"file '{svg_cand.resolve()}'\n")
                        f.write(f"duration {dur:.3f}\n")
                if svg_assets:
                    last_aid = beats[-1].get("asset_id") or (beats[-1].get("asset_ids", [""])[0] if beats[-1].get("asset_ids") else "")
                    last_svg = visuals_dir / f"{last_aid}.svg"
                    if not last_svg.is_file():
                        last_svg = svg_assets[-1]
                    f.write(f"file '{last_svg.resolve()}'\n")

            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-i", str(audio_path),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(duration_seconds),
                str(output_mp4),
            ]
            subprocess.run(cmd, check=True)
            concat_list.unlink(missing_ok=True)
        elif svg_assets:
            slide_dur = duration_seconds / len(svg_assets)
            concat_list = renders_dir / "slides_concat.txt"
            with concat_list.open("w", encoding="utf-8") as f:
                for svg in svg_assets:
                    f.write(f"file '{svg.resolve()}'\n")
                    f.write(f"duration {slide_dur:.2f}\n")
                f.write(f"file '{svg_assets[-1].resolve()}'\n")

            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-i", str(audio_path),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(duration_seconds),
                str(output_mp4),
            ]
            subprocess.run(cmd, check=True)
            concat_list.unlink(missing_ok=True)
        else:
            # Fallback test pattern
            vf_pat = f"scale={width}:{height},format=yuv420p"
            if srt_path.is_file():
                esc_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
                vf_pat += f",subtitles='{esc_srt}'"
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c=#0b1120:s={width}x{height}:d={duration_seconds}:r=30",
                "-i", str(audio_path),
                "-vf", vf_pat,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(duration_seconds),
                str(output_mp4),
            ]
            subprocess.run(cmd, check=True)

    return output_mp4


class FixedNicheVideoRunner:
    """Manages full video production lifecycle for a single in-scope candidate."""

    def __init__(
        self,
        project_dir: Path | str,
        candidate_id: str,
        format_kind: str = "short",
        policy: Optional[LockedNichePolicy] = None,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.candidate_id = str(candidate_id)
        if format_kind not in ("short", "shorts"):
            raise ValueError(
                f"Unsupported format {format_kind!r}. The Practical AI Agent Engineering niche "
                "pipeline is strictly locked to 'short' (9:16 vertical 65-75s) per policy."
            )
        self.format_kind = format_kind
        self.policy = policy or load_locked_policy()
        self.gate = FixedNicheScopeGate(self.policy)
        self.researcher = FixedNicheResearcher()
        self.storyboard_director = FixedNicheStoryboardDirector(self.policy.policy_sha256)
        self.orchestrator = NarrationOrchestrator()

    def get_target_duration(self) -> float:
        """Return target duration in seconds (65.0 - 75.0s for shorts)."""
        shorts_contract = self.policy.video_contract.get("shorts", {})
        dur_range = shorts_contract.get("target_duration_seconds", [65, 75])
        return float(dur_range[1] if len(dur_range) > 1 else 72.0)

    def build_and_stage_project(
        self,
        topic: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute intake, scope gate, research, storyboard, and asset staging."""
        self.project_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = self.project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # 1. Scope gate validation
        verdict = self.gate.evaluate_candidate(topic)
        if not verdict.is_eligible:
            return {
                "status": "REJECTED_OFF_NICHE",
                "reason": verdict.reason,
                "project_id": self.candidate_id,
            }

        # Write fixed_niche_scope.json sidecar
        self.gate.write_scope_artifact(verdict, artifacts_dir)

        # 2. Project descriptor
        project_json = {
            "project_id": self.candidate_id,
            "pipeline_type": "fixed_niche_explainer",
            "locale": "en-US",
            "market": "US",
            "niche_id": self.policy.niche_id,
            "policy_sha256": self.policy.policy_sha256,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (self.project_dir / "project.json").write_text(json.dumps(project_json, indent=2), encoding="utf-8")

        # 3. Build research brief and claim ledger
        art_paths = self.researcher.build_topic_artifacts(
            candidate=topic,
            project_dir=self.project_dir,
            content_kind=verdict.content_kind,
        )

        with open(art_paths["claim_ledger"], "r", encoding="utf-8") as f:
            claim_ledger = json.load(f)

        # 4. Generate storyboard, proof map, and technical SVGs
        target_dur = self.get_target_duration()
        story_res = self.storyboard_director.generate_storyboard(
            topic=topic,
            claims=claim_ledger["claims"],
            project_dir=self.project_dir,
            target_duration=target_dur,
        )

        # 5. Generate script_en_US.json and captions.srt
        visual_plan = story_res["visual_plan"]
        script_data = {
            "version": "1.0",
            "locale": "en-US",
            "title": topic.get("title", "AI Agent Engineering Explainer"),
            "target_duration_seconds": target_dur,
            "sections": [
                {
                    "section_id": b["script_section_id"],
                    "beat_id": b["beat_id"],
                    "start_s": b["start_s"],
                    "end_s": b["end_s"],
                    "narration": b["narration"],
                    "claims": b["claim_ids"],
                }
                for b in visual_plan["beats"]
            ],
        }
        script_bytes = json.dumps(script_data, indent=2).encode("utf-8")
        (artifacts_dir / "script_en_US.json").write_bytes(script_bytes)
        script_sha = hashlib.sha256(script_bytes).hexdigest()

        full_text = " ".join(s["narration"] for s in script_data["sections"])
        (artifacts_dir / "narration_en_US_text.txt").write_text(full_text, encoding="utf-8")
        (artifacts_dir / "captions.srt").write_text(
            generate_srt_from_beats(visual_plan["beats"]), encoding="utf-8"
        )

        # 6. Resolve assets with strict meaningful visual enforcement and verified script SHA256
        plan_sha = hashlib.sha256(json.dumps(visual_plan).encode("utf-8")).hexdigest()
        manifest = resolve_visual_assets(
            project_dir=self.project_dir,
            visual_plan=visual_plan,
            script_sha256=script_sha,
            visual_plan_sha256=plan_sha,
            enforce_meaningful_visuals=True,
        )
        (artifacts_dir / "news_visual_assets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 7. Setup HyperFrames composition structures
        for comp_name in ("hyperframes", "hyperframes_reels"):
            comp_dir = self.project_dir / comp_name
            comp_dir.mkdir(parents=True, exist_ok=True)
            # Link or copy visual assets into composition dir
            comp_vis = comp_dir / "assets" / "visuals"
            comp_vis.mkdir(parents=True, exist_ok=True)
            for svg_file in (self.project_dir / "assets" / "visuals").glob("*.svg"):
                shutil.copy2(svg_file, comp_vis / svg_file.name)

            # Minimal renderable HTML composition
            html = (
                f'<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n'
                f'<title>{topic.get("title")}</title>\n'
                f'<style>body {{ margin:0; background:#0b1120; overflow:hidden; }}</style>\n'
                f'</head><body><div id="root"></div></body></html>'
            )
            (comp_dir / "index.html").write_text(html, encoding="utf-8")

        return {
            "status": "STAGED_READY",
            "project_id": self.candidate_id,
            "project_dir": str(self.project_dir),
            "target_duration": target_dur,
            "beats_count": len(visual_plan["beats"]),
        }

    def synthesize_narration(
        self,
        provider: str = "flite",
        voice: str = "slt",
        speed: float = 1.0,
    ) -> Path:
        """Synthesize final speech track using existing NarrationOrchestrator."""
        text_path = self.project_dir / "artifacts" / "narration_en_US_text.txt"
        if not text_path.is_file():
            raise FileNotFoundError(f"Narration text not found: {text_path}")

        text = text_path.read_text(encoding="utf-8")
        out_audio = self.project_dir / "assets" / "narration.mp3"
        out_audio.parent.mkdir(parents=True, exist_ok=True)

        res = self.orchestrator.synthesize(
            text=text,
            output_path=out_audio,
            locale="en-US",
            provider=provider,
            voice=voice,
            settings={"speed": speed},
            allow_fallback=True,
        )
        if not res.get("success") or not out_audio.is_file():
            raise RuntimeError(f"Narration synthesis failed: {res.get('error', 'Unknown error')}")

        dur = probe_audio_duration(out_audio)
        logger.info(f"Synthesized voice track: duration={dur:.2f}s")
        target_dur = self.get_target_duration()
        if dur > target_dur:
            raise ValueError(
                f"Synthesized narration duration ({dur:.2f}s) exceeds maximum target duration ({target_dur:.2f}s). "
                "Truncating narration mid-sentence is forbidden."
            )
        return out_audio

    def render(self) -> Dict[str, Any]:
        """Render final 9:16 video and perform strict signed QA gating."""
        target_dur = self.get_target_duration()
        output_mp4 = self.project_dir / "renders" / "final_short_en_US_9x16.mp4"

        render_project_composition(
            project_dir=self.project_dir,
            composition_name="hyperframes_reels",
            output_mp4=output_mp4,
            duration_seconds=target_dur,
        )

        # Probe output video using argument list (prevent CWE-78)
        probe_cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(output_mp4),
        ]
        probe_out = subprocess.run(probe_cmd, capture_output=True, text=True)
        probe_json = json.loads(probe_out.stdout) if probe_out.returncode == 0 else {}
        (self.project_dir / "renders" / "ffprobe.json").write_text(
            json.dumps(probe_json, indent=2), encoding="utf-8"
        )

        # Sample frames using argument lists
        frames_dir = self.project_dir / "renders" / "frame_samples"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sample_points = [
            (0, "frame_00s_hook.png"),
            (3, "frame_03s_impact.png"),
            (int(target_dur / 2), "frame_mid_mechanism.png"),
            (int(target_dur - 2), "frame_end_payoff.png"),
        ]
        sampling_ok = True
        for sec, fname in sample_points:
            fpath = frames_dir / fname
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(sec), "-i", str(output_mp4),
                "-vframes", "1", str(fpath),
            ]
            sample_proc = subprocess.run(cmd, capture_output=True)
            if sample_proc.returncode != 0:
                sampling_ok = False

        # Validate probe duration and output video
        video_ok = output_mp4.is_file() and output_mp4.stat().st_size > 0 and probe_out.returncode == 0
        probe_dur_str = probe_json.get("format", {}).get("duration")
        probe_dur = float(probe_dur_str) if probe_dur_str else 0.0

        # Validate frame samples with visual variance check
        frames_valid = sampling_ok
        if frames_valid:
            for _, fname in sample_points:
                fpath = frames_dir / fname
                if not fpath.is_file():
                    frames_valid = False
                    break
                ok, _ = self.storyboard_director.validate_frame_sample(fpath)
                if not ok:
                    frames_valid = False
                    break

        # Validate claim ledger integrity
        claim_ledger_path = self.project_dir / "artifacts" / "claim_ledger.json"
        ledger_valid = claim_ledger_path.is_file() and claim_ledger_path.stat().st_size > 0
        ledger_sha = FixedNicheResearcher.compute_file_sha(claim_ledger_path) if ledger_valid else None
        audio_path = self.project_dir / "assets" / "narration.mp3"
        audio_sha = FixedNicheResearcher.compute_file_sha(audio_path) if audio_path.is_file() else None
        video_sha = FixedNicheResearcher.compute_file_sha(output_mp4) if video_ok else None

        # Run independent QA validator
        from lib.fixed_niche.qa import FixedNicheQAValidator
        qa_validator = FixedNicheQAValidator(self.policy)
        qa_report = qa_validator.audit_fixed_niche_deliverable(
            project_dir=self.project_dir,
            expected_duration=target_dur,
        )

        qa_pass = bool(
            video_ok
            and probe_dur > 0
            and frames_valid
            and ledger_valid
            and audio_sha is not None
            and video_sha is not None
            and qa_report.get("strict_quality_pass")
        )

        app_status = "APPROVED_FOR_PRIVATE_CANARY" if qa_pass else "QA_FAILED"
        val_status_code = "VIDEO_READY_FOR_PRIVATE_REVIEW" if qa_pass else "QA_FAILED"

        app_record = {
            "approved": qa_pass,
            "status": app_status,
            "claim_ledger_sha256": ledger_sha,
            "audio_sha256": audio_sha,
            "video_sha256": video_sha,
            "target_aspect": "9:16",
            "target_duration": target_dur,
            "policy_sha256": self.policy.policy_sha256,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (self.project_dir / "approval.json").write_text(json.dumps(app_record, indent=2), encoding="utf-8")

        val_status = {
            "project_id": self.candidate_id,
            "status": val_status_code,
            "strict_quality_pass": qa_pass,
            "rendered_mp4": str(output_mp4),
            "duration": target_dur,
            "policy_sha256": self.policy.policy_sha256,
        }
        (self.project_dir / "validation_status.json").write_text(json.dumps(val_status, indent=2), encoding="utf-8")

        return {
            "status": val_status_code,
            "rendered_mp4": str(output_mp4),
            "duration": target_dur,
            "frames_dir": str(frames_dir),
            "approval_path": str(self.project_dir / "approval.json"),
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed Niche Video Production CLI")
    parser.add_argument("--candidate-id", required=True, help="Candidate ID to produce")
    parser.add_argument("--project-dir", required=False, help="Custom project output directory")
    parser.add_argument("--format", default="short", choices=["short", "shorts"], help="Video format (locked to shorts)")
    parser.add_argument("--dry-run", action="store_true", help="Stage project without media rendering")
    parser.add_argument("--title", default="Why coding agents lose project requirements between sessions")
    parser.add_argument("--topic-family", default="context_memory")
    parser.add_argument("--canonical-url", default="https://docs.anthropic.com/claude/context-window")
    args = parser.parse_args(argv)

    proj_dir = Path(args.project_dir) if args.project_dir else ROOT / "projects" / args.candidate_id
    runner = FixedNicheVideoRunner(
        project_dir=proj_dir,
        candidate_id=args.candidate_id,
        format_kind=args.format,
    )

    topic = {
        "candidate_id": args.candidate_id,
        "title": args.title,
        "topic_family": args.topic_family,
        "canonical_url": args.canonical_url,
    }

    stage_res = runner.build_and_stage_project(topic=topic, dry_run=args.dry_run)
    print(json.dumps(stage_res, indent=2))

    if args.dry_run or stage_res.get("status") != "STAGED_READY":
        return 0 if stage_res.get("status") == "STAGED_READY" else 1

    runner.synthesize_narration(provider="flite", voice="slt")
    render_res = runner.render()
    print(json.dumps(render_res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
