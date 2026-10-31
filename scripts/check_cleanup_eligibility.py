"""Unified project cleanup eligibility contract for OpenMontage.

Enforces that NO project is deleted unless all required publish destinations
are verified published in the PublishStore (matching media hashes) or recorded
in the durable audit log. Age, lack of queue presence, or partial publication
never substitute for verified completion.

Inspection and dry-run operations are strictly read-only: they never mutate
the PublishStore, queue files, audit logs, or media files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("OPENMONTAGE_ROOT") or Path(__file__).resolve().parents[1])
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_store import PublishStore, publish_key, file_sha256
from tools.publishers.platform_routes import PLATFORM_ROUTES


def _resolve_render_file(
    resolved_dir: Path,
    platform: str,
    meta: dict[str, Any],
    rec: dict[str, Any] | None = None,
    stored_hash: str | None = None,
) -> Path | None:
    """Resolve on-disk render file for platform, supporting US English and Vietnamese."""
    if rec and rec.get("asset_path"):
        cand = Path(rec["asset_path"])
        if cand.is_file():
            return cand
        cand_renders = resolved_dir / "renders" / cand.name
        if cand_renders.is_file():
            return cand_renders

    field = PLATFORM_ROUTES.get(platform, (None, None, None))[1]
    meta_render = meta.get(field) if field else None
    if isinstance(meta_render, dict):
        meta_render = meta_render.get("path")
    if meta_render:
        cand = resolved_dir / meta_render
        if cand.is_file():
            return cand

    def_render = PLATFORM_ROUTES.get(platform, (None, None, "renders/final_reels_vi_9x16.mp4"))[2]
    cand = resolved_dir / def_render
    if cand.is_file():
        return cand

    renders_dir = resolved_dir / "renders"
    if renders_dir.is_dir():
        if stored_hash:
            for f in renders_dir.glob("*.mp4"):
                if file_sha256(f) == stored_hash:
                    return f
        for name in ("final_short_en_US_9x16.mp4", "final_long_en_US_16x9.mp4", "final_reels_vi_9x16.mp4", "final_full_vi_9x16.mp4"):
            cand = renders_dir / name
            if cand.is_file():
                return cand

    return None


def _classify_outcome(outcomes: list | None, route: str, outcome: str, detail: str) -> None:
    """Record a per-route reconciliation outcome for CLI reporting (no-op when None)."""
    if outcomes is not None:
        outcomes.append({"route": route, "outcome": outcome, "detail": detail})


def _classify_youtube_outcome(v_status: Any) -> tuple[str, str]:
    """Classify a YouTube remote-check result: a hard API/auth failure is an
    actionable block; 'still not proven public' is a safe pending state."""
    if v_status is None:
        return "blocked_error", "remote check returned no status (auth/API unavailable)"
    status = v_status.get("status")
    if status == "error" or v_status.get("error_type") in ("auth_required", "http_error", "unavailable"):
        detail = str(v_status.get("error") or v_status.get("error_type") or status)
        return "blocked_error", detail[:300]
    return "pending_unverified", f"remote status={v_status.get('privacy_status') or status or 'unknown'} is not authoritative public+processed"


def _classify_meta_outcome(m_status: Any, platform: str) -> tuple[str, str]:
    """Classify a Meta remote-check result: a hard API/auth failure is an
    actionable block; 'still not proven published' is a safe pending state."""
    if m_status is None:
        return "blocked_error", f"{platform} remote check returned no status (auth/API unavailable)"
    status = m_status.get("status")
    if status == "error" or m_status.get("error_type") in ("auth_required", "http_error", "unavailable"):
        detail = str(m_status.get("error") or m_status.get("error_type") or status)
        return "blocked_error", detail[:300]
    if status != "published":
        return "pending_unverified", f"{platform} remote status={status or 'unknown'} is not published"
    return "promoted", "Graph API confirmed published"


def reconcile_scheduled_record(
    store: PublishStore,
    key: str,
    record: dict[str, Any],
    outcomes: list | None = None,
) -> dict[str, Any]:
    """Attempt to reconcile a remotely scheduled publication that may have gone live.

    CRITICAL SAFETY (R1): Fails closed. Never uses elapsed time, upload acceptance,
    or processing status alone to authorize publication. Requires authoritative
    evidence of public visibility and completed publication.

    When ``outcomes`` (a list) is supplied, a per-route outcome record is appended
    for this attempt so callers can distinguish blocked verification (hard API/auth
    failure) from legitimate pending/no-op states. The return type is unchanged.
    """
    platform = record.get("platform")
    # Records carry no explicit kind; the canonical routes are youtube/short and
    # instagram|facebook/reels (matching write_audit_tombstone's platform_records).
    kind = "short" if platform == "youtube" else "reels"
    route = f"{platform}/{kind}" if platform else "?"
    status = record.get("status")
    if status != "scheduled":
        _classify_outcome(outcomes, route, "no_op", f"record status is {status!r}")
        return record

    scheduled_for = record.get("scheduled_for")
    if not scheduled_for:
        _classify_outcome(outcomes, route, "no_op", "no scheduled_for timestamp")
        return record

    try:
        sched_dt = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        if now_dt < sched_dt:
            # Scheduled time in the future; cannot be published yet
            _classify_outcome(outcomes, route, "not_due", f"scheduled for {scheduled_for}")
            return record
    except Exception:
        _classify_outcome(outcomes, route, "no_op", f"unparseable scheduled_for {scheduled_for!r}")
        return record

    video_id = record.get("video_id") or record.get("platform_id")
    if not video_id:
        _classify_outcome(outcomes, route, "pending_unverified", "no remote id to verify; waiting for upload registration")
        return record

    if platform == "youtube":
        try:
            from tools.publishers.youtube_publisher import YoutubePublisher
            pub = YoutubePublisher()
            v_status = pub.check_video_published(video_id)
            # R1: Must require verified authoritative API public visibility and processed upload status.
            # Do NOT accept private processed video, unverified oEmbed responses, or elapsed time.
            is_data_api_verified = (
                v_status
                and v_status.get("status") in ("found", None)
                and not v_status.get("via_oembed")
                and v_status.get("status") != "unverified_oembed"
                and v_status.get("privacy_status") == "public"
                and v_status.get("upload_status") == "processed"
            )
            # Verified oEmbed: when Data API is blocked (e.g. upload-only OAuth scope),
            # oEmbed proves public status (HTTP 200) once scheduled time has passed
            # and video title matches the scheduled publication record.
            is_oembed_verified = False
            if (
                v_status
                and v_status.get("via_oembed")
                and v_status.get("video_id") == video_id
            ):
                rec_title = record.get("normalized_title") or record.get("title")
                oembed_title = v_status.get("title")
                if rec_title and oembed_title:
                    from tools.publish_store import normalize_identity
                    norm_rec = normalize_identity(rec_title)
                    norm_oembed = normalize_identity(oembed_title)
                    if norm_rec == norm_oembed or norm_rec in norm_oembed or norm_oembed in norm_rec:
                        is_oembed_verified = True
                elif v_status.get("status") == "verified_oembed":
                    is_oembed_verified = True

            if is_data_api_verified or is_oembed_verified:
                now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                remote_status = v_status.copy() if isinstance(v_status, dict) else {}
                remote_status["privacy_status"] = "public"
                remote_status["upload_status"] = "processed"
                remote_status["status"] = "published"
                updated = store.mark_published(
                    key,
                    video_id=video_id,
                    video_url=record.get("video_url"),
                    published_at=scheduled_for,
                    verified_at=now_iso,
                    remote_status=remote_status,
                )
                _classify_outcome(outcomes, route, "promoted", "authoritative public+processed evidence persisted")
                return updated
            outcome, detail = _classify_youtube_outcome(v_status)
            _classify_outcome(outcomes, route, outcome, detail)
        except Exception as exc:
            print(f"DEBUG: YouTube status check failed for {video_id}: {exc}", file=sys.stderr)
            _classify_outcome(outcomes, route, "blocked_error", f"exception: {exc}")

    elif platform in ("instagram", "facebook"):
        try:
            from tools.publishers.meta_publisher import MetaPublisher
            mp = MetaPublisher()
            m_status = mp.check_media_published(video_id, platform=platform)
            # R1: Must have authoritative remote confirmation from Meta Graph API.
            # Do NOT mark published from elapsed timestamp and ID alone.
            if m_status and m_status.get("status") == "published":
                now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                updated = store.mark_published(
                    key,
                    video_id=video_id,
                    video_url=record.get("video_url"),
                    platform_id=record.get("platform_id") or video_id,
                    published_at=scheduled_for,
                    verified_at=now_iso,
                    remote_status=m_status,
                )
                _classify_outcome(outcomes, route, "promoted", "Graph API confirmed published")
                return updated
            outcome, detail = _classify_meta_outcome(m_status, platform)
            _classify_outcome(outcomes, route, outcome, detail)
        except Exception as exc:
            print(f"DEBUG: Meta status check failed for {video_id} ({platform}): {exc}", file=sys.stderr)
            _classify_outcome(outcomes, route, "blocked_error", f"exception: {exc}")

    elif platform == "tiktok":
        try:
            from tools.publishers.tiktok_publisher import TiktokPublisher
            tp = TiktokPublisher()
            t_status = tp.check_video_published(video_id)
            if t_status and t_status.get("status") == "published":
                now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                updated = store.mark_published(
                    key,
                    video_id=video_id,
                    video_url=record.get("video_url"),
                    platform_id=record.get("platform_id") or video_id,
                    published_at=scheduled_for,
                    verified_at=now_iso,
                    remote_status=t_status,
                )
                _classify_outcome(outcomes, route, "promoted", "TikTok Creator Studio confirmed published")
                return updated
            _classify_outcome(outcomes, route, "pending_unverified", f"TikTok status={t_status.get('status') if t_status else 'unknown'}")
        except Exception as exc:
            print(f"DEBUG: TikTok status check failed for {video_id}: {exc}", file=sys.stderr)
            _classify_outcome(outcomes, route, "blocked_error", f"exception: {exc}")

    _classify_outcome(outcomes, route, "pending_unverified", "remote check returned no authoritative evidence")
    return record


def reconcile_project_publications(
    store: PublishStore,
    project_id: str,
    date: str,
    routes: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Explicit mutating operation to reconcile scheduled records for a project.

    Returns (updated_records, outcomes): promotions plus a per-route outcome
    list that distinguishes blocked verification from legitimate pending/no-op.
    """
    updated_records = []
    outcomes: list[dict[str, Any]] = []
    for platform, kind in routes:
        key = publish_key(date, project_id, platform, kind)
        rec = store.get(key)
        if rec and rec.get("status") == "scheduled":
            updated = reconcile_scheduled_record(store, key, rec, outcomes=outcomes)
            if updated and updated.get("status") == "published":
                updated_records.append(updated)
    return updated_records, outcomes


