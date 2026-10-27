"""Production runner for the owner-locked Practical AI Agent Engineering niche.

Generates truthful, evidence-backed en-US animated explainer videos for dynamic project directories.
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
from lib.fixed_niche.captions import format_srt_timestamp, generate_srt_from_beats
from lib.fixed_niche.hyperframes_composer import (
    materialize_hyperframes_project, render_hyperframes_composition, render_ffmpeg_composition,
)
from tools.news.fixed_niche_sources import FixedNicheSourceAdapter

logger = logging.getLogger(__name__)


def render_project_composition(
    project_dir: Path,
    composition_name: str = "hyperframes_reels",
    output_mp4: Optional[Path] = None,
    duration_seconds: float = 72.0,
    allow_synthetic_audio: bool = False,
    burn_captions: bool = False,
    renderer: str = "auto",
) -> Path:
    """Render a dynamic project composition via HyperFrames or FFmpeg.

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
        audio_path = project_dir / "assets" / "narration.mp3"
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

        # In production renders, warn if narration duration is below minimum allowed duration
        if not allow_synthetic_audio and duration_seconds >= 60.0 and audio_dur < 60.0:
            logger.warning(
                f"Narration duration ({audio_dur:.2f}s) is below 60.0s. "
                "Aligning render duration to prevent out-of-sync playback."
            )

        # Determine actual render duration strictly matching narration audio if valid within shorts contract
        render_dur = audio_dur if 65.0 <= audio_dur <= 75.0 else duration_seconds

        # Dispatch renderer: auto, hyperframes, or ffmpeg
        chosen_renderer = renderer.lower() if renderer else "auto"
        if chosen_renderer == "auto":
            env_renderer = os.environ.get("OPENMONTAGE_RENDERER", "").lower()
            if env_renderer in ("hyperframes", "ffmpeg"):
                chosen_renderer = env_renderer
            else:
                # Prioritize HyperFrames when composition exists
                has_hf = (
                    (project_dir / composition_name / "index.html").is_file()
                    or (project_dir / "hyperframes" / "index.html").is_file()
                )
                chosen_renderer = "hyperframes" if has_hf else "ffmpeg"

        if chosen_renderer == "hyperframes":
            comp_dir = project_dir / composition_name
            if not (comp_dir / "index.html").is_file():
                comp_dir = project_dir / "hyperframes"
            if audio_path.is_file():
                comp_audio = comp_dir / "assets" / "narration.mp3"
                comp_audio.parent.mkdir(parents=True, exist_ok=True)
                if not comp_audio.is_file() or comp_audio.stat().st_size != audio_path.stat().st_size:
                    shutil.copy2(audio_path, comp_audio)
            ass_path = project_dir / "artifacts" / "captions.ass"
            try:
                return render_hyperframes_composition(
                    comp_dir=comp_dir,
                    output_mp4=output_mp4,
                    burn_captions=burn_captions,
                    ass_path=ass_path if burn_captions else None,
                )
            except Exception as hf_err:
                logger.warning(f"HyperFrames render encountered issue ({hf_err}), falling back to FFmpeg composition")
                return render_ffmpeg_composition(
                    project_dir=project_dir,
                    output_mp4=output_mp4,
                    render_dur=render_dur,
                    width=width,
                    height=height,
                    burn_captions=burn_captions,
                )
        else:
            return render_ffmpeg_composition(
                project_dir=project_dir,
                output_mp4=output_mp4,
                render_dur=render_dur,
                width=width,
                height=height,
                burn_captions=burn_captions,
            )

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
        self._staged_topic: Optional[Dict[str, Any]] = None

    def get_target_duration(self) -> float:
        """Return target duration in seconds (65.0 - 75.0s for shorts, default 72.0s)."""
        shorts_contract = self.policy.video_contract.get("shorts", {})
        dur_range = shorts_contract.get("target_duration_seconds", [65, 75])
        if len(dur_range) >= 2 and dur_range[0] <= 72.0 <= dur_range[1]:
            return 72.0
        return float(dur_range[0] if dur_range else 72.0)

    def build_and_stage_project(
        self,
        topic: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute intake, scope gate, research, storyboard, and asset staging."""
        self._staged_topic = topic
        # 1. Scope gate validation before any filesystem side effects
        verdict = self.gate.evaluate_candidate(topic)
        if not verdict.is_eligible:
            return {
                "status": "REJECTED_OFF_NICHE",
                "reason": verdict.reason,
                "project_id": self.candidate_id,
            }

        self.project_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = self.project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

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

        from lib.fixed_niche.captions import build_and_align_captions
        c_width = 1080 if self.format_kind in ("short", "shorts") else 1920
        c_height = 1920 if self.format_kind in ("short", "shorts") else 1080
        srt_content, ass_content, _ = build_and_align_captions(
            beats=visual_plan["beats"],
            audio_path=None,
            width=c_width,
            height=c_height,
        )
        (artifacts_dir / "captions.srt").write_text(srt_content, encoding="utf-8")
        (artifacts_dir / "captions.ass").write_text(ass_content, encoding="utf-8")

        # 6. Orchestrate and resolve assets with strict meaningful visual enforcement
        from lib.news_visual.visual_asset_orchestrator import VisualAssetOrchestrator
        orchestrator = VisualAssetOrchestrator()
        orch_res = orchestrator.orchestrate_plan_assets(
            project_dir=self.project_dir,
            plan=visual_plan,
            topic=topic,
            claim_ledger=claim_ledger.get("claims", []),
        )
        if orch_res.get("summary", {}).get("blocked_missing_proof", 0) > 0:
            return {
                "status": "BLOCKED_MISSING_PROOF",
                "project_id": self.candidate_id,
                "beat_results": orch_res.get("beat_results", {}),
            }

        plan_sha = hashlib.sha256(json.dumps(visual_plan).encode("utf-8")).hexdigest()
        manifest = resolve_visual_assets(
            project_dir=self.project_dir,
            visual_plan=visual_plan,
            script_sha256=script_sha,
            visual_plan_sha256=plan_sha,
            enforce_meaningful_visuals=True,
        )
        (artifacts_dir / "news_visual_assets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 6.5. Generate animated diagram sidecar if visual style is active
        visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "legacy")
        flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") in ("1", "true", "True")
        if visual_style == "animated_agent_diagram_v1" or flag_enabled:
            from lib.visual_style.diagram_director import AnimatedDiagramDirector
            director = AnimatedDiagramDirector(policy_sha256=self.policy.policy_sha256)
            diag_plan = director.plan_diagram_animation(
                project_id=self.candidate_id,
                topic=topic,
                claims=claim_ledger.get("claims", []),
                target_duration=target_dur,
                script_sha256=script_sha,
                source_claim_ledger_sha256=hashlib.sha256(json.dumps(claim_ledger).encode("utf-8")).hexdigest(),
                source_visual_plan_sha256=plan_sha,
            )
            director.write_sidecar(diag_plan, self.project_dir)

        # 7. Setup HyperFrames composition structures
        from lib.fixed_niche.hyperframes_composer import materialize_hyperframes_project
        materialize_hyperframes_project(
            project_dir=self.project_dir,
            topic=topic,
            visual_plan=visual_plan,
            duration=target_dur,
        )

        return {
            "status": "STAGED_READY",
            "project_id": self.candidate_id,
            "project_dir": str(self.project_dir),
            "target_duration": target_dur,
            "beats_count": len(visual_plan["beats"]),
        }

    def _restage_for_duration(self, dur: float) -> int:
        """Re-stage storyboard and orchestrate assets when narration duration exceeds beat hold limit."""
        topic_data = self._staged_topic
        if not topic_data:
            tb_file = self.project_dir / "artifacts" / "topic_brief.json"
            topic_data = json.loads(tb_file.read_text(encoding="utf-8")) if tb_file.is_file() else {"candidate_id": self.candidate_id}
        cl_file = self.project_dir / "artifacts" / "claim_ledger.json"
        claims = json.loads(cl_file.read_text(encoding="utf-8")).get("claims", []) if cl_file.is_file() else []
        if not claims:
            raise ValueError(f"Cannot re-stage storyboard for {dur:.2f}s: claim ledger is unavailable.")

        story_res = self.storyboard_director.generate_storyboard(
            topic=topic_data, claims=claims, project_dir=self.project_dir, target_duration=dur
        )
        visual_plan = story_res["visual_plan"]
        beats = visual_plan.get("beats", [])

        script_data = {
            "version": "1.0", "locale": "en-US", "title": topic_data.get("title", "AI Agent Engineering Explainer"),
            "target_duration_seconds": dur,
            "sections": [
                {"section_id": b["script_section_id"], "beat_id": b["beat_id"], "start_s": b["start_s"],
                 "end_s": b["end_s"], "narration": b["narration"], "claims": b["claim_ids"]}
                for b in beats
            ],
        }
        script_bytes = json.dumps(script_data, indent=2).encode("utf-8")
        (self.project_dir / "artifacts" / "script_en_US.json").write_bytes(script_bytes)
        from lib.news_visual.visual_asset_orchestrator import VisualAssetOrchestrator
        orch_res = VisualAssetOrchestrator().orchestrate_plan_assets(
            project_dir=self.project_dir, plan=visual_plan, topic=topic_data, claim_ledger=claims
        )
        if orch_res.get("summary", {}).get("blocked_missing_proof", 0) > 0:
            raise ValueError(f"Re-staging for {dur:.2f}s blocked: proof-bearing beats missing verified evidence.")

        from lib.news_visual.asset_resolver import resolve_visual_assets
        plan_sha = hashlib.sha256(json.dumps(visual_plan).encode("utf-8")).hexdigest()
        manifest = resolve_visual_assets(
            project_dir=self.project_dir, visual_plan=visual_plan,
            script_sha256=hashlib.sha256(script_bytes).hexdigest(), visual_plan_sha256=plan_sha,
            enforce_meaningful_visuals=True,
        )
        (self.project_dir / "artifacts" / "news_visual_assets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "legacy")
        flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") in ("1", "true", "True")
        if visual_style == "animated_agent_diagram_v1" or flag_enabled:
            from lib.visual_style.diagram_director import AnimatedDiagramDirector
            director = AnimatedDiagramDirector(policy_sha256=self.policy.policy_sha256)
            diag_plan = director.plan_diagram_animation(
                project_id=self.candidate_id,
                topic=topic_data,
                claims=claims,
                target_duration=dur,
                script_sha256=hashlib.sha256(script_bytes).hexdigest(),
                source_claim_ledger_sha256=hashlib.sha256(json.dumps(claims).encode("utf-8")).hexdigest(),
                source_visual_plan_sha256=plan_sha,
            )
            director.write_sidecar(diag_plan, self.project_dir)

        return len(beats)

    def synthesize_narration(
        self,
        provider: Optional[str] = None,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Path:
        """Synthesize final speech track using existing NarrationOrchestrator."""
        text_path = self.project_dir / "artifacts" / "narration_en_US_text.txt"
        if not text_path.is_file():
            raise FileNotFoundError(f"Narration text not found: {text_path}")

        text = text_path.read_text(encoding="utf-8")
        out_audio = self.project_dir / "assets" / "narration.mp3"
        out_audio.parent.mkdir(parents=True, exist_ok=True)

        if provider is None:
            from tools.audio.kokoro_local_tts import is_kokoro_available
            provider = "kokoro" if is_kokoro_available() else "flite"

        if voice is None:
            voice = self.orchestrator.resolve_default_voice(locale="en-US", provider=provider)

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
        n_beats = 0
        plan_p = self.project_dir / "artifacts" / "news_visual_plan.json"
        if plan_p.is_file():
            try:
                n_beats = len(json.loads(plan_p.read_text(encoding="utf-8")).get("beats", []))
            except Exception:
                pass
        dur_range = self.policy.video_contract.get("shorts", {}).get("target_duration_seconds", [65, 75])
        policy_max = float(dur_range[1]) if len(dur_range) >= 2 else 75.0
        if dur > policy_max:
            raise ValueError(
                f"Synthesized narration duration ({dur:.2f}s) exceeds maximum allowed duration ({policy_max:.2f}s). "
                "Truncating narration mid-sentence is forbidden."
            )

        # In production synthesis with neural voice, reject narration outside 65-75s contract
        if provider == "kokoro" and not (65.0 <= dur <= 75.0):
            raise ValueError(
                f"Synthesized narration duration ({dur:.2f}s) is outside required [65.0, 75.0]s shorts contract. "
                "Full technical analysis across all 6 beats is required per VIDEO_PLAYBOOK.md."
            )

        if n_beats > 0 and dur > n_beats * 12.0:
            if dur <= policy_max:
                logger.info(
                    f"Narration duration ({dur:.2f}s) exceeds {n_beats} beats x 12.0s hold limit; "
                    f"re-staging storyboard with target_duration={dur:.2f}s."
                )
                n_beats = self._restage_for_duration(dur)
            else:
                raise ValueError(
                    f"Synthesized narration duration ({dur:.2f}s) exceeds maximum allowed duration ({policy_max:.2f}s)."
                )

        # Re-align all timed artifacts with synthesized audio duration
        visual_plan_file = self.project_dir / "artifacts" / "news_visual_plan.json"
        script_file = self.project_dir / "artifacts" / "script_en_US.json"
        proof_map_file = self.project_dir / "artifacts" / "video_proof_map.json"
        srt_file = self.project_dir / "artifacts" / "captions.srt"
        assets_file = self.project_dir / "artifacts" / "news_visual_assets.json"

        if visual_plan_file.is_file() and dur > 0:
            try:
                plan_json = json.loads(visual_plan_file.read_text(encoding="utf-8"))
                beats = plan_json.get("beats", [])
                if beats:
                    planned_total = float(beats[-1].get("end_s", 0.0)) - float(beats[0].get("start_s", 0.0))
                    if planned_total > 0:
                        align_dur = dur if 65.0 <= dur <= 75.0 else target_dur
                        scale = align_dur / planned_total
                        curr_start = 0.0
                        for b in beats:
                            beat_dur = (float(b.get("end_s", 0.0)) - float(b.get("start_s", 0.0))) * scale
                            b["start_s"] = round(curr_start, 3)
                            curr_start += beat_dur
                            b["end_s"] = round(curr_start, 3)
                        beats[-1]["end_s"] = round(align_dur, 3)

                        # Prepare all reconciled payload dictionaries before writing
                        from lib.fixed_niche.captions import build_and_align_captions
                        c_width = 1080 if self.format_kind in ("short", "shorts") else 1920
                        c_height = 1920 if self.format_kind in ("short", "shorts") else 1080
                        srt_content, ass_content, _ = build_and_align_captions(
                            beats=beats,
                            audio_path=out_audio,
                            width=c_width,
                            height=c_height,
                        )
                        ass_file = self.project_dir / "artifacts" / "captions.ass"
                        beat_map = {b["beat_id"]: b for b in beats}

                        script_bytes_to_write = None
                        assets_json_to_write = None
                        if script_file.is_file():
                            script_json = json.loads(script_file.read_text(encoding="utf-8"))
                            script_json["target_duration_seconds"] = round(align_dur, 3)
                            for sec in script_json.get("sections", []):
                                bid = sec.get("beat_id")
                                if bid in beat_map:
                                    sec["start_s"] = beat_map[bid]["start_s"]
                                    sec["end_s"] = beat_map[bid]["end_s"]
                            script_bytes_to_write = json.dumps(script_json, indent=2).encode("utf-8")
                            if assets_file.is_file():
                                assets_json = json.loads(assets_file.read_text(encoding="utf-8"))
                                assets_json["script_sha256"] = hashlib.sha256(script_bytes_to_write).hexdigest()
                                assets_json_to_write = json.dumps(assets_json, indent=2)

                        proof_json_to_write = None
                        if proof_map_file.is_file():
                            proof_json = json.loads(proof_map_file.read_text(encoding="utf-8"))
                            for pb in proof_json.get("beats", []):
                                bid = pb.get("beat_id")
                                if bid in beat_map:
                                    pb["start_s"] = beat_map[bid]["start_s"]
                                    pb["end_s"] = beat_map[bid]["end_s"]
                            proof_json_to_write = json.dumps(proof_json, indent=2)

                        # Write all verified artifact updates
                        visual_plan_file.write_text(json.dumps(plan_json, indent=2), encoding="utf-8")
                        srt_file.write_text(srt_content, encoding="utf-8")
                        ass_file.write_text(ass_content, encoding="utf-8")
                        if script_bytes_to_write is not None:
                            script_file.write_bytes(script_bytes_to_write)
                        if assets_json_to_write is not None:
                            assets_file.write_text(assets_json_to_write, encoding="utf-8")
                        if proof_json_to_write is not None:
                            proof_map_file.write_text(proof_json_to_write, encoding="utf-8")

                        # Re-materialize HyperFrames compositions with the reconciled audio duration
                        from lib.fixed_niche.hyperframes_composer import materialize_hyperframes_project
                        topic_for_comp = self._staged_topic or {"candidate_id": self.candidate_id}
                        visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "legacy")
                        flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") in ("1", "true", "True")
                        if visual_style == "animated_agent_diagram_v1" or flag_enabled:
                            from lib.visual_style.diagram_director import AnimatedDiagramDirector
                            cl_file = self.project_dir / "artifacts" / "claim_ledger.json"
                            claims = json.loads(cl_file.read_text(encoding="utf-8")).get("claims", []) if cl_file.is_file() else []
                            director = AnimatedDiagramDirector(policy_sha256=self.policy.policy_sha256)
                            diag_plan = director.plan_diagram_animation(
                                project_id=self.candidate_id,
                                topic=topic_for_comp,
                                claims=claims,
                                target_duration=align_dur,
                                script_sha256=hashlib.sha256(script_file.read_bytes()).hexdigest(),
                                source_claim_ledger_sha256=hashlib.sha256(json.dumps(claims).encode("utf-8")).hexdigest(),
                                source_visual_plan_sha256=hashlib.sha256(json.dumps(plan_json).encode("utf-8")).hexdigest(),
                            )
                            director.write_sidecar(diag_plan, self.project_dir)

                        materialize_hyperframes_project(
                            project_dir=self.project_dir,
                            topic=topic_for_comp,
                            visual_plan=plan_json,
                            duration=align_dur,
                        )
            except Exception as e:
                raise RuntimeError(f"Failed to realign timed artifacts to synthesized narration duration: {e}") from e

        return out_audio

    def render(self, burn_captions: bool = False, renderer: str = "auto") -> Dict[str, Any]:
        """Render final 9:16 video and perform strict signed QA gating."""
        target_dur = self.get_target_duration()
        output_mp4 = self.project_dir / "renders" / "final_short_en_US_9x16.mp4"
        audio_path = self.project_dir / "assets" / "narration.mp3"
        audio_dur = probe_audio_duration(audio_path) if audio_path.is_file() else -1.0
        # Enforce shorts duration contract: select audio_dur within [65.0, 75.0], fallback to target_dur
        render_dur = audio_dur if 65.0 <= audio_dur <= 75.0 else target_dur

        render_project_composition(
            project_dir=self.project_dir, composition_name="hyperframes_reels",
            output_mp4=output_mp4, duration_seconds=render_dur,
            burn_captions=burn_captions, renderer=renderer,
        )

        probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(output_mp4)]
        probe_out = subprocess.run(probe_cmd, capture_output=True, text=True)
        probe_json = json.loads(probe_out.stdout) if probe_out.returncode == 0 else {}
        (self.project_dir / "renders" / "ffprobe.json").write_text(json.dumps(probe_json, indent=2), encoding="utf-8")

        # Sample frames using argument lists
        frames_dir = self.project_dir / "renders" / "frame_samples"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sample_points = [
            (0, "frame_00s_hook.png"),
            (3, "frame_03s_impact.png"),
            (int(render_dur / 2), "frame_mid_mechanism.png"),
            (int(render_dur - 2), "frame_end_payoff.png"),
        ]
        sampling_ok = True
        for sec, fname in sample_points:
            fpath = frames_dir / fname
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(sec), "-i", str(output_mp4), "-vframes", "1", str(fpath)]
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

        actual_dur = probe_dur if probe_dur > 0 else render_dur

        if qa_pass:
            from lib.qa_signing import sign_approval_record
            app_record = sign_approval_record(
                project_id=self.candidate_id,
                media_sha256=video_sha,
                claim_ledger_sha256=ledger_sha,
                timestamp_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                reviewer="independent_qa_supervisor",
                format_type="short",
                audit_trail={
                    "status": app_status,
                    "audio_sha256": audio_sha,
                    "video_sha256": video_sha,
                    "target_aspect": "9:16",
                    "duration": actual_dur,
                    "target_duration": target_dur,
                    "policy_sha256": self.policy.policy_sha256,
                    "strict_quality_pass": True,
                },
            )
            # Retain top-level attributes for compatibility
            app_record["status"] = app_status
            app_record["audio_sha256"] = audio_sha
            app_record["video_sha256"] = video_sha
            app_record["target_aspect"] = "9:16"
            app_record["duration"] = actual_dur
            app_record["target_duration"] = target_dur
            app_record["policy_sha256"] = self.policy.policy_sha256
        else:
            app_record = {
                "approved": False,
                "status": app_status,
                "claim_ledger_sha256": ledger_sha,
                "audio_sha256": audio_sha,
                "video_sha256": video_sha,
                "target_aspect": "9:16",
                "duration": actual_dur,
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
            "duration": actual_dur,
            "target_duration": target_dur,
            "policy_sha256": self.policy.policy_sha256,
        }
        (self.project_dir / "validation_status.json").write_text(json.dumps(val_status, indent=2), encoding="utf-8")

        return {
            "status": val_status_code,
            "rendered_mp4": str(output_mp4),
            "duration": actual_dur,
            "target_duration": target_dur,
            "frames_dir": str(frames_dir),
            "approval_path": str(self.project_dir / "approval.json"),
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed Niche Video Production CLI")
    parser.add_argument("--candidate-id", required=False, default=None, help="Candidate ID to produce")
    parser.add_argument("--auto-select", action="store_true", default=False, help="Automatically discover, filter, and score top in-scope candidate")
    parser.add_argument("--candidates-file", required=False, default=None, help="Path to YAML/JSON candidates pool file")
    parser.add_argument("--use-test-fixtures", action="store_true", default=False, help="Explicitly allow loading test fixtures for testing/rehearsals")
    parser.add_argument("--renderer", choices=["auto", "hyperframes", "ffmpeg"], default="auto", help="Video composition renderer (auto, hyperframes, ffmpeg)")
    parser.add_argument("--project-dir", required=False, help="Custom project output directory")
    parser.add_argument("--format", default="short", choices=["short", "shorts"], help="Video format (locked to shorts)")
    parser.add_argument("--provider", default=None, help="TTS provider (kokoro, flite, edge, pocket18, omniroute)")
    parser.add_argument("--voice", default=None, help="TTS voice override")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--dry-run", action="store_true", help="Stage project without media rendering")
    parser.add_argument("--burn-captions", action="store_true", default=False, help="Burn subtitles into video (default: False, clean video)")
    parser.add_argument("--title", default=None)
    parser.add_argument("--topic-family", default=None)
    parser.add_argument("--canonical-url", default=None)
    parser.add_argument("--enable-ai-visuals", action=argparse.BooleanOptionalAction, default=False, help="Enable Muse AI image generation for conceptual illustration beats (operator opt-in)")
    args = parser.parse_args(argv)

    if args.enable_ai_visuals:
        os.environ["AI_VISUAL_ENABLED"] = "1"
    else:
        os.environ["AI_VISUAL_ENABLED"] = "0"

    policy = load_locked_policy()
    gate = FixedNicheScopeGate(policy)

    # Automatic topic selection when requested or candidate-id is omitted
    topic: Dict[str, Any]
    candidate_id = args.candidate_id

    candidates_pool: List[Dict[str, Any]] = []
    if args.candidates_file:
        c_file = Path(args.candidates_file)
        if c_file.is_file():
            try:
                import yaml
                raw_data = yaml.safe_load(c_file.read_text(encoding="utf-8"))
                candidates_pool = raw_data.get("positive_cases", []) if isinstance(raw_data, dict) else raw_data
            except Exception as e:
                logger.warning(f"Failed to load candidates pool from {c_file}: {e}")
    elif args.use_test_fixtures:
        c_file = ROOT / "tests/fixtures/fixed_niche_cases.yaml"
        if c_file.is_file():
            try:
                import yaml
                raw_data = yaml.safe_load(c_file.read_text(encoding="utf-8"))
                candidates_pool = raw_data.get("positive_cases", []) if isinstance(raw_data, dict) else raw_data
            except Exception as e:
                logger.warning(f"Failed to load test fixtures from {c_file}: {e}")
    elif args.auto_select or not candidate_id:
        adapter = FixedNicheSourceAdapter()
        candidates_pool = adapter.discover_production_candidates()

    matched_cand = next((c for c in candidates_pool if (c.get("candidate_id") == candidate_id or c.get("id") == candidate_id)), None) if candidate_id else None

    if matched_cand:
        topic = dict(matched_cand)
        topic["candidate_id"] = candidate_id
        if args.title:
            topic["title"] = args.title
        if args.topic_family:
            topic["topic_family"] = args.topic_family
        if args.canonical_url:
            topic["canonical_url"] = args.canonical_url
    elif args.auto_select or not candidate_id:
        eligible = [c for c in candidates_pool if gate.evaluate_candidate(c).is_eligible]
        if not eligible:
            print(json.dumps({
                "status": "NO_ELIGIBLE_TOPIC",
                "message": "Zero eligible topics found in candidate pool; no project staged.",
            }, indent=2))
            return 0

        from lib.fixed_niche.ranker import FixedNicheTopicScorer
        ranked = FixedNicheTopicScorer().rank_candidates([(c, gate.evaluate_candidate(c)) for c in eligible])
        top_cand = ranked[0] if ranked else eligible[0]
        candidate_id = top_cand.get("id") or top_cand.get("candidate_id") or "cand_selected"
        topic = dict(top_cand)
        topic["candidate_id"] = candidate_id
        if args.title:
            topic["title"] = args.title
        if args.topic_family:
            topic["topic_family"] = args.topic_family
        if args.canonical_url:
            topic["canonical_url"] = args.canonical_url
    else:
        topic = {
            "candidate_id": candidate_id,
            "title": args.title or "Why coding agents lose project requirements between sessions",
            "topic_family": args.topic_family or "context_memory",
            "canonical_url": args.canonical_url or "https://docs.anthropic.com/claude/context-window",
        }

    proj_dir = Path(args.project_dir) if args.project_dir else ROOT / "projects" / candidate_id
    runner = FixedNicheVideoRunner(
        project_dir=proj_dir, candidate_id=candidate_id, format_kind=args.format, policy=policy
    )

    stage_res = runner.build_and_stage_project(topic=topic, dry_run=args.dry_run)
    print(json.dumps(stage_res, indent=2))

    if args.dry_run or stage_res.get("status") != "STAGED_READY":
        return 0 if stage_res.get("status") == "STAGED_READY" else 1

    runner.synthesize_narration(provider=args.provider, voice=args.voice, speed=args.speed)
    render_res = runner.render(burn_captions=args.burn_captions, renderer=args.renderer)
    print(json.dumps(render_res, indent=2))
    return 0 if render_res.get("status") == "VIDEO_READY_FOR_PRIVATE_REVIEW" else 1


if __name__ == "__main__":
    sys.exit(main())
