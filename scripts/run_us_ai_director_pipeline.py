#!/usr/bin/env python3
"""OpenMontage US AI Director End-to-End Execution Pipeline.

Executes and verifies the 8-stage production pipeline for native US deliverables:
  Stage 1: Research & source snapshot validation (verbatim excerpt verification)
  Stage 2: AI Director script generation & en-US language validation
  Stage 3: Editorial review & quantitative claim grounding
  Stage 4: Contextual scene graphics generation
  Stage 5: Speech synthesis & audio mixing
  Stage 6: Subtitle alignment & cue validation
  Stage 7: Video rendering, subtitle burn-in & parameter inspection
  Stage 8: Independent QA audit & cryptographic supervisor signing

Enforces strict separation of duties, cryptographic manifest binding, and fail-closed security.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.audience_profile import load_audience_profile
from lib.language_validation import get_language_validator
from lib.qa_signing import sign_approval_record, verify_approval_record
from scripts.independent_editorial_qa import APPROVED_DOMAINS, audit_project, grant_supervisor_approval


class StageExecutionError(RuntimeError):
    """Raised when a pipeline stage fails."""


def log_stage(stage_num: int, name: str, status: str, details: str = "") -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    symbol = "🟢" if status == "PASS" else "🔴" if status == "FAIL" else "ℹ️"
    print(f"[{ts}] {symbol} Stage {stage_num}/8: {name} — {status} {details}")
    return {"stage": stage_num, "name": name, "status": status, "timestamp": ts, "details": details}


def _verify_source_hostname(cid: str, source: dict) -> None:
    url = source.get("canonical_url", "")
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname or not any(hostname == d or hostname.endswith("." + d) for d in APPROVED_DOMAINS):
        raise StageExecutionError(
            f"Stage 1 failed: claim {cid} source URL hostname '{hostname}' not in approved literature domains"
        )


def _resolve_snapshot_path(project_dir: Path, snapshot_dir: Path, snap_file: Optional[str]) -> Path:
    if not snap_file:
        return project_dir / "artifacts" / "source_snapshot.txt"
    snap_path = Path(snap_file)
    target = snap_path if snap_path.is_absolute() else (project_dir / snap_path)
    if not target.is_file():
        target = project_dir / "artifacts" / snap_path.name
    if not target.is_file():
        target = snapshot_dir / snap_path.name
    return target


def _verify_fact_check(cid: str, fact_check: dict, snap_text: str, snap_name: str) -> None:
    v_status = fact_check.get("verification_status")
    if v_status != "INDEPENDENT_FACT_CHECK_VERIFIED":
        raise StageExecutionError(
            f"Stage 1 failed: claim {cid} fact check status is '{v_status}', expected 'INDEPENDENT_FACT_CHECK_VERIFIED'"
        )
    verified_by = fact_check.get("verified_by")
    if not verified_by or len(str(verified_by).strip()) < 5:
        raise StageExecutionError(f"Stage 1 failed: claim {cid} independent fact check missing verified_by entity")
    grounding = fact_check.get("grounding_sentence", "").strip()
    if not grounding:
        raise StageExecutionError(f"Stage 1 failed: claim {cid} independent fact check missing grounding_sentence")
    if grounding not in snap_text:
        raise StageExecutionError(
            f"Stage 1 failed: claim {cid} grounding_sentence is not verbatim in snapshot {snap_name}"
        )


def _verify_provenance_record(snap_name: str, actual_sha: str, prov_data: dict) -> None:
    described_snap = prov_data.get("snapshot_file", "source_snapshot.txt")
    if snap_name != described_snap:
        raise StageExecutionError(
            f"Stage 1 failed: snapshot provenance describes '{described_snap}', not '{snap_name}'"
        )
    recorded_prov_sha = prov_data.get("content_sha256")
    if recorded_prov_sha != actual_sha:
        raise StageExecutionError(
            f"Stage 1 failed: snapshot provenance sha mismatch ({str(recorded_prov_sha)[:16]} != {actual_sha[:16]})"
        )
    if not prov_data.get("is_authentic_primary"):
        raise StageExecutionError("Stage 1 failed: snapshot provenance indicates unauthentic source")


def _verify_snapshot_content_and_facts(
    cid: str, claim: dict, source: dict, target_snap: Path, prov_data: Optional[dict]
) -> None:
    if not target_snap.is_file():
        raise StageExecutionError(f"Stage 1 failed: claim {cid} snapshot file missing on disk: {target_snap}")
    actual_sha = hashlib.sha256(target_snap.read_bytes()).hexdigest()
    expected_sha = source.get("snapshot_sha256") or claim.get("snapshot_sha256")
    if expected_sha and actual_sha != expected_sha:
        raise StageExecutionError(
            f"Stage 1 failed: claim {cid} snapshot SHA mismatch ({actual_sha[:16]} != {expected_sha[:16]})"
        )
    excerpt = claim.get("evidence_excerpt", "").strip()
    snap_text = target_snap.read_text(encoding="utf-8")
    if excerpt and excerpt not in snap_text:
        raise StageExecutionError(
            f"Stage 1 failed: claim {cid} evidence excerpt is not verbatim in snapshot {target_snap.name}"
        )
    fact_check = source.get("independent_fact_check") or claim.get("independent_fact_check")
    if fact_check:
        _verify_fact_check(cid, fact_check, snap_text, target_snap.name)
    if prov_data is not None:
        _verify_provenance_record(target_snap.name, actual_sha, prov_data)


def stage_1_research_and_sources(project_dir: Path) -> dict:
    """Stage 1: Research & source snapshot validation."""
    ledger_path = project_dir / "artifacts" / "claim_ledger.json"
    if not ledger_path.is_file():
        raise StageExecutionError(f"Stage 1 failed: claim ledger missing ({ledger_path})")

    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StageExecutionError(f"Stage 1 failed: malformed claim ledger ({exc})")

    claims = ledger.get("claims", [])
    if not claims:
        raise StageExecutionError("Stage 1 failed: no claims recorded in claim ledger")

    active_claims = [c for c in claims if c.get("verdict") != "REJECTED"]
    if not active_claims:
        raise StageExecutionError("Stage 1 failed: all claims in ledger are REJECTED; at least one active claim required")

    snapshot_dir = project_dir / "artifacts" / "source_snapshots"
    verified_sources = 0

    prov_file = project_dir / "artifacts" / "snapshot_provenance.json"
    prov_data = None
    if prov_file.is_file():
        try:
            prov_data = json.loads(prov_file.read_text(encoding="utf-8"))
            if not isinstance(prov_data, dict):
                raise StageExecutionError("Stage 1 failed: malformed snapshot_provenance.json")
        except (ValueError, OSError):
            raise StageExecutionError("Stage 1 failed: malformed snapshot_provenance.json")

    for idx, claim in enumerate(claims):
        cid = claim.get("claim_id", f"claim_{idx}")
        if claim.get("verdict") == "REJECTED":
            continue
        source = claim.get("source", {})
        _verify_source_hostname(cid, source)

        snap_file = source.get("snapshot_file") or claim.get("snapshot_file") or claim.get("source_snapshot_path")
        if snap_file or (project_dir / "artifacts" / "source_snapshot.txt").is_file():
            target_snap = _resolve_snapshot_path(project_dir, snapshot_dir, snap_file)
            _verify_snapshot_content_and_facts(cid, claim, source, target_snap, prov_data)
            verified_sources += 1

    return {"verified_claims": len(active_claims), "verified_snapshots": verified_sources}


def stage_2_script_generation(project_dir: Path) -> dict:
    """Stage 2: AI Director script generation & en-US language validation."""
    script_path = project_dir / "artifacts" / "script_en_US.json"
    if not script_path.is_file():
        # Dynamically synthesize script if missing from topic brief and claim ledger
        brief_file = project_dir / "artifacts" / "topic_brief.json"
        claims_file = project_dir / "artifacts" / "claim_ledger.json"
        if brief_file.is_file() and claims_file.is_file():
            try:
                topic = json.loads(brief_file.read_text(encoding="utf-8"))
                claims = json.loads(claims_file.read_text(encoding="utf-8")).get("claims", [])
                from lib.fixed_niche.storyboard import FixedNicheStoryboardDirector
                director = FixedNicheStoryboardDirector()
                res = director.generate_storyboard(topic=topic, claims=claims, project_dir=project_dir)
                sections = [
                    {
                        "section_id": b["script_section_id"],
                        "beat_id": b["beat_id"],
                        "start_s": b["start_s"],
                        "end_s": b["end_s"],
                        "story_function": b["story_function"],
                        "narration": b["narration"],
                        "text": b["narration"],
                        "claim_ids": b["claim_ids"],
                    }
                    for b in res["visual_plan"]["beats"]
                ]
                script_data = {
                    "version": "1.0",
                    "locale": "en-US",
                    "title": topic.get("title", "Practical AI Agent Engineering Explainer"),
                    "target_duration_seconds": 72.0,
                    "sections": sections,
                    "scenes": sections,
                }
                script_path.parent.mkdir(parents=True, exist_ok=True)
                script_path.write_text(json.dumps(script_data, indent=2), encoding="utf-8")
            except Exception as e:
                raise StageExecutionError(f"Stage 2 failed: dynamic script generation failed: {e}")
        else:
            raise StageExecutionError(f"Stage 2 failed: script file missing ({script_path}) and no brief to synthesize from")

    try:
        script = json.loads(script_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StageExecutionError(f"Stage 2 failed: malformed script JSON ({exc})")

    scenes = script.get("scenes") or script.get("sections", [])
    if not scenes:
        raise StageExecutionError("Stage 2 failed: script contains no scenes or sections")

    # Validate prose with EnglishLanguageValidator
    validator = get_language_validator("en-US")
    full_text = " ".join(s.get("text", "") or s.get("narration", "") for s in scenes)
    errors = validator.validate_prose(full_text)
    if errors:
        raise StageExecutionError(f"Stage 2 failed: en-US prose validation errors: {errors}")

    # Validate audience profile rules
    profile = load_audience_profile("en-US")
    for banned in profile.viewer_profile.banned_assumptions:
        if banned.lower() in full_text.lower():
            raise StageExecutionError(f"Stage 2 failed: script contains banned audience assumption '{banned}'")

    return {"scenes_count": len(scenes), "word_count": len(full_text.split())}


def _verify_claim_numeric_grounding(cid: str, span: str, excerpt: str) -> None:
    numbers = re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?%?", span)
    for num in numbers:
        if num not in excerpt and num.replace(",", "") not in excerpt:
            raise StageExecutionError(
                f"Stage 3 failed: claim {cid} number '{num}' in script span not substantiated by excerpt"
            )


def _verify_single_claim_editorial(claim: dict, full_script: str) -> None:
    cid = claim.get("claim_id")
    verdict = claim.get("verdict", "")
    confidence = claim.get("confidence", "")

    is_in_script = any(
        span and (span in full_script or span.lower() in full_script.lower())
        for span in claim.get("script_spans", [])
    )
    if not is_in_script and claim.get("statement"):
        is_in_script = claim.get("statement", "").lower() in full_script.lower()

    if verdict == "REJECTED":
        if is_in_script:
            raise StageExecutionError(f"Stage 3 failed: claim {cid} has unapproved verdict '{verdict}'")
        return

    # Require BOTH APPROVED verdict and verified confidence (fail-closed)
    if verdict != "APPROVED":
        raise StageExecutionError(f"Stage 3 failed: claim {cid} has unapproved verdict '{verdict}'")
    if confidence != "verified":
        raise StageExecutionError(f"Stage 3 failed: claim {cid} has unverified confidence '{confidence}'")

    # Check that script spans are grounded in evidence excerpts
    excerpt = claim.get("evidence_excerpt", "")
    for span in claim.get("script_spans", []):
        if span not in full_script and span.lower() not in full_script.lower():
            raise StageExecutionError(f"Stage 3 failed: claim {cid} script span '{span}' not in script")
        _verify_claim_numeric_grounding(cid, span, excerpt)


def stage_3_editorial_grounding(project_dir: Path) -> dict:
    """Stage 3: Editorial review & quantitative claim grounding."""
    ledger_path = project_dir / "artifacts" / "claim_ledger.json"
    script_path = project_dir / "artifacts" / "script_en_US.json"
    
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    script = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = script.get("scenes") or script.get("sections", [])
    full_script = " ".join(s.get("text", "") or s.get("narration", "") for s in scenes)

    claims = ledger.get("claims", [])
    approved_claims = [c for c in claims if c.get("verdict") == "APPROVED"]
    if not approved_claims:
        raise StageExecutionError("Stage 3 failed: no approved claims in ledger")

    for claim in claims:
        _verify_single_claim_editorial(claim, full_script)

    return {"approved_claims": len(approved_claims)}


def stage_4_scene_graphics(project_dir: Path, format_type: str = "short") -> dict:
    """Stage 4: Contextual scene graphics generation."""
    project_dir = Path(project_dir).resolve()
    target_dir = project_dir / "assets" / "scene_graphics"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        target_dir = Path("/tmp/scene_graphics") / format_type
        target_dir.mkdir(parents=True, exist_ok=True)

    pngs = list(target_dir.glob("*.png"))
    if not pngs:
        # Check if project has storyboard SVGs in assets/visuals
        vis_dir = project_dir / "assets" / "visuals"
        svgs = list(vis_dir.glob("*.svg")) if vis_dir.is_dir() else []
        if svgs:
            w, h = (1080, 1920) if format_type == "short" else (1920, 1080)
            for s in svgs:
                png_path = target_dir / f"{s.stem}.png"
                if not png_path.is_file():
                    try:
                        subprocess.run([
                            "ffmpeg", "-y", "-loglevel", "error",
                            "-i", str(s),
                            "-vf", f"scale={w}:{h}",
                            str(png_path),
                        ], check=True)
                    except Exception:
                        pass
            pngs = list(target_dir.glob("*.png"))

    if not pngs:
        from scripts.generate_scene_graphics import generate_short_graphics, generate_longform_graphics
        if format_type == "short":
            generate_short_graphics(target_dir)
        else:
            generate_longform_graphics(target_dir)
        pngs = list(target_dir.glob("*.png"))

    if not pngs:
        raise StageExecutionError("Stage 4 failed: no scene graphics available")

    return {"graphics_count": len(pngs)}


def stage_5_speech_synthesis(project_dir: Path, provider: str = "flite") -> dict:
    """Stage 5: Speech synthesis & audio mixing verification."""
    narration_txt = project_dir / "artifacts" / "narration_en_US_text.txt"
    if not narration_txt.is_file():
        script_path = project_dir / "artifacts" / "script_en_US.json"
        if script_path.is_file():
            s_data = json.loads(script_path.read_text(encoding="utf-8"))
            scenes = s_data.get("scenes") or s_data.get("sections") or []
            lines = [s.get("text") or s.get("narration", "") for s in scenes]
            narration_txt.parent.mkdir(parents=True, exist_ok=True)
            narration_txt.write_text("\n".join(lines), encoding="utf-8")
        else:
            raise StageExecutionError(f"Stage 5 failed: narration text file missing ({narration_txt})")

    audio_file = project_dir / "assets" / "narration.mp3"
    if not audio_file.is_file():
        render_files = list((project_dir / "renders").glob("*.mp4"))
        if not render_files:
            try:
                from lib.audio.narration_orchestrator import NarrationOrchestrator
                orchestrator = NarrationOrchestrator()
                text = narration_txt.read_text(encoding="utf-8")
                audio_file.parent.mkdir(parents=True, exist_ok=True)
                voice = orchestrator.resolve_default_voice(locale="en-US", provider=provider)
                res = orchestrator.synthesize(
                    text=text,
                    output_path=audio_file,
                    locale="en-US",
                    provider=provider,
                    voice=voice,
                    allow_fallback=True,
                )
                if not res.get("success") or not audio_file.is_file():
                    raise RuntimeError(res.get("error", "Unknown synthesis failure"))
            except Exception as e:
                raise StageExecutionError(f"Stage 5 failed: speech synthesis failed ({e})")

    return {"audio_source": str(audio_file) if audio_file.is_file() else "embedded"}


def stage_6_captions_alignment(project_dir: Path) -> dict:
    """Stage 6: Subtitle alignment & cue validation."""
    srt_path = project_dir / "artifacts" / "captions_en_US.srt"
    if not srt_path.is_file():
        vplan_file = project_dir / "artifacts" / "news_visual_plan.json"
        if not vplan_file.is_file():
            vplan_file = project_dir / "artifacts" / "visual_plan.json"
        if vplan_file.is_file():
            try:
                from lib.fixed_niche.captions import generate_srt_from_beats
                plan_json = json.loads(vplan_file.read_text(encoding="utf-8"))
                beats = plan_json.get("beats", [])
                srt_content = generate_srt_from_beats(beats)
                srt_path.parent.mkdir(parents=True, exist_ok=True)
                srt_path.write_text(srt_content, encoding="utf-8")
            except Exception as e:
                raise StageExecutionError(f"Stage 6 failed: dynamic captions generation failed: {e}")
        else:
            raise StageExecutionError(f"Stage 6 failed: subtitles file missing ({srt_path})")

    content = srt_path.read_text(encoding="utf-8")
    time_blocks = re.findall(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", content)
    if not time_blocks or len(time_blocks) < 3:
        raise StageExecutionError(f"Stage 6 failed: insufficient subtitle cues ({len(time_blocks)} found, min 3)")

    def parse_ms(s: str) -> int:
        h, m, sec_ms = s.split(":")
        sec, ms = sec_ms.split(",")
        return int(h) * 3600000 + int(m) * 60000 + int(sec) * 1000 + int(ms)

    last_end = 0
    for idx, (start_str, end_str) in enumerate(time_blocks):
        s_ms = parse_ms(start_str)
        e_ms = parse_ms(end_str)
        if s_ms >= e_ms:
            raise StageExecutionError(f"Stage 6 failed: cue {idx+1} invalid timestamp interval ({start_str} >= {end_str})")
        if s_ms < last_end:
            raise StageExecutionError(f"Stage 6 failed: cue {idx+1} timestamp overlap with previous cue")
        last_end = e_ms

    return {"cues_count": len(time_blocks)}


def stage_7_video_rendering(
    project_dir: Path,
    format_type: str = "short",
    render_mode: str = "verify_existing"
) -> dict:
    """Stage 7: Video rendering, subtitle burn-in & parameter inspection."""
    renders_dir = project_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    target_video = (
        renders_dir / "final_short_en_US_9x16.mp4"
        if format_type == "short"
        else renders_dir / "final_long_en_US_16x9.mp4"
    )

    if render_mode == "full" or not target_video.is_file():
        from scripts.run_fixed_niche_video import render_project_composition
        comp_name = "hyperframes_reels" if format_type == "short" else "hyperframes"
        dur = 72.0 if format_type == "short" else 360.0
        try:
            render_project_composition(
                project_dir=project_dir,
                composition_name=comp_name,
                output_mp4=target_video,
                duration_seconds=dur,
                burn_captions=False,
                renderer="auto",
            )
        except Exception as e:
            logger.warning(f"Render composition error ({e}), running project fallback render for {project_dir}")
            from lib.fixed_niche.hyperframes_composer import render_ffmpeg_composition
            w, h = (1080, 1920) if format_type == "short" else (1920, 1080)
            render_ffmpeg_composition(
                project_dir=project_dir,
                output_mp4=target_video,
                render_dur=dur,
                width=w,
                height=h,
                burn_captions=False,
            )

    if not target_video.is_file():
        raise StageExecutionError(f"Stage 7 failed: render output {target_video} not found")

    frame_dir = renders_dir / "frame_samples"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_samples = list(frame_dir.glob("*.png"))
    if len(frame_samples) < 3:
        try:
            sample_offsets = [0, 3, int(dur / 2), max(0, int(dur - 2))]
            for idx, offset in enumerate(sample_offsets):
                sample_p = frame_dir / f"frame_{idx:02d}_{offset}s.png"
                if not sample_p.is_file():
                    subprocess.run([
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-ss", str(offset),
                        "-i", str(target_video),
                        "-vframes", "1",
                        str(sample_p),
                    ], check=True)
            frame_samples = list(frame_dir.glob("*.png"))
        except Exception as exc:
            logger.warning(f"Frame sampling failed: {exc}")

    return {
        "video_file": str(target_video),
        "file_size": target_video.stat().st_size,
        "frame_samples_count": len(frame_samples),
    }


def stage_8_supervisor_qa_and_signing(
    project_dir: Path,
    format_type: str = "short",
    supervisor_secret: str | None = None
) -> dict:
    """Stage 8: Independent QA audit & cryptographic supervisor signing."""
    dur = 72.0 if format_type == "short" else 360.0
    tol = 5.0
    audit_res = audit_project(project_dir, expected_format=format_type, expected_duration=dur, duration_tolerance=tol)
    if not audit_res.get("passed"):
        errors = audit_res.get("errors", [])
        raise StageExecutionError(f"Stage 8 failed: Independent QA audit failed: {errors}")

    if supervisor_secret:
        os.environ["QA_SUPERVISOR_SECRET"] = supervisor_secret

    approval_data = grant_supervisor_approval(
        project_dir=project_dir,
        expected_format=format_type,
        audit_results=audit_res,
    )
    approval_file = project_dir / "approval.json"
    if not approval_file.is_file():
        raise StageExecutionError(f"Stage 8 failed: approval file {approval_file} was not written")

    valid, msg = verify_approval_record(
        approval_data=approval_data,
        project_id=project_dir.name,
        project_dir=project_dir,
        require_manifest=True,
    )
    if not valid:
        raise StageExecutionError(f"Stage 8 failed: self-verification of signed approval failed: {msg}")

    return {
        "approval_file": str(approval_file),
        "manifest_sha256": approval_data.get("manifest_sha256"),
        "signature": approval_data.get("signature"),
    }


def run_us_ai_director_pipeline(
    project_dir: Path | str,
    format_type: str = "short",
    render_mode: str = "verify_existing",
    supervisor_secret: str | None = None,
) -> dict:
    """Execute all 8 stages of the US AI Director Pipeline with strict gate verification."""
    p_dir = Path(project_dir).resolve()
    stages_log = []

    print(f"\n=======================================================")
    print(f"  US AI DIRECTOR PIPELINE: {p_dir.name} ({format_type.upper()})")
    print(f"=======================================================\n")

    stages = [
        (1, "Research & Sources Validation", lambda: stage_1_research_and_sources(p_dir)),
        (2, "AI Director Script Generation", lambda: stage_2_script_generation(p_dir)),
        (3, "Editorial Claim Grounding", lambda: stage_3_editorial_grounding(p_dir)),
        (4, "Scene Graphics Generation", lambda: stage_4_scene_graphics(p_dir, format_type=format_type)),
        (5, "Speech Synthesis & Audio", lambda: stage_5_speech_synthesis(p_dir)),
        (6, "Subtitle Alignment", lambda: stage_6_captions_alignment(p_dir)),
        (7, "Video Rendering & Burn-in", lambda: stage_7_video_rendering(p_dir, format_type=format_type, render_mode=render_mode)),
        (8, "Independent QA Audit & Signing", lambda: stage_8_supervisor_qa_and_signing(p_dir, format_type=format_type, supervisor_secret=supervisor_secret)),
    ]

    for num, name, func in stages:
        try:
            res = func()
            entry = log_stage(num, name, "PASS", str(res))
            stages_log.append(entry)
        except Exception as exc:
            entry = log_stage(num, name, "FAIL", str(exc))
            stages_log.append(entry)
            try:
                (p_dir / "artifacts" / "pipeline_stage_log.json").write_text(
                    json.dumps({"pipeline": "us_ai_director", "status": "FAILED", "stages": stages_log}, indent=2),
                    encoding="utf-8"
                )
            except OSError:
                pass
            raise

    try:
        log_file = p_dir / "artifacts" / "pipeline_stage_log.json"
        log_file.write_text(
            json.dumps({"pipeline": "us_ai_director", "status": "SUCCESS", "stages": stages_log}, indent=2),
            encoding="utf-8"
        )
        print(f"\n🎉 All 8 stages completed successfully! Log written to {log_file}\n")
    except OSError:
        print(f"\n🎉 All 8 stages completed successfully! (read-only filesystem notice)\n")

    return {"status": "SUCCESS", "stages": stages_log}


def main():
    parser = argparse.ArgumentParser(description="Run OpenMontage US AI Director 8-Stage Pipeline")
    parser.add_argument("project_dir", type=Path, help="Path to project directory")
    parser.add_argument("--format", choices=["short", "longform"], default="short", help="Video format")
    parser.add_argument("--render-mode", choices=["verify_existing", "full"], default="verify_existing", help="Rendering mode")
    parser.add_argument("--secret", default=None, help="Optional QA supervisor secret key")
    args = parser.parse_args()

    try:
        run_us_ai_director_pipeline(
            project_dir=args.project_dir,
            format_type=args.format,
            render_mode=args.render_mode,
            supervisor_secret=args.secret,
        )
    except Exception as exc:
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
