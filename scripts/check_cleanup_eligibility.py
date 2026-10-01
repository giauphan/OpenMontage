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


def reconcile_scheduled_record(store: PublishStore, key: str, record: dict[str, Any]) -> dict[str, Any]:
    """Attempt to reconcile a remotely scheduled publication that may have gone live.
    
    CRITICAL SAFETY (R1): Fails closed. Never uses elapsed time, upload acceptance,
    or processing status alone to authorize publication. Requires authoritative
    evidence of public visibility and completed publication.
    """
    status = record.get("status")
    if status != "scheduled":
        return record

    scheduled_for = record.get("scheduled_for")
    if not scheduled_for:
        return record

    try:
        sched_dt = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        if now_dt < sched_dt:
            # Scheduled time in the future; cannot be published yet
            return record
    except Exception:
        return record

    platform = record.get("platform")
    video_id = record.get("video_id") or record.get("platform_id")
    if not video_id:
        return record

    if platform == "youtube":
        try:
            from tools.publishers.youtube_publisher import YoutubePublisher
            pub = YoutubePublisher()
            v_status = pub.check_video_published(video_id)
            # R1: Must require verified authoritative API public visibility and processed upload status.
            # Do NOT accept private processed video, unverified oEmbed responses, or elapsed time.
            if (
                v_status
                and v_status.get("status") in ("found", None)
                and not v_status.get("via_oembed")
                and v_status.get("status") != "unverified_oembed"
                and v_status.get("privacy_status") == "public"
                and v_status.get("upload_status") == "processed"
            ):
                now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                updated = store.mark_published(
                    key,
                    video_id=video_id,
                    video_url=record.get("video_url"),
                    published_at=scheduled_for,
                    verified_at=now_iso,
                    remote_status=v_status,
                )
                return updated
        except Exception as exc:
            print(f"DEBUG: YouTube status check failed for {video_id}: {exc}", file=sys.stderr)

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
                return updated
        except Exception as exc:
            print(f"DEBUG: Meta status check failed for {video_id} ({platform}): {exc}", file=sys.stderr)

    return record


def reconcile_project_publications(
    store: PublishStore,
    project_id: str,
    date: str,
    routes: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Explicit mutating operation to reconcile scheduled records for a project."""
    updated_records = []
    for platform, kind in routes:
        key = publish_key(date, project_id, platform, kind)
        rec = store.get(key)
        if rec and rec.get("status") == "scheduled":
            updated = reconcile_scheduled_record(store, key, rec)
            if updated and updated.get("status") == "published":
                updated_records.append(updated)
    return updated_records


def is_project_eligible_for_cleanup(
    project_id: str,
    *,
    project_dir: Path | str | None = None,
    store: PublishStore | None = None,
    date: str | None = None,
    config_path: Path | None = None,
    root: Path | None = None,
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
    )
    if not required_routes:
        return False, "no_required_routes_identified_fail_closed", {}

    # 5. Check PublishStore if available (STRICTLY READ-ONLY - R2)
    if store is None:
        try:
            store = PublishStore()
        except Exception:
            store = None

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
                        if remote_st.get("status") != "published" and not rec.get("verified_at"):
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
                    stored_hash = rec.get("media_sha256")
                    if not stored_hash:
                        # R3: Missing hash fails closed; never skip verification
                        return (
                            False,
                            f"missing_media_hash_for_{platform}_{kind}_fail_closed",
                            meta,
                        )

                    rel_render = PLATFORM_ROUTES.get(platform, (None, None, "renders/final_reels_vi_9x16.mp4"))[2]
                    render_file = resolved_dir / rel_render
                    if not render_file.is_file():
                        return (
                            False,
                            f"missing_render_file_{render_file.name}_for_{platform}_{kind}",
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
                            rel_render = PLATFORM_ROUTES.get(platform, (None, None, "renders/final_reels_vi_9x16.mp4"))[2]
                            render_file = resolved_dir / rel_render
                            if not render_file.is_file():
                                return False, f"missing_render_file_for_archive_check_{render_file.name}", meta
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
    args = parser.parse_args()

    if args.reconcile:
        return _run_reconciliation(args.pid, args.date)

    eligible, reason, _ = is_project_eligible_for_cleanup(
        args.pid,
        project_dir=Path(args.dir) if args.dir else None,
        date=args.date,
    )
    if eligible:
        print(f"ELIGIBLE: {args.pid} ({reason})")
        return 0
    else:
        print(f"NOT_ELIGIBLE: {args.pid} ({reason})")
        return 1


def _run_reconciliation(project_id: str, date: str | None) -> int:
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

    routes = get_required_routes_for_project(project_id)
    if not routes:
        print(f"RECONCILE_SKIP: no required routes identified for {project_id}")
        return 0

    pub_date = date or _infer_publish_date(store, project_id)
    if not pub_date:
        print(f"RECONCILE_SKIP: no publish date resolvable for {project_id}")
        return 0

    updated = reconcile_project_publications(store, project_id, pub_date, routes)
    if updated:
        for rec in updated:
            print(
                f"RECONCILED: {rec.get('key') or rec.get('platform_id') or rec.get('video_id')} "
                f"-> published (verified_at={rec.get('verified_at')})"
            )
    else:
        print(f"RECONCILE_NO_CHANGE: {project_id} on {pub_date} (no scheduled record promoted; safe to retry)")
    return 0


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
