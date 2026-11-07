from __future__ import annotations

import fcntl
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = DEFAULT_ROOT / "config" / "publish_schedule.json"


def _pap():
    import scripts.publish_active_projects as pap
    return pap


def write_audit_tombstone(
    project_id: str,
    project_dir: Path,
    *,
    date: str | None = None,
    status: str = "cleanup_completed",
    store=None,
    media_hashes: dict[str, str] | None = None,
    error: str | None = None,
) -> bool:
    """Write minimal audit record to logs/published_archive.jsonl before/after directory removal.
    
    Returns True on success, False on failure. Uses file locking to serialize appends.
    """
    try:
        root = getattr(_pap(), "ROOT", DEFAULT_ROOT)
        archive_file = root / "logs" / "published_archive.jsonl"
        archive_file.parent.mkdir(parents=True, exist_ok=True)

        platform_records = {}
        if store is not None and date:
            from tools.publish_store import publish_key
            for plat, kind in [("youtube", "short"), ("instagram", "reels"), ("facebook", "reels")]:
                rec = store.get(publish_key(date, project_id, plat, kind))
                if rec:
                    platform_records[f"{plat}/{kind}"] = {
                        "status": rec.get("status"),
                        "video_id": rec.get("video_id") or rec.get("platform_id"),
                        "video_url": rec.get("video_url"),
                    }

        hashes = dict(media_hashes) if media_hashes else {}
        if not hashes and project_dir.is_dir():
            from tools.publish_store import file_sha256
            for render_name in ["final_short_en_US_9x16.mp4", "final_long_en_US_16x9.mp4", "final_reels_vi_9x16.mp4", "final_full_vi_9x16.mp4"]:
                rf = project_dir / "renders" / render_name
                if rf.is_file():
                    hashes[render_name] = file_sha256(rf)

        tombstone = {
            "project_id": project_id,
            "date": date or datetime.now(timezone.utc).date().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "resolved_path": str(project_dir),
            "platform_records": platform_records,
            "media_hashes": hashes,
            "cleanup_state": status,
        }
        if error:
            tombstone["error"] = error

        line = json.dumps(tombstone, ensure_ascii=False) + "\n"
        lock_file = archive_file.with_suffix(".lock")
        with open(lock_file, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                with open(archive_file, "a", encoding="utf-8") as f:
                    f.write(line)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        return True
    except Exception as exc:
        print(f"ERROR: Failed to write audit tombstone for {project_id}: {exc}", file=sys.stderr)
        return False


def deactivate_project(
    project_id: str,
    *,
    project_dir: Path | str | None = None,
    store=None,
    date: str | None = None,
    instagram_mode: bool = False,
    held_platforms: set[str] | list[str] | str | None = None,
    enabled_platforms: set[str] | list[str] | str | None = None,
) -> bool:
    """Safely deactivate published project from schedule and delete its media directory."""
    pap = _pap()
    root = getattr(pap, "ROOT", DEFAULT_ROOT)
    config = getattr(pap, "CONFIG", DEFAULT_CONFIG)
    locked_schedule = getattr(pap, "locked_schedule")
    tombstone_writer = getattr(pap, "write_audit_tombstone", write_audit_tombstone)

    projects_root = (root / "projects").resolve()
    projects_news_root = (root / "projects_news").resolve()
    ig_parent = (projects_root / "instagram").resolve()
    authorized_roots = (projects_root, projects_news_root, ig_parent)

    # Pre-resolution symlink checks on input path (R5)
    if project_dir is not None:
        cand_input = Path(project_dir)
        if cand_input.is_symlink():
            print(f"❌ Safety check failed: Refusing to delete symlink: {cand_input}", file=sys.stderr)
            return False
        for parent in cand_input.parents:
            if parent.is_symlink():
                print(f"❌ Safety check failed: Refusing to delete path through symlink ancestor: {parent}", file=sys.stderr)
                return False

    # Detect duplicate project directories across locations (R5)
    found_dirs = []
    for cand in [
        projects_root / project_id,
        projects_news_root / project_id,
        ig_parent / project_id,
    ]:
        if cand.is_dir():
            found_dirs.append(cand.resolve())

    # R5: Reject duplicate project locations even when an explicit path is supplied
    if len(found_dirs) > 1:
        print(f"❌ Safety check failed: duplicate project directories found for {project_id}: {found_dirs}", file=sys.stderr)
        return False

    resolved_dir: Path | None = None
    if project_dir is not None:
        resolved_dir = Path(project_dir).resolve()
    elif found_dirs:
        resolved_dir = found_dirs[0]
    else:
        resolved_dir = (projects_root / project_id).resolve()

    if resolved_dir.name != project_id:
        print(f"❌ Safety check failed: Target folder name {resolved_dir.name} does not match {project_id}", file=sys.stderr)
        return False

    is_contained = False
    for auth_root in authorized_roots:
        try:
            rel = resolved_dir.relative_to(auth_root)
            if rel.parts and rel.parts[0] == project_id and len(rel.parts) == 1:
                is_contained = True
                parent_dir = auth_root
                break
        except ValueError:
            pass

    if not is_contained:
        print(f"❌ Safety check failed: Target {resolved_dir} is not an authorized project directory", file=sys.stderr)
        return False

    # Validate metadata identity if publish_metadata.json exists
    meta_path = resolved_dir / "publish_metadata.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_id = meta.get("id") or meta.get("project_id")
            if meta_id and meta_id != project_id:
                print(f"❌ Safety check failed: Metadata ID {meta_id} does not match {project_id}", file=sys.stderr)
                return False
        except Exception:
            pass

    # Protected finalization boundary (R4)
    with locked_schedule(config):
        # 1. Reconcile any scheduled publications if store is available (R1/R2 explicit mutation)
        pub_date = date
        if not pub_date and meta_path.is_file():
            try:
                m = json.loads(meta_path.read_text(encoding="utf-8"))
                pub_date = m.get("publish_date") or m.get("date")
            except Exception:
                pass

        if store is not None and pub_date:
            from scripts.publish_manual_video import get_required_routes_for_project
            from scripts.check_cleanup_eligibility import reconcile_project_publications
            req_routes = get_required_routes_for_project(
                project_id,
                project_dir=resolved_dir if resolved_dir.is_dir() else None,
                held_platforms=held_platforms,
                enabled_platforms=enabled_platforms,
            )
            if req_routes:
                reconcile_project_publications(store, project_id, pub_date, req_routes)

        # 2. Check verified publication eligibility inside protected boundary (R1, R2, R3, R4)
        from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
        eligible, reason, _ = is_project_eligible_for_cleanup(
            project_id,
            project_dir=resolved_dir if resolved_dir.exists() else None,
            store=store,
            date=pub_date,
            config_path=config,
            root=root,
            held_platforms=held_platforms,
            enabled_platforms=enabled_platforms,
        )
        if not eligible:
            print(f"Project retained: {reason} for {project_id}")
            return False

        # 3. Compute hashes and write audit tombstone before deleting
        media_hashes = {}
        if resolved_dir.is_dir():
            from tools.publish_store import file_sha256
            for render_name in ["final_short_en_US_9x16.mp4", "final_long_en_US_16x9.mp4", "final_reels_vi_9x16.mp4", "final_full_vi_9x16.mp4"]:
                rf = resolved_dir / "renders" / render_name
                if rf.is_file():
                    media_hashes[render_name] = file_sha256(rf)

            # R4: Audit failure MUST block deletion
            if not tombstone_writer(
                project_id,
                resolved_dir,
                date=pub_date,
                status="cleanup_pending",
                store=store,
                media_hashes=media_hashes,
            ):
                print(f"❌ Failed to persist audit tombstone for {project_id}; aborting cleanup to preserve audit trail", file=sys.stderr)
                return False

            try:
                shutil.rmtree(resolved_dir)
                print(f"✓ Removed published project: {resolved_dir}")
            except OSError as exc:
                print(f"❌ Failed to remove project directory {resolved_dir}: {exc}", file=sys.stderr)
                tombstone_writer(
                    project_id,
                    resolved_dir,
                    date=pub_date,
                    status="cleanup_failed",
                    store=store,
                    media_hashes=media_hashes,
                    error=str(exc),
                )
                return False

            # R4: Surface failed completion-audit writes
            if not tombstone_writer(
                project_id,
                resolved_dir,
                date=pub_date,
                status="cleanup_completed",
                store=store,
                media_hashes=media_hashes,
            ):
                print(f"❌ Failed to persist completion audit tombstone for {project_id}", file=sys.stderr)
                return False

            if parent_dir == ig_parent and ig_parent.exists():
                try:
                    if not any(ig_parent.iterdir()):
                        ig_parent.rmdir()
                except OSError:
                    pass
        else:
            print(f"✓ Project directory already cleaned: {resolved_dir}")
            if not tombstone_writer(project_id, resolved_dir, date=pub_date, status="cleanup_completed", store=store):
                print(f"❌ Failed to persist completion audit tombstone for {project_id}", file=sys.stderr)
                return False

        # 4. Deactivate from active_projects queue inside lock
        if config.is_file():
            try:
                schedule = json.loads(config.read_text(encoding="utf-8"))
                active_projects = schedule.get("active_projects", [])
                if any((item.get("project_id") if isinstance(item, dict) else item) == project_id for item in active_projects):
                    schedule["active_projects"] = [
                        item for item in active_projects
                        if (item.get("project_id") if isinstance(item, dict) else item) != project_id
                    ]
                    temp_config = config.with_suffix(".json.tmp")
                    temp_config.write_text(
                        json.dumps(schedule, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    temp_config.replace(config)
                    print(f"✓ Deactivated published project: {project_id}")
            except Exception as exc:
                print(f"❌ Failed to update schedule queue for {project_id}: {exc}", file=sys.stderr)
                return False

        return True
