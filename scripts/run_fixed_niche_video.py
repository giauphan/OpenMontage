"""Production runner for the owner-locked Practical AI Agent Engineering niche.

Generates truthful, evidence-backed en-US animated explainer videos for dynamic project directories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
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
from lib.fixed_niche.render_pipeline import render_project_composition
from tools.news.fixed_niche_sources import FixedNicheSourceAdapter

logger = logging.getLogger(__name__)

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
        visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg")
        flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") not in ("0", "false", "False")
        if visual_style == "animated_agent_diagram_v1" and flag_enabled:
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

        visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg")
        flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") not in ("0", "false", "False")
        if visual_style == "animated_agent_diagram_v1" and flag_enabled:
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

    def _resolve_tts_speed(self, provider: str, speed: float) -> float:
        if not math.isclose(speed, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            return speed
        speeds = {"kokoro": 1.36, "elevenlabs": 1.05, "edge": 1.10}
        return speeds.get(provider, speed)

    def _invoke_initial_synthesis(
        self, text: str, out_audio: Path, provider: str, voice: str, speed: float
    ) -> tuple[dict[str, Any], str, str, float]:
        try:
            res = self.orchestrator.synthesize(
                text=text, output_path=out_audio, locale="en-US", provider=provider, voice=voice, settings={"speed": speed}, allow_fallback=True,
            )
            return res, provider, voice, speed
        except Exception as exc:
            if provider != "elevenlabs":
                raise
            logger.warning(f"ElevenLabs synthesis failed ({exc}); falling back to local TTS engine.")
            from tools.audio.kokoro_local_tts import is_kokoro_available
            f_prov = "kokoro" if is_kokoro_available() else "flite"
            f_voice = self.orchestrator.resolve_default_voice(locale="en-US", provider=f_prov)
            f_speed = 1.36 if f_prov == "kokoro" else 1.0
            res = self.orchestrator.synthesize(
                text=text, output_path=out_audio, locale="en-US", provider=f_prov, voice=f_voice, settings={"speed": f_speed}, allow_fallback=True
            )
            return res, f_prov, f_voice, f_speed

    def _calibrate_speed_and_tempo(
        self, text: str, out_audio: Path, actual_prov: str, voice: str, speed: float, dur: float, policy_max: float
    ) -> float:
        if actual_prov in ("kokoro", "elevenlabs", "edge") and not (65.0 <= dur <= 75.0):
            ratio = dur / 70.0
            speed_min, speed_max = (0.8, 1.4) if actual_prov in ("elevenlabs", "edge") else (0.8, 1.8)
            adj_speed = round(speed * ratio, 2)
            if adj_speed != speed and speed_min <= adj_speed <= speed_max:
                logger.info(f"Re-synthesizing narration with calibrated speed {adj_speed} (previous duration {dur:.2f}s)")
                self.orchestrator.synthesize(
                    text=text, output_path=out_audio, locale="en-US", provider=actual_prov, voice=voice, settings={"speed": adj_speed}, allow_fallback=True,
                )
                dur = probe_audio_duration(out_audio)
        if policy_max < dur <= 95.0:
            tempo = round(dur / 70.0, 3)
            tmp_t = out_audio.with_suffix(".tempo.mp3")
            res_t = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_audio), "-filter:a", f"atempo={tempo}", "-vn", str(tmp_t)], capture_output=True)
            if res_t.returncode == 0 and tmp_t.is_file():
                os.replace(tmp_t, out_audio)
                dur = probe_audio_duration(out_audio)
                logger.info(f"Auto-calibrated narration tempo with ffmpeg atempo={tempo}: duration={dur:.2f}s")
        return dur

    def _validate_narration_durations(self, dur: float, actual_prov: str, policy_max: float, n_beats: int) -> None:
        if dur > policy_max:
            raise ValueError(
                f"Synthesized narration duration ({dur:.2f}s) exceeds maximum allowed duration ({policy_max:.2f}s). Truncating narration mid-sentence is forbidden."
            )
        if actual_prov in ("kokoro", "elevenlabs", "edge") and not (65.0 <= dur <= 75.0):
            raise ValueError(
                f"Synthesized narration duration ({dur:.2f}s) is outside required [65.0, 75.0]s shorts contract. Full technical analysis across all 6 beats is required per VIDEO_PLAYBOOK.md."
            )
        if n_beats > 0 and dur > n_beats * 12.0:
            if dur <= policy_max:
                logger.info(f"Narration duration ({dur:.2f}s) exceeds {n_beats} beats x 12.0s hold limit; re-staging storyboard with target_duration={dur:.2f}s.")
                self._restage_for_duration(dur)
            else:
                raise ValueError(f"Synthesized narration duration ({dur:.2f}s) exceeds maximum allowed duration ({policy_max:.2f}s).")

    def _reconcile_artifacts(self, dur: float, target_dur: float, out_audio: Path) -> None:
        plan_f = self.project_dir / "artifacts" / "news_visual_plan.json"
        if not (plan_f.is_file() and dur > 0):
            return
        try:
            plan_json = json.loads(plan_f.read_text(encoding="utf-8"))
            beats = plan_json.get("beats", [])
            if not beats:
                return
            p_total = float(beats[-1].get("end_s", 0.0)) - float(beats[0].get("start_s", 0.0))
            if p_total <= 0:
                return
            align_dur = dur if 65.0 <= dur <= 75.0 else target_dur
            scale = align_dur / p_total
            curr_start = 0.0
            for b in beats:
                beat_dur = (float(b.get("end_s", 0.0)) - float(b.get("start_s", 0.0))) * scale
                b["start_s"], curr_start = round(curr_start, 3), curr_start + beat_dur
                b["end_s"] = round(curr_start, 3)
            beats[-1]["end_s"] = round(align_dur, 3)
            self._write_reconciled_artifacts(beats, align_dur, out_audio, plan_json, plan_f)
        except Exception as e:
            raise RuntimeError(f"Failed to realign timed artifacts to synthesized narration duration: {e}") from e

    def _write_reconciled_artifacts(
        self, beats: list[dict], align_dur: float, out_audio: Path, plan_json: dict, plan_f: Path
    ) -> None:
        from lib.fixed_niche.captions import build_and_align_captions
        c_w = 1080 if self.format_kind in ("short", "shorts") else 1920
        c_h = 1920 if self.format_kind in ("short", "shorts") else 1080
        srt_content, ass_content, _ = build_and_align_captions(beats=beats, audio_path=out_audio, width=c_w, height=c_h)
        (self.project_dir / "artifacts" / "captions.srt").write_text(srt_content, encoding="utf-8")
        (self.project_dir / "artifacts" / "captions.ass").write_text(ass_content, encoding="utf-8")

        beat_map = {b["beat_id"]: b for b in beats}
        script_file = self.project_dir / "artifacts" / "script_en_US.json"
        assets_file = self.project_dir / "artifacts" / "news_visual_assets.json"
        ev_file = self.project_dir / "artifacts" / "news_evidence.json"
        proof_map_file = self.project_dir / "artifacts" / "video_proof_map.json"

        if script_file.is_file():
            s_json = json.loads(script_file.read_text(encoding="utf-8"))
            s_json["target_duration_seconds"] = round(align_dur, 3)
            for sec in s_json.get("sections", []):
                bid = sec.get("beat_id")
                if bid in beat_map:
                    sec["start_s"], sec["end_s"] = beat_map[bid]["start_s"], beat_map[bid]["end_s"]
                sec["id"], sec["text"] = sec.get("id") or sec.get("section_id"), sec.get("text") or sec.get("narration")
            s_bytes = json.dumps(s_json, indent=2).encode("utf-8")
            script_file.write_bytes(s_bytes)
            s_sha = hashlib.sha256(s_bytes).hexdigest()
            for f_path in (assets_file, ev_file):
                if f_path.is_file():
                    data = json.loads(f_path.read_text(encoding="utf-8"))
                    data["script_sha256"] = s_sha
                    f_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        if proof_map_file.is_file():
            p_json = json.loads(proof_map_file.read_text(encoding="utf-8"))
            for pb in p_json.get("beats", []):
                bid = pb.get("beat_id")
                if bid in beat_map:
                    pb["start_s"], pb["end_s"] = beat_map[bid]["start_s"], beat_map[bid]["end_s"]
            proof_map_file.write_text(json.dumps(p_json, indent=2), encoding="utf-8")

        plan_f.write_text(json.dumps(plan_json, indent=2), encoding="utf-8")
        self._rematerialize_after_reconciliation(align_dur, plan_json, script_file)

    def _rematerialize_after_reconciliation(self, align_dur: float, plan_json: dict, script_file: Path) -> None:
        from lib.fixed_niche.hyperframes_composer import materialize_hyperframes_project
        topic_comp = self._staged_topic or {"candidate_id": self.candidate_id}
        visual_style = os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg")
        flag_enabled = os.environ.get("ANIMATED_AGENT_DIAGRAM_V1_ENABLED", "0") not in ("0", "false", "False")
        if visual_style == "animated_agent_diagram_v1" and flag_enabled:
            from lib.visual_style.diagram_director import AnimatedDiagramDirector
            cl_file = self.project_dir / "artifacts" / "claim_ledger.json"
            claims = json.loads(cl_file.read_text(encoding="utf-8")).get("claims", []) if cl_file.is_file() else []
            director = AnimatedDiagramDirector(policy_sha256=self.policy.policy_sha256)
            diag_plan = director.plan_diagram_animation(
                project_id=self.candidate_id, topic=topic_comp, claims=claims, target_duration=align_dur,
                script_sha256=hashlib.sha256(script_file.read_bytes()).hexdigest(),
                source_claim_ledger_sha256=hashlib.sha256(json.dumps(claims).encode("utf-8")).hexdigest(),
                source_visual_plan_sha256=hashlib.sha256(json.dumps(plan_json).encode("utf-8")).hexdigest(),
            )
            director.write_sidecar(diag_plan, self.project_dir)

        materialize_hyperframes_project(project_dir=self.project_dir, topic=topic_comp, visual_plan=plan_json, duration=align_dur)

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

        prov = provider or os.environ.get("TTS_PROVIDER_EN", "edge")
        spd = self._resolve_tts_speed(prov, speed)
        vc = voice or self.orchestrator.resolve_default_voice(locale="en-US", provider=prov)

        res, actual_prov, vc, spd = self._invoke_initial_synthesis(text, out_audio, prov, vc, spd)
        if not res.get("success") or not out_audio.is_file():
            raise RuntimeError(f"Narration synthesis failed: {res.get('error', 'Unknown error')}")

        dur = probe_audio_duration(out_audio)
        if res.get("provider") and res.get("provider") != actual_prov:
            actual_prov = res.get("provider")
            vc = self.orchestrator.resolve_default_voice(locale="en-US", provider=actual_prov)
            spd = 1.0

        dur_range = self.policy.video_contract.get("shorts", {}).get("target_duration_seconds", [65, 75])
        policy_max = float(dur_range[1]) if len(dur_range) >= 2 else 75.0

        dur = self._calibrate_speed_and_tempo(text, out_audio, actual_prov, vc, spd, dur, policy_max)
        logger.info(f"Synthesized voice track: duration={dur:.2f}s")

        target_dur = self.get_target_duration()
        n_beats = 0
        plan_p = self.project_dir / "artifacts" / "news_visual_plan.json"
        if plan_p.is_file():
            try:
                n_beats = len(json.loads(plan_p.read_text(encoding="utf-8")).get("beats", []))
            except Exception:
                pass

        self._validate_narration_durations(dur, actual_prov, policy_max, n_beats)
        self._reconcile_artifacts(dur, target_dur, out_audio)
        return out_audio

    def _sample_and_validate_frames(self, output_mp4: Path, render_dur: float, frames_dir: Path) -> bool:
        """Sample key frames and validate visual quality/variance."""
        frames_dir.mkdir(parents=True, exist_ok=True)
        sample_points = [
            (0, "frame_00s_hook.png"),
            (3, "frame_03s_impact.png"),
            (int(render_dur / 2), "frame_mid_mechanism.png"),
            (int(render_dur - 2), "frame_end_payoff.png"),
        ]
        for sec, fname in sample_points:
            fpath = frames_dir / fname
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(sec), "-i", str(output_mp4), "-vframes", "1", str(fpath)]
            if subprocess.run(cmd, capture_output=True).returncode != 0:
                return False
            if not fpath.is_file():
                return False
            ok, _ = self.storyboard_director.validate_frame_sample(fpath)
            if not ok:
                return False
        return True

    def _record_approval_and_status(
        self,
        qa_pass: bool,
        output_mp4: Path,
        actual_dur: float,
        target_dur: float,
        video_sha: Optional[str],
        audio_sha: Optional[str],
        ledger_sha: Optional[str],
    ) -> str:
        """Sign approval record if QA passed and persist validation status."""
        app_status = "APPROVED_FOR_PRIVATE_CANARY" if qa_pass else "QA_FAILED"
        val_status_code = "VIDEO_READY_FOR_PRIVATE_REVIEW" if qa_pass else "QA_FAILED"
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if qa_pass:
            from lib.qa_signing import sign_approval_record
            audit_trail = {
                "status": app_status, "audio_sha256": audio_sha, "video_sha256": video_sha,
                "target_aspect": "9:16", "duration": actual_dur, "target_duration": target_dur,
                "policy_sha256": self.policy.policy_sha256, "strict_quality_pass": True,
            }
            app_record = sign_approval_record(
                project_id=self.candidate_id, media_sha256=video_sha, claim_ledger_sha256=ledger_sha,
                timestamp_iso=timestamp, reviewer="independent_qa_supervisor", format_type="short",
                audit_trail=audit_trail,
            )
            app_record.update(audit_trail)
        else:
            app_record = {
                "approved": False, "status": app_status, "claim_ledger_sha256": ledger_sha,
                "audio_sha256": audio_sha, "video_sha256": video_sha, "target_aspect": "9:16",
                "duration": actual_dur, "target_duration": target_dur,
                "policy_sha256": self.policy.policy_sha256, "timestamp": timestamp,
            }
        (self.project_dir / "approval.json").write_text(json.dumps(app_record, indent=2), encoding="utf-8")
        val_status = {
            "project_id": self.candidate_id, "status": "PASS" if qa_pass else "QA_FAILED",
            "review_status": val_status_code, "strict_quality_pass": qa_pass,
            "rendered_mp4": str(output_mp4), "duration": actual_dur, "target_duration": target_dur,
            "policy_sha256": self.policy.policy_sha256,
        }
        (self.project_dir / "validation_status.json").write_text(json.dumps(val_status, indent=2), encoding="utf-8")
        return val_status_code

    def _generate_thumbnail_if_approved(self) -> None:
        """Generate thumbnail when QA validation passes."""
        try:
            from lib.news_visual.thumbnail_orchestrator import ThumbnailOrchestrator
            topic_data = getattr(self, "_staged_topic", None) or {}
            tb_file = self.project_dir / "artifacts" / "topic_brief.json"
            if not topic_data and tb_file.is_file():
                topic_data = json.loads(tb_file.read_text(encoding="utf-8"))
            ThumbnailOrchestrator.generate_thumbnail(
                project_dir=self.project_dir,
                title=topic_data.get("title") or self.candidate_id,
                topic=topic_data.get("summary", ""),
                format_type="short",
                allow_fallback=True,
            )
        except Exception as e:
            logger.warning(f"Failed to generate thumbnail for {self.candidate_id}: {e}")

    def render(self, burn_captions: bool = False, renderer: str = "auto") -> Dict[str, Any]:
        """Render final 9:16 video and perform strict signed QA gating."""
        target_dur = self.get_target_duration()
        output_mp4 = self.project_dir / "renders" / "final_short_en_US_9x16.mp4"
        audio_path = self.project_dir / "assets" / "narration.mp3"
        audio_dur = probe_audio_duration(audio_path) if audio_path.is_file() else -1.0
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

        frames_dir = self.project_dir / "renders" / "frame_samples"
        frames_valid = self._sample_and_validate_frames(output_mp4, render_dur, frames_dir)

        video_ok = output_mp4.is_file() and output_mp4.stat().st_size > 0 and probe_out.returncode == 0
        probe_dur_str = probe_json.get("format", {}).get("duration")
        probe_dur = float(probe_dur_str) if probe_dur_str else 0.0

        claim_ledger_path = self.project_dir / "artifacts" / "claim_ledger.json"
        ledger_valid = claim_ledger_path.is_file() and claim_ledger_path.stat().st_size > 0
        ledger_sha = FixedNicheResearcher.compute_file_sha(claim_ledger_path) if ledger_valid else None
        audio_path = self.project_dir / "assets" / "narration.mp3"
        audio_sha = FixedNicheResearcher.compute_file_sha(audio_path) if audio_path.is_file() else None
        video_sha = FixedNicheResearcher.compute_file_sha(output_mp4) if video_ok else None

        from lib.fixed_niche.qa import FixedNicheQAValidator
        qa_validator = FixedNicheQAValidator(self.policy)
        qa_report = qa_validator.audit_fixed_niche_deliverable(
            project_dir=self.project_dir,
            expected_duration=target_dur,
        )

        qa_pass = bool(
            video_ok and probe_dur > 0 and frames_valid and ledger_valid
            and audio_sha is not None and video_sha is not None and qa_report.get("strict_quality_pass")
        )
        actual_dur = probe_dur if probe_dur > 0 else render_dur
        val_status_code = self._record_approval_and_status(
            qa_pass, output_mp4, actual_dur, target_dur, video_sha, audio_sha, ledger_sha
        )
        if qa_pass:
            self._generate_thumbnail_if_approved()

        return {
            "status": val_status_code, "rendered_mp4": str(output_mp4), "duration": actual_dur,
            "target_duration": target_dur, "frames_dir": str(frames_dir),
            "approval_path": str(self.project_dir / "approval.json"),
        }


def _configure_cli_environment(args: argparse.Namespace) -> None:
    """Set global environment variables based on CLI flags."""
    os.environ["AI_VISUAL_ENABLED"] = "1" if args.enable_ai_visuals else "0"
    os.environ["OPENMONTAGE_VISUAL_STYLE"] = args.visual_style
    if args.visual_style == "animated_agent_diagram_v1" and args.enable_diagram_animation:
        os.environ["ANIMATED_AGENT_DIAGRAM_V1_ENABLED"] = "1"
    else:
        os.environ["ANIMATED_AGENT_DIAGRAM_V1_ENABLED"] = "0"


def _validate_safe_path(path: Path | str) -> Path:
    """Validate path against traversal attacks (CWE-22 / CWE-73)."""
    import tempfile
    p = Path(path).expanduser().resolve()
    allowed = (ROOT.resolve(), Path.home().resolve(), Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve())
    if not any(p.is_relative_to(root) for root in allowed if root != Path(root.anchor)):
        raise ValueError(f"Path traversal detected or path outside allowed root: {path}")
    if not p.is_file():
        raise FileNotFoundError(f"Candidate file does not exist: {path}")
    if p.is_relative_to(Path(tempfile.gettempdir()).resolve()) and hasattr(os, "getuid") and p.stat().st_uid != os.getuid():
        raise PermissionError(f"Candidate file in temp directory must be owned by current user: {path}")
    return p


def _load_yaml_candidates(file_path: Path) -> List[Dict[str, Any]]:
    """Safely load candidate dictionaries from a YAML file."""
    try:
        import yaml
        raw_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            return raw_data.get("positive_cases", [])
        return raw_data if isinstance(raw_data, list) else []
    except Exception as e:
        logger.warning("Failed to load candidates from %s: %s", file_path, e)
        return []


def _load_cli_candidates_pool(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Load candidates from specified file, test fixtures, or production source adapter."""
    if args.candidates_file:
        candidates = _load_yaml_candidates(_validate_safe_path(args.candidates_file))
        if not candidates:
            raise ValueError(f"No candidates could be loaded from specified --candidates-file: {args.candidates_file}")
        return candidates
    if args.use_test_fixtures:
        candidates = _load_yaml_candidates(_validate_safe_path(ROOT / "tests/fixtures/fixed_niche_cases.yaml"))
        if not candidates:
            raise ValueError("No candidates could be loaded from test fixtures")
        return candidates
    return FixedNicheSourceAdapter().discover_production_candidates()


