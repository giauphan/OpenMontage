"""Quality and release preflight validation for OpenMontage publishing.

Enforces:
1. Strict video, audio, and metadata quality validation.
2. Stage checkpoints & prerequisites from selected pipeline manifest.
3. Required stage artifacts from pipeline manifest.
4. Explicit human approval bound to exact media SHA-256, target account, copy, and release time.
5. Block publication on asset or copy changes until re-validated and re-approved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_render_quality import PORTRAIT_DIMENSIONS, resolve_narration, validate_video
from tools.narration_text import validate_vietnamese_narration
from tools.publishers.platform_routes import youtube_shorts_title
from tools.publish_store import file_sha256


def _facade_symbol(name: str, fallback: Any) -> Any:
    mod = sys.modules.get("scripts.publish_manual_video")
    return getattr(mod, name, fallback) if mod is not None else fallback


def safe_resolve_publish_path(raw: str | Path, base_dir: Path | None = None) -> Path:
    """Resolve and sanitize path against traversal attacks (CWE-22 / CWE-73)."""
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (base_dir or ROOT) / p
    resolved = p.resolve()
    allowed_roots = (
        ROOT.resolve(),
        Path.cwd().resolve(),
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )
    if not any(resolved.is_relative_to(r) for r in allowed_roots if r != Path(r.anchor)):
        raise ValueError(f"Path traversal detected or path outside allowed root: {raw}")
    return resolved


def load_metadata(project_dir: Path) -> dict:
    resolve_fn = _facade_symbol("safe_resolve_publish_path", safe_resolve_publish_path)
    project_dir = resolve_fn(project_dir, ROOT)
    meta_path = project_dir / "publish_metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"publish_metadata.json not found in {project_dir}")
    with meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_video_path(raw: str, project_dir: Path, root: Path) -> Path:
    """Resolve a metadata video path safely.

    - Absolute paths are validated against allowed root directories.
    - Repo-prefixed paths (``projects/...``) resolve against the repo root.
    - Anything else resolves against the project directory.
    """
    p = Path(raw)
    base = root if (p.parts and p.parts[0] == "projects") else project_dir
    resolve_fn = _facade_symbol("safe_resolve_publish_path", safe_resolve_publish_path)
    return resolve_fn(p, base)


def validate_publish_asset(
    video_path: Path,
    project_dir: Path,
    platform: str,
    strict: bool = False,
) -> None:
    resolve_fn = _facade_symbol("safe_resolve_publish_path", safe_resolve_publish_path)
    project_dir = resolve_fn(project_dir, ROOT)
    video_path = resolve_fn(video_path, project_dir)
    rehearsal_marker = project_dir / "OFFLINE_REHEARSAL_TEST_ONLY.json"
    if rehearsal_marker.exists() or rehearsal_marker.is_symlink():
        raise ValueError(
            f"Release blocked: offline rehearsal test-only marker present in {project_dir.name}"
        )
    ffprobe = shutil.which("ffprobe") or ""
    ffmpeg = shutil.which("ffmpeg") or ""
    if not ffprobe:
        candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
        ffprobe = str(candidates[0]) if candidates else ""
    if not ffmpeg:
        candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
        ffmpeg = str(candidates[0]) if candidates else ""
    if not ffprobe or not ffmpeg:
        raise ValueError("ffprobe and ffmpeg are required for strict publish asset validation")

    meta = {}
    meta_path = project_dir / "publish_metadata.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    fmt = meta.get("format", "short")
    is_longform = fmt in ("longform", "long", "16:9", "16x9", "full")

    narration_fn = _facade_symbol("resolve_narration", resolve_narration)
    narration = narration_fn(
        project_dir,
        "narration.mp3"
        if is_longform
        else ("narration_reels.mp3" if platform in ("youtube", "instagram") else "narration.mp3"),
        "narration.mp3",
    )
    from lib.artifact_paths import resolve_project_locale, is_english_locale, resolve_narration_text_path
    from lib.language_validation import get_language_validator

    locale = resolve_project_locale(project_dir)
    narration_text = resolve_narration_text_path(project_dir, locale=locale)
    if not narration_text.is_file():
        raise ValueError(f"missing narration text: {narration_text}")
    if is_english_locale(locale):
        validator = get_language_validator(locale)
        language_errors = validator.validate_prose(narration_text.read_text(encoding="utf-8"))
    else:
        vn_fn = _facade_symbol("validate_vietnamese_narration", validate_vietnamese_narration)
        language_errors = vn_fn(narration_text.read_text(encoding="utf-8"))
    if language_errors:
        raise ValueError("; ".join(language_errors))
    expected_dims = (1920, 1080) if (is_longform and is_english_locale(locale)) else PORTRAIT_DIMENSIONS
    min_dur = 60.0 if is_longform else 14.0
    max_dur = (
        None
        if is_longform
        else (180.0 if platform == "youtube" else (60.0 if platform == "instagram" else None))
    )
    validate_vid_fn = _facade_symbol("validate_video", validate_video)
    errors = validate_vid_fn(
        video_path,
        narration,
        ffprobe,
        ffmpeg,
        min_dur,
        3.0,
        expected_dims,
        max_dur,
        narration_text if narration_text.is_file() else None,
        strict=strict,
        locale=locale,
    )
    if errors:
        raise ValueError("\n".join(errors))


def validate_project_quality(project_path: Path, strict: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]
    load_meta_fn = _facade_symbol("load_metadata", load_metadata)
    try:
        youtube_shorts_title(load_meta_fn(project_path)["title"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"YouTube Shorts title validation failed: {exc}") from exc

    metadata_validator = root / "scripts" / "validate_publish_metadata.py"
    if not metadata_validator.is_file():
        raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: metadata validator required")

    subproc = _facade_symbol("subprocess", subprocess)
    result = subproc.run(
        [sys.executable, str(metadata_validator), str(project_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        diagnostic = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise RuntimeError(diagnostic or f"metadata validator exited {result.returncode}")

    if strict:
        val_status_file = project_path / "validation_status.json"
        already_valid = False
        if val_status_file.is_file():
            try:
                v_data = json.loads(val_status_file.read_text(encoding="utf-8"))
                records = v_data if isinstance(v_data, list) else [v_data]
                for rec in reversed(records):
                    if rec.get("status") == "PASS" and rec.get("strict_quality_pass") is True:
                        already_valid = True
                        break
            except Exception:
                already_valid = False

        if not already_valid:
            agent_validator = root / "scripts" / "codex_agent_validation.py"
            if not agent_validator.is_file():
                raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: Codex agent validator required")

            env = dict(os.environ)
            ffprobe = shutil.which("ffprobe") or ""
            ffmpeg = shutil.which("ffmpeg") or ""
            if not ffprobe:
                candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
                if candidates:
                    env["PATH"] = str(candidates[0].parent) + ":" + env.get("PATH", "")
                    ffprobe = str(candidates[0])
            if not ffmpeg:
                candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
                if candidates:
                    ffmpeg = str(candidates[0])

            cmd = [sys.executable, str(agent_validator), str(project_path), "--strict", "--retry", "3"]
            if ffprobe:
                cmd.extend(["--ffprobe", ffprobe])
            if ffmpeg:
                cmd.extend(["--ffmpeg", ffmpeg])

            val_result = subproc.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
            )
            if val_result.returncode:
                diagnostic = "\n".join(part.strip() for part in (val_result.stdout, val_result.stderr) if part.strip())
                err_detail = diagnostic or f"validator exited {val_result.returncode}"
                raise RuntimeError(f"Codex Agent strict validation failed: {err_detail}")

    ffprobe = shutil.which("ffprobe") or ""
    ffmpeg = shutil.which("ffmpeg") or ""
    if not ffprobe:
        candidates = list(Path.home().glob(".local/share/uv/**/ffprobe"))
        ffprobe = str(candidates[0]) if candidates else ""
    if not ffmpeg:
        candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
        ffmpeg = str(candidates[0]) if candidates else ""
    validate_script = root / "scripts" / "validate_render_quality.py"
    if not validate_script.is_file() or not ffprobe or not ffmpeg:
        raise RuntimeError("STRICT QUALITY GATE UNAVAILABLE: validator, ffprobe, and ffmpeg are required")
    meta = load_meta_fn(project_path)
    fmt = meta.get("format")
    from lib.artifact_paths import resolve_project_locale, is_english_locale

    locale = resolve_project_locale(project_path)
    is_en = is_english_locale(locale)

    command = [
        sys.executable,
        str(validate_script),
        str(project_path),
        "--ffprobe",
        ffprobe,
        "--ffmpeg",
        ffmpeg,
    ]
    if is_en:
        if fmt in ("short", "shorts", "reels", "9x16"):
            command.extend(["--render", "reels", "--reels-max-duration", "180"])
        elif fmt in ("long", "longform", "16x9", "full"):
            command.extend(["--render", "full"])
        else:
            if (project_path / "renders" / "final_short_en_US_9x16.mp4").is_file():
                command.extend(["--render", "reels", "--reels-max-duration", "180"])
            elif (project_path / "renders" / "final_long_en_US_16x9.mp4").is_file():
                command.extend(["--render", "full"])
    else:
        command.extend(["--reels-max-duration", "60"])

    if strict:
        command.append("--strict")
    result = subproc.run(command, capture_output=True, text=True)
    if result.returncode:
        diagnostic = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise RuntimeError(diagnostic or f"validator exited {result.returncode}")


def enforce_release_preflight(
    project_dir: Path,
    metadata: dict,
    *,
    platforms: list[dict] | None = None,
    strict: bool = True,
    force: bool = False,
) -> None:
    """Unified release preflight gate."""
    root = Path(__file__).resolve().parents[1]

    # Step 1: Quality Validation (forward to facade in case patched)
    quality_fn = _facade_symbol("validate_project_quality", validate_project_quality)
    quality_fn(project_dir, strict=strict)

    # Step 2: Pipeline Checkpoints & Artifacts
    project_marker = project_dir / "project.json"
    pipeline_type = metadata.get("pipeline_type")
    if project_marker.is_file():
        try:
            with project_marker.open("r", encoding="utf-8") as f:
                marker_data = json.load(f)
            if not pipeline_type:
                pipeline_type = marker_data.get("pipeline_type")
        except Exception as e:
            raise RuntimeError(f"Release preflight failed: Invalid project.json: {e}") from e

    from lib.news_release_gate import is_news_project

    is_news = is_news_project(project_dir, metadata)

    if pipeline_type:
        from lib.checkpoint import (
            get_pipeline_stages,
            _stage_requires_approval,
            validate_checkpoint,
            CANONICAL_STAGE_ARTIFACTS,
        )
        from lib.pipeline_loader import load_pipeline_readonly

        try:
            stages = get_pipeline_stages(pipeline_type)
        except Exception:
            stages = []

        publish_idx = stages.index("publish") if "publish" in stages else len(stages)
        predecessor_stages = stages[:publish_idx]

        manifest_stages_dict = {}
        try:
            manifest = load_pipeline_readonly(pipeline_type)
            for st in manifest.get("stages", []):
                manifest_stages_dict[st.get("name")] = st
        except Exception:
            pass

        is_interactive_production = bool(
            (project_dir / "checkpoint_proposal.json").is_file()
            or (not is_news and (project_dir / "approval.json").is_file())
            or (project_dir / "human_approval.json").is_file()
            or "human_approval" in metadata
        )

        for st_name in predecessor_stages:
            cp_file = project_dir / f"checkpoint_{st_name}.json"
            if not cp_file.is_file():
                if is_news and not is_interactive_production:
                    continue
                raise RuntimeError(
                    f"Release preflight failed: Missing required stage checkpoint for {st_name!r} "
                    f"(expected {cp_file.name})"
                )
            try:
                with cp_file.open("r", encoding="utf-8") as f:
                    cp_data = json.load(f)
                validate_checkpoint(cp_data)
            except Exception as e:
                raise RuntimeError(
                    f"Release preflight failed: Invalid checkpoint for stage {st_name!r}: {e}"
                ) from e

            if cp_data.get("status") != "completed":
                raise RuntimeError(
                    f"Release preflight failed: Stage {st_name!r} status is {cp_data.get('status')!r}, "
                    f"expected 'completed'"
                )

            if _stage_requires_approval(pipeline_type, st_name) and not cp_data.get("human_approved"):
                raise RuntimeError(
                    f"Release preflight failed: Stage {st_name!r} requires human approval "
                    f"but human_approved is false"
                )

            produced = []
            if st_name in manifest_stages_dict:
                produced = manifest_stages_dict[st_name].get("produces", [])
            elif st_name in CANONICAL_STAGE_ARTIFACTS:
                produced = [CANONICAL_STAGE_ARTIFACTS[st_name]]

            for art in produced:
                art_in_cp = isinstance(cp_data.get("artifacts"), dict) and art in cp_data["artifacts"]
                art_on_disk = (
                    (project_dir / "artifacts" / f"{art}.json").is_file()
                    or (project_dir / "artifacts" / f"{art}_vi.json").is_file()
                    or (project_dir / f"{art}.json").is_file()
                )
                if not (art_in_cp or art_on_disk):
                    raise RuntimeError(
                        f"Release preflight failed: Missing required stage artifact {art!r} "
                        f"for stage {st_name!r}"
                    )

    # Step 3: Explicit Human Approval Bound to Media SHA-256
    is_interactive_production = bool(
        (project_dir / "checkpoint_proposal.json").is_file()
        or (project_dir / "approval.json").is_file()
        or (project_dir / "human_approval.json").is_file()
        or "human_approval" in metadata
    )
    if is_news and not is_interactive_production:
        requires_approval = False
    else:
        requires_approval = bool(
            project_marker.is_file()
            or is_interactive_production
            or os.environ.get("PRODUCTION_RELEASE") == "1"
            or os.environ.get("STRICT_PRODUCTION") == "1"
        )

    if requires_approval:
        approval = None
        if "human_approval" in metadata and isinstance(metadata["human_approval"], dict):
            approval = metadata["human_approval"]
        elif (project_dir / "approval.json").is_file():
            try:
                with (project_dir / "approval.json").open("r", encoding="utf-8") as f:
                    approval = json.load(f)
            except Exception as e:
                raise RuntimeError(f"Release preflight failed: Invalid approval.json: {e}") from e
        elif (project_dir / "human_approval.json").is_file():
            try:
                with (project_dir / "human_approval.json").open("r", encoding="utf-8") as f:
                    approval = json.load(f)
            except Exception as e:
                raise RuntimeError(f"Release preflight failed: Invalid human_approval.json: {e}") from e

        if isinstance(approval, list):
            approval = approval[-1] if approval else None

        if not approval or not isinstance(approval, dict):
            raise RuntimeError(
                f"Release preflight failed: Missing explicit human approval record for {project_dir.name}. "
                f"Publication requires human approval bound to media SHA-256."
            )

        if not (approval.get("approved") is True or approval.get("status") == "approved"):
            raise RuntimeError(
                f"Release preflight failed: Human approval status is not approved "
                f"(status={approval.get('status')!r}, approved={approval.get('approved')!r})"
            )

        from lib.artifact_paths import resolve_project_locale, is_english_locale

        locale = resolve_project_locale(project_dir)
        is_us = is_english_locale(locale) or metadata.get("audience") == "us"
        if is_us or "signature" in approval:
            if not approval or not isinstance(approval, dict):
                raise RuntimeError("Release preflight failed: mandatory approval.json missing or invalid for US project")
            from lib.qa_signing import verify_approval_record

            valid_sig, sig_msg = verify_approval_record(
                approval, project_dir.name, project_dir=project_dir, require_manifest=is_us
            )
            if not valid_sig:
                raise RuntimeError(f"Release preflight failed: {sig_msg}")

            ledger_file = project_dir / "artifacts" / "claim_ledger.json"
            if is_us:
                if not ledger_file.is_file():
                    raise RuntimeError("Release preflight failed: mandatory claim_ledger.json missing for US project")
                import hashlib

                h_c = hashlib.sha256(ledger_file.read_bytes()).hexdigest()
                approved_claim_sha = approval.get("claim_ledger_sha256")
                if approved_claim_sha and h_c != approved_claim_sha:
                    raise RuntimeError(
                        f"Release preflight failed: claim ledger SHA-256 mismatch ({h_c} != {approved_claim_sha})"
                    )

        media_to_check: list[tuple[str, Path]] = []
        resolve_vid_fn = _facade_symbol("resolve_video_path", resolve_video_path)
        if platforms:
            for p in platforms:
                vp = resolve_vid_fn(p["video_path"], project_dir, root)
                media_to_check.append((p["platform"], vp))
        else:
            for k in ("yt_shorts", "yt_longform", "youtube_video", "ig_reels", "fb_video", "fb_reels"):
                if k in metadata:
                    vp = resolve_vid_fn(metadata[k], project_dir, root)
                    plat = "youtube" if "yt" in k else ("instagram" if "ig" in k else "facebook")
                    media_to_check.append((plat, vp))

        approved_sha = approval.get("approved_media_sha256") or approval.get("media_sha256")
        approved_hashes_list = approval.get("approved_media_hashes", [])
        approved_by_plat = approval.get("media_sha256_by_platform", {})

        for plat, v_path in media_to_check:
            if not v_path.is_file():
                continue
            actual_sha = file_sha256(v_path)
            plat_approved_sha = approved_by_plat.get(plat) or approved_sha

            hash_matched = (
                (plat_approved_sha and actual_sha == plat_approved_sha)
                or (actual_sha in approved_hashes_list)
            )
            if not hash_matched:
                raise RuntimeError(
                    f"Release preflight failed: Media SHA-256 mismatch for {v_path.name} on {plat}. "
                    f"File SHA-256 is {actual_sha}, but approved hash is {plat_approved_sha!r}. "
                    f"Asset has been modified after human approval!"
                )

            val_status_file = project_dir / "validation_status.json"
            if val_status_file.is_file():
                inspected_hashes = set()
                try:
                    with val_status_file.open("r", encoding="utf-8") as f:
                        v_stat = json.load(f)
                    entries = v_stat if isinstance(v_stat, list) else [v_stat]
                    for entry in reversed(entries):
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("project_id") not in (None, project_dir.name):
                            continue
                        hashes = [entry.get("inspected_artifact_hash")]
                        details = entry.get("details")
                        results = details.get("results", []) if isinstance(details, dict) else []
                        if isinstance(results, list):
                            for result in results:
                                result_details = result.get("details") if isinstance(result, dict) else None
                                if isinstance(result_details, dict):
                                    hashes.append(result_details.get("inspected_artifact_hash"))
                        inspected_hashes = {h for h in hashes if isinstance(h, str) and h}
                        if inspected_hashes:
                            break
                except (json.JSONDecodeError, OSError):
                    pass
                if inspected_hashes and actual_sha not in inspected_hashes:
                    raise RuntimeError(
                        f"Release preflight failed: Stale validation review! "
                        f"Codex agent inspected hashes {sorted(inspected_hashes)}, but media file hash is {actual_sha}. "
                        f"Re-validation required."
                    )

        approved_title = approval.get("approved_title") or approval.get("title")
        if approved_title is not None and metadata.get("title") != approved_title:
            raise RuntimeError(
                f"Release preflight failed: Post title has been altered since approval. "
                f"Approved: {approved_title!r}, Current: {metadata.get('title')!r}"
            )

        approved_desc = approval.get("approved_description") or approval.get("description")
        if approved_desc is not None and metadata.get("description") != approved_desc:
            raise RuntimeError(
                f"Release preflight failed: Post description has been altered since approval. "
                f"Approved: {approved_desc!r}, Current: {metadata.get('description')!r}"
            )

        approved_accounts = approval.get("target_accounts", {})
        if not approved_accounts and approval.get("account"):
            approved_accounts = {"all": approval.get("account")}
        if platforms:
            for p in platforms:
                plat = p["platform"]
                acct = p.get("account", "")
                target_match = approved_accounts.get(plat) or approved_accounts.get("all")
                if target_match and str(target_match) != str(acct):
                    raise RuntimeError(
                        f"Release preflight failed: Target account mismatch for {plat}. "
                        f"Configured account: {acct!r}, Approved account: {target_match!r}"
                    )

        approved_time = (
            approval.get("release_time")
            or approval.get("publish_time")
            or approval.get("scheduled_for")
        )
        if approved_time is not None:
            actual_time = metadata.get("publish_time") or metadata.get("publish_date")
            if actual_time and approved_time != actual_time and not approved_time.startswith(str(actual_time)):
                raise RuntimeError(
                    f"Release preflight failed: Release time mismatch. "
                    f"Approved: {approved_time!r}, Scheduled: {actual_time!r}"
                )


__all__ = [
    "safe_resolve_publish_path",
    "load_metadata",
    "resolve_video_path",
    "validate_publish_asset",
    "validate_project_quality",
    "enforce_release_preflight",
]