def is_project_eligible_for_cleanup(
    project_id: str,
    *,
    project_dir: Path | str | None = None,
    store: PublishStore | None = None,
    date: str | None = None,
    config_path: Path | None = None,
    root: Path | None = None,
    held_platforms: set[str] | list[str] | str | None = None,
    enabled_platforms: set[str] | list[str] | str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify if a project is fully published across all required destinations and eligible for cleanup.
    
    STRICTLY READ-ONLY (R2): Produces zero writes to PublishStore, queue files,
    audit records, or media directories.
    
    Returns:
        (is_eligible: bool, reason: str, metadata: dict)
    """
    if root is None:
        env_root = os.environ.get("OPENMONTAGE_ROOT")
        if env_root:
            root = Path(env_root).resolve()
        elif project_dir is not None:
            # Infer root from project_dir structure if within projects/ or projects_news/
            p = Path(project_dir).resolve()
            if p.parent.name in ("projects", "projects_news"):
                root = p.parent.parent
            elif p.parent.name == "instagram" and p.parent.parent.name == "projects":
                root = p.parent.parent.parent
            else:
                root = ROOT
        else:
            root = ROOT

    projects_root = (root / "projects").resolve()
    projects_news_root = (root / "projects_news").resolve()
    ig_parent = (projects_root / "instagram").resolve()
    authorized_roots = (projects_root, projects_news_root, ig_parent)

    # 1. Path safety and duplicate location check (R5)
    # Check original input for symlinks BEFORE resolution
    if project_dir is not None:
        cand_input = Path(project_dir)
        if cand_input.is_symlink():
            return False, f"unsafe_symlink_rejected: {cand_input}", {}
        for parent in cand_input.parents:
            if parent.is_symlink():
                return False, f"unsafe_ancestor_symlink_rejected: {parent}", {}

    # Scan for duplicate project directories across authorized locations
    found_dirs: list[Path] = []
    for loc in [
        projects_root / project_id,
        projects_news_root / project_id,
        ig_parent / project_id,
    ]:
        if loc.is_dir():
            found_dirs.append(loc.resolve())

    # R5: Reject duplicate project locations even when an explicit path is supplied
    if len(found_dirs) > 1:
        return False, f"duplicate_project_directories_found: {[str(d) for d in found_dirs]}", {}

    resolved_dir: Path | None = None
    if project_dir is not None:
        resolved_dir = Path(project_dir).resolve()
        # Verify directory name matches project_id
        if resolved_dir.name != project_id:
            return False, f"directory_name_mismatch: {resolved_dir.name} != {project_id}", {}
        # Verify containment within authorized roots
        is_contained = False
        for auth_root in authorized_roots:
            try:
                rel = resolved_dir.relative_to(auth_root)
                if rel.parts and rel.parts[0] == project_id and len(rel.parts) == 1:
                    is_contained = True
                    break
            except ValueError:
                pass
        if not is_contained:
            return False, f"unauthorized_project_path: {resolved_dir}", {}
    elif found_dirs:
        resolved_dir = found_dirs[0]
    else:
        resolved_dir = (projects_root / project_id).resolve()

    # 2. Load project metadata and check identity
    meta: dict[str, Any] = {}
    if resolved_dir and (resolved_dir / "publish_metadata.json").is_file():
        try:
            meta = json.loads((resolved_dir / "publish_metadata.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    # R5: Validate metadata identity
    meta_id = meta.get("id") or meta.get("project_id")
    if meta_id and meta_id != project_id:
        return False, f"metadata_identity_mismatch: {meta_id} != {project_id}", meta

    pub_date = date or meta.get("publish_date") or meta.get("date")

    # 3. Check publish schedule if available and date not yet resolved
    cfg_file = config_path or (root / "config" / "publish_schedule.json")
    if cfg_file.is_file() and not pub_date:
        try:
            sched = json.loads(cfg_file.read_text(encoding="utf-8"))
            for item in sched.get("active_projects", []):
                pid = item.get("project_id") if isinstance(item, dict) else item
                if pid == project_id and isinstance(item, dict):
                    pub_date = item.get("publish_date")
                    break
        except Exception:
            pass

    # 4. Determine required routes from project assets and approved metadata
    from scripts.publish_manual_video import get_required_routes_for_project
    required_routes = get_required_routes_for_project(
        project_id,
        project_dir=resolved_dir if (resolved_dir and resolved_dir.is_dir()) else None,
        metadata=meta,
        held_platforms=held_platforms,
        enabled_platforms=enabled_platforms,
    )
    if not required_routes:
        all_routes = get_required_routes_for_project(
            project_id,
            project_dir=resolved_dir if (resolved_dir and resolved_dir.is_dir()) else None,
            metadata=meta,
            ignore_held=True,
            ignore_disabled=True,
        )
        if all_routes:
            return False, "all_candidate_routes_currently_held", {}
        return False, "no_required_routes_identified_fail_closed", {}

    # 5. Check PublishStore if available (STRICTLY READ-ONLY - R2)
    if store is None:
        try:
            store = PublishStore()
        except Exception:
            store = None

    candidate_enabled_routes = get_required_routes_for_project(
        project_id,
        project_dir=resolved_dir if (resolved_dir and resolved_dir.is_dir()) else None,
        metadata=meta,
        ignore_held=True,
        enabled_platforms=enabled_platforms,
    )
    held_routes = [r for r in candidate_enabled_routes if r not in required_routes]
    if held_routes:
        if store is not None and pub_date:
            unpub_held = []
            for hp, hk in held_routes:
                h_rec = store.get(publish_key(pub_date, project_id, hp, hk))
                if not h_rec or h_rec.get("status") != "published":
                    unpub_held.append((hp, hk))
            if unpub_held:
                return False, f"held_routes_pending: {unpub_held}", meta
        else:
            return False, f"held_routes_pending: {held_routes}", meta

    has_active_store_records = False
    all_store_published = True
    missing_or_incomplete = []

    if store is not None and pub_date:
        for platform, kind in required_routes:
            key = publish_key(pub_date, project_id, platform, kind)
            rec = store.get(key)
            # R2: Do NOT call reconcile_scheduled_record here! Inspection is strictly read-only.
            if rec is not None:
                has_active_store_records = True
                if rec.get("status") != "published":
                    all_store_published = False
                    status = rec.get("status")
                    missing_or_incomplete.append(f"{platform}/{kind} (status={status})")
                else:
                    # Require verified public release evidence; unverified uploads do not authorize cleanup
                    remote_st = rec.get("remote_status") or {}
                    if platform == "youtube":
                        if remote_st.get("privacy_status") != "public" or remote_st.get("upload_status") != "processed":
                            all_store_published = False
                            missing_or_incomplete.append(f"{platform}/{kind} (missing_authoritative_public_evidence)")
                    elif platform in ("instagram", "facebook"):
                        # R1: a bare verified_at timestamp is NOT authoritative remote evidence.
                        # The platform record must carry the Graph-API confirmation that the
                        # media is publicly published. Symmetric to the YouTube check above.
                        if remote_st.get("status") != "published":
                            all_store_published = False
                            missing_or_incomplete.append(f"{platform}/{kind} (missing_authoritative_public_evidence)")
            else:
                all_store_published = False
                missing_or_incomplete.append(f"{platform}/{kind} (status=missing)")

        # Historical cleanup records must not override incomplete or conflicting current publication records.
        if has_active_store_records and not all_store_published:
            return False, f"destinations_incomplete: {', '.join(missing_or_incomplete)}", meta

        if all_store_published and not missing_or_incomplete:
            # R3: Verify exact platform asset and media hash binding if project directory exists
            if resolved_dir and resolved_dir.is_dir():
                for platform, kind in required_routes:
                    key = publish_key(pub_date, project_id, platform, kind)
                    rec = store.get(key)
                    stored_hash = rec.get("media_sha256") or rec.get("source_sha256")
                    if not stored_hash:
                        # R3: Missing hash fails closed; never skip verification
                        return (
                            False,
                            f"missing_media_hash_for_{platform}_{kind}_fail_closed",
                            meta,
                        )

                    render_file = _resolve_render_file(resolved_dir, platform, meta, rec=rec, stored_hash=stored_hash)
                    if not render_file or not render_file.is_file():
                        return (
                            False,
                            f"missing_render_file_for_{platform}_{kind}",
                            meta,
                        )

                    current_hash = file_sha256(render_file)
                    if stored_hash != current_hash:
                        return (
                            False,
                            f"media_hash_mismatch for {platform}/{kind}: stored={stored_hash[:10]} current={current_hash[:10]}",
                            meta,
                        )

            return True, "all_required_destinations_verified_published", meta

    # 6. Check durable audit archive if store is not available or has no records
    archive_file = root / "logs" / "published_archive.jsonl"
    if archive_file.is_file():
        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line)
                    if (
                        entry.get("project_id") != project_id
                        or entry.get("cleanup_state") != "cleanup_completed"
                    ):
                        continue

                    # Release date check: missing archive date must fail closed for existing media
                    entry_date = entry.get("date")
                    if not entry_date:
                        if resolved_dir and resolved_dir.is_dir():
                            return False, "audit_archive_missing_date_fail_closed", meta
                        continue

                    if pub_date and entry_date != pub_date:
                        continue

                    # Required destination scope check: platform_records must be non-empty
                    plat_records = entry.get("platform_records")
                    if not plat_records or not isinstance(plat_records, dict):
                        if resolved_dir and resolved_dir.is_dir():
                            return False, "audit_archive_missing_or_empty_platform_records_fail_closed", meta
                        continue

                    all_covered = all(
                        plat_records.get(f"{p}/{k}", {}).get("status") == "published"
                        for p, k in required_routes
                    )
                    if not all_covered:
                        if resolved_dir and resolved_dir.is_dir():
                            return False, "audit_archive_incomplete_destinations_fail_closed", meta
                        continue

                    # R3: Separate already-deleted recovery from deleting newly present media
                    if resolved_dir and resolved_dir.is_dir():
                        tombstone_hashes = entry.get("media_hashes")
                        if not tombstone_hashes or not isinstance(tombstone_hashes, dict):
                            return False, "audit_archive_missing_media_hashes_fail_closed", meta

                        # Verify every required destination's render matches the tombstone
                        for platform, kind in required_routes:
                            render_file = _resolve_render_file(resolved_dir, platform, meta)
                            if not render_file or not render_file.is_file():
                                return False, f"missing_render_file_for_archive_check_{platform}_{kind}", meta
                            if render_file.name not in tombstone_hashes:
                                return False, f"archive_missing_hash_for_{render_file.name}", meta
                            if file_sha256(render_file) != tombstone_hashes[render_file.name]:
                                return False, f"audit_hash_mismatch_with_current_media for {render_file.name}", meta

                        # Also verify any other rendered mp4 matches tombstone (reject newly present / modified renders)
                        renders_dir = resolved_dir / "renders"
                        if renders_dir.is_dir():
                            for fpath in renders_dir.glob("*.mp4"):
                                if fpath.name not in tombstone_hashes:
                                    return False, f"unrecognized_new_media_file_in_archive_check_{fpath.name}", meta
                                if file_sha256(fpath) != tombstone_hashes[fpath.name]:
                                    return False, f"audit_hash_mismatch_with_current_media for {fpath.name}", meta
                        return True, "verified_via_audit_archive", meta
                    else:
                        # Project directory already removed; safe idempotent recovery
                        return True, "verified_via_audit_archive", meta
        except Exception:
            pass

    if missing_or_incomplete:
        return False, f"destinations_incomplete: {', '.join(missing_or_incomplete)}", meta
    return False, "unverified_publication_records_and_no_matching_audit_tombstone", meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Check project cleanup eligibility (strictly read-only)")
    parser.add_argument("--pid", required=True, help="Project ID")
    parser.add_argument("--dir", help="Project directory path")
    parser.add_argument("--date", help="Publish date (YYYY-MM-DD)")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Non-deleting reconciliation: query existing remote status for scheduled records and persist authoritative evidence. Never uploads or deletes.",
    )
    parser.add_argument(
        "--hold-platform",
        action="append",
        default=[],
        dest="hold_platforms_list",
        help="Hold (pause/skip) publishing to specific platform (e.g. ig, fb, tiktok, ytb). Can be repeated.",
    )
    parser.add_argument(
        "--hold-platforms",
        type=str,
        default="",
        help="Comma-separated platforms to hold (e.g. 'ig,fb,tiktok,ytb')",
    )
    parser.add_argument("--hold-ig", action="store_true", help="Hold Instagram publishing")
    parser.add_argument("--hold-fb", action="store_true", help="Hold Facebook publishing")
    parser.add_argument("--hold-tiktok", action="store_true", help="Hold TikTok publishing")
    parser.add_argument("--hold-ytb", action="store_true", help="Hold YouTube publishing")
    parser.add_argument(
        "--enabled-platforms",
        type=str,
        default="",
        help="Comma-separated platforms to enable (e.g. 'ytb' or 'youtube,instagram')",
    )
    parser.add_argument(
        "--enable-platform",
        action="append",
        default=[],
        dest="enabled_platforms_list",
        help="Enable a specific platform (e.g. ytb, ig, fb, tiktok). Can be repeated.",
    )
    args = parser.parse_args()

    cli_held: list[str] = list(args.hold_platforms_list)
    if args.hold_platforms:
        cli_held.append(args.hold_platforms)
    if args.hold_ig:
        cli_held.append("instagram")
    if args.hold_fb:
        cli_held.append("facebook")
    if args.hold_tiktok:
        cli_held.append("tiktok")
    if args.hold_ytb:
        cli_held.append("youtube")

    cli_enabled: list[str] = list(args.enabled_platforms_list)
    if args.enabled_platforms:
        cli_enabled.append(args.enabled_platforms)
    if not cli_enabled:
        cli_enabled = None

    if args.reconcile:
        return _run_reconciliation(args.pid, args.date, held_platforms=cli_held, enabled_platforms=cli_enabled)

    eligible, reason, _ = is_project_eligible_for_cleanup(
        args.pid,
        project_dir=Path(args.dir) if args.dir else None,
        date=args.date,
        held_platforms=cli_held,
        enabled_platforms=cli_enabled,
    )
    if eligible:
        print(f"ELIGIBLE: {args.pid} ({reason})")
        return 0
    else:
        print(f"NOT_ELIGIBLE: {args.pid} ({reason})")
        return 1


def _run_reconciliation(
    project_id: str,
    date: str | None,
    held_platforms: set[str] | list[str] | str | None = None,
    enabled_platforms: set[str] | list[str] | str | None = None,
) -> int:
    """Canonical, non-deleting reconciliation path (Finding 3).

    Queries existing remote publication status for scheduled records and persists
    authoritative evidence via mark_published(verified_at, remote_status). It never
    uploads a new video, never deletes, and is safe to retry: only records in
    `scheduled` state are transitioned, and only when the remote endpoint confirms
    public visibility + processed upload. Failed/overdue records stay `scheduled`
    for a later retry without duplicate uploads.
    """
    from scripts.publish_manual_video import get_required_routes_for_project
    from tools.publish_store import PublishStore

    try:
        store = PublishStore()
    except Exception as exc:
        print(f"RECONCILE_BLOCKED: PublishStore unavailable ({exc})", file=sys.stderr)
        return 2

    routes = get_required_routes_for_project(
        project_id, held_platforms=held_platforms, enabled_platforms=enabled_platforms
    )
    if not routes:
        print(f"RECONCILE_SKIP: no required routes identified for {project_id}")
        return 0

    pub_date = date or _infer_publish_date(store, project_id)
    if not pub_date:
        print(f"RECONCILE_SKIP: no publish date resolvable for {project_id}")
        return 0

    updated, outcomes = reconcile_project_publications(store, project_id, pub_date, routes)
    for rec in updated:
        print(
            f"RECONCILED: {rec.get('key') or rec.get('platform_id') or rec.get('video_id')} "
            f"-> published (verified_at={rec.get('verified_at')})"
        )
    blocked = [o for o in outcomes if o["outcome"] == "blocked_error"]
    pending = [o for o in outcomes if o["outcome"] == "pending_unverified"]
    for o in blocked:
        print(
            f"RECONCILE_BLOCKED: {project_id} [{o['route']}] {o['detail']}",
            file=sys.stderr,
        )
    for o in pending:
        print(f"RECONCILE_PENDING: {project_id} [{o['route']}] {o['detail']}")
    if not updated and not blocked and not pending:
        print(
            f"RECONCILE_NO_CHANGE: {project_id} on {pub_date} (no scheduled record promoted; safe to retry)"
        )
    return 2 if blocked else 0


def _infer_publish_date(store, project_id: str) -> str | None:
    """Read-only inference of publish date from an active schedule entry if present."""
    import json as _json
    cfg = ROOT / "config" / "publish_schedule.json"
    if cfg.is_file():
        try:
            sched = _json.loads(cfg.read_text(encoding="utf-8"))
            for item in sched.get("active_projects", []):
                pid = item.get("project_id") if isinstance(item, dict) else item
                if pid == project_id and isinstance(item, dict):
                    return item.get("publish_date")
        except Exception:
            pass
    return None


if __name__ == "__main__":
    sys.exit(main())