def _apply_topic_overrides(topic: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """Apply explicit CLI argument overrides to topic metadata."""
    res = dict(topic)
    res.update({k: getattr(args, k) for k in ("title", "topic_family", "canonical_url") if getattr(args, k, None)})
    return res


def _auto_select_topic(
    candidates_pool: List[Dict[str, Any]], gate: FixedNicheScopeGate, args: argparse.Namespace
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Auto-select the highest ranked eligible candidate from pool."""
    eligible = [c for c in candidates_pool if gate.evaluate_candidate(c).is_eligible]
    if not eligible:
        return None, None
    from lib.fixed_niche.ranker import FixedNicheTopicScorer
    ranked = FixedNicheTopicScorer().rank_candidates([(c, gate.evaluate_candidate(c)) for c in eligible])
    top_cand = ranked[0] if ranked else eligible[0]
    cid = top_cand.get("id") or top_cand.get("candidate_id") or "cand_selected"
    topic = _apply_topic_overrides(top_cand, args)
    topic["candidate_id"] = cid
    return cid, topic


def _resolve_cli_topic_and_candidate(
    args: argparse.Namespace, candidates_pool: List[Dict[str, Any]], gate: FixedNicheScopeGate
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve target candidate ID and topic dictionary according to auto-select/explicit args."""
    cid = args.candidate_id
    if cid:
        matched = next((c for c in candidates_pool if c.get("candidate_id") == cid or c.get("id") == cid), None)
        if matched:
            t = _apply_topic_overrides(matched, args)
            t["candidate_id"] = cid
            return cid, t
    if args.auto_select or not cid:
        return _auto_select_topic(candidates_pool, gate, args)
    fallback = _apply_topic_overrides({
        "candidate_id": cid, "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory", "canonical_url": "https://docs.anthropic.com/claude/context-window",
    }, args)
    fallback["candidate_id"] = cid
    return cid, fallback


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fixed Niche Video Production CLI")
    parser.add_argument("--candidate-id", default=None, help="Candidate ID to produce")
    parser.add_argument("--auto-select", action="store_true", default=False, help="Auto-discover in-scope candidate")
    parser.add_argument("--candidates-file", default=None, help="Path to YAML/JSON candidates pool file")
    parser.add_argument("--use-test-fixtures", action="store_true", default=False, help="Allow loading test fixtures")
    parser.add_argument("--renderer", choices=["auto", "hyperframes", "ffmpeg"], default="auto", help="Renderer")
    parser.add_argument("--project-dir", help="Custom project output directory")
    parser.add_argument("--format", default="short", choices=["short", "shorts"], help="Video format")
    parser.add_argument("--provider", default=None, help="TTS provider")
    parser.add_argument("--voice", default=None, help="TTS voice override")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--dry-run", action="store_true", help="Stage project without media rendering")
    parser.add_argument("--burn-captions", action="store_true", default=False, help="Burn subtitles into video")
    parser.add_argument("--title", default=None)
    parser.add_argument("--topic-family", default=None)
    parser.add_argument("--canonical-url", default=None)
    parser.add_argument("--enable-ai-visuals", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--visual-style", default=os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg"), choices=["progressive_svg", "animated_agent_diagram_v1", "legacy"])
    parser.add_argument("--enable-diagram-animation", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-latest-news", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-age-days", type=int, default=7)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_cli_parser().parse_args(argv)

    _configure_cli_environment(args)

    policy = load_locked_policy()
    gate = FixedNicheScopeGate(policy)

    candidates_pool = _load_cli_candidates_pool(args)
    candidate_id, topic = _resolve_cli_topic_and_candidate(args, candidates_pool, gate)

    if not candidate_id or not topic:
        print(json.dumps({"status": "NO_ELIGIBLE_TOPIC", "message": "Zero eligible topics found in candidate pool; no project staged."}, indent=2))
        return 0

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
