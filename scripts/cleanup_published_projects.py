"""Independent published-candidate cleanup; inspection is read-only by default."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import date
from pathlib import Path

from scripts import publish_active_projects as publisher
from scripts.check_cleanup_eligibility import is_project_eligible_for_cleanup
from tools.publish_store import PublishStore


def candidate_dates(root: Path):
    """Discover candidate directories, retaining missing or ambiguous release dates.

    PublishStore exposes keyed reads, not date enumeration. Do not guess dates
    from directory names, timestamps, or the current day.
    """
    config = root / "config" / "publish_schedule.json"
    schedule = json.loads(config.read_text()) if config.exists() else {}
    active = schedule.get("active_projects", [])
    if not isinstance(active, list):
        raise ValueError("active_projects must be a list")
    for location in ("projects", "projects_news", "projects/instagram"):
        for directory in sorted((root / location).glob("cand_*")):
            if not directory.is_dir():
                continue
            if directory.is_symlink() or any(p.is_symlink() for p in directory.parents):
                print(f"RETAINED: {directory.name}: unsafe symlink path")
                continue
            try:
                metadata_path = directory / "publish_metadata.json"
                if metadata_path.is_symlink():
                    raise ValueError("symlink metadata")
                metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
                dates = [metadata.get("publish_date"), metadata.get("date")]
                dates.extend(
                    item.get("publish_date") for item in active
                    if isinstance(item, dict) and item.get("project_id") == directory.name
                )
                dates = {value for value in dates if value is not None}
                if len(dates) != 1:
                    raise ValueError("missing or conflicting publish dates")
                publish_date = dates.pop()
                if not isinstance(publish_date, str) or date.fromisoformat(publish_date).isoformat() != publish_date:
                    raise ValueError("invalid publish date")
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                print(f"RETAINED: {directory.name}: {exc}")
                continue
            yield directory, publish_date


def clear_project_trash(root: Path, *, apply: bool = False, store=None, min_age_minutes: int = 120) -> int:
    """Clear failed generation recovery dirs and abandoned errored candidate trash.

    Safety requirements:
    1. Never touch directories modified within min_age_minutes (default 120m).
    2. Never delete active projects in publish_schedule.json.
    3. Never delete projects that have an active claim or scheduled/published record in PublishStore.
    4. Only delete:
       - Quarantined recovery dirs in projects/_failed_generation_recovered older than min_age_minutes.
       - Abandoned candidate directories that failed validation (strict_quality_pass=False) or have no valid publish date/renders.
    """
    removed_count = 0
    now_ts = time.time()
    min_age_seconds = min_age_minutes * 60

    # 1. Clean quarantined failed generations
    recovered_root = root / "projects" / "_failed_generation_recovered"
    if recovered_root.is_dir():
        for item in sorted(recovered_root.iterdir()):
            if not item.is_dir() or item.is_symlink():
                continue
            try:
                mtime = item.stat().st_mtime
                if now_ts - mtime >= min_age_seconds:
                    if apply:
                        shutil.rmtree(item)
                        print(f"REMOVED_TRASH: _failed_generation_recovered/{item.name}")
                    else:
                        print(f"DRY_RUN_TRASH: would remove _failed_generation_recovered/{item.name}")
                    removed_count += 1
            except Exception as e:
                print(f"ERROR: failed to inspect/remove trash {item.name}: {e}")

    # 2. Clean abandoned errored candidate projects
    config = root / "config" / "publish_schedule.json"
    active_ids = set()
    if config.exists():
        try:
            sched = json.loads(config.read_text(encoding="utf-8"))
            for entry in sched.get("active_projects", []):
                pid = entry.get("project_id") if isinstance(entry, dict) else entry
                if pid:
                    active_ids.add(str(pid))
        except Exception:
            pass

    for location in ("projects", "projects_news"):
        loc_dir = root / location
        if not loc_dir.is_dir():
            continue
        for directory in sorted(loc_dir.glob("cand_*")):
            if not directory.is_dir() or directory.is_symlink():
                continue
            pid = directory.name
            if pid in active_ids:
                continue

            try:
                mtime = directory.stat().st_mtime
                if now_ts - mtime < min_age_seconds:
                    # Modified recently; protect in-flight generation
                    continue

                # Check if project has an active claim or scheduled record in PublishStore
                if store is not None and hasattr(store, "get"):
                    meta_file = directory / "publish_metadata.json"
                    if meta_file.is_file():
                        try:
                            meta = json.loads(meta_file.read_text(encoding="utf-8"))
                            pdate = meta.get("publish_date") or meta.get("date")
                            if pdate:
                                from tools.publish_store import publish_key
                                yt_rec = store.get(publish_key(pdate, pid, "youtube", "short"))
                                if yt_rec and yt_rec.get("status") in ("scheduled", "published"):
                                    continue
                        except Exception:
                            pass

                # Verify if this is an errored/incomplete project
                vstatus_file = directory / "validation_status.json"
                is_failed_validation = False
                if vstatus_file.is_file():
                    try:
                        v_data = json.loads(vstatus_file.read_text(encoding="utf-8"))
                        last = v_data[-1] if isinstance(v_data, list) and v_data else v_data
                        if isinstance(last, dict) and (last.get("status") != "PASS" or not last.get("strict_quality_pass")):
                            is_failed_validation = True
                    except Exception:
                        is_failed_validation = True

                has_renders = (directory / "renders" / "final_reels_vi_9x16.mp4").is_file()
                has_meta = (directory / "publish_metadata.json").is_file()

                # If validation failed, or if it has no metadata and no renders (abandoned early research)
                if is_failed_validation or (not has_meta and not has_renders):
                    if apply:
                        shutil.rmtree(directory)
                        print(f"REMOVED_TRASH: {location}/{pid} (errored/abandoned project)")
                    else:
                        print(f"DRY_RUN_TRASH: would remove {location}/{pid} (errored/abandoned project)")
                    removed_count += 1
            except Exception as e:
                print(f"ERROR: inspecting candidate {pid}: {e}")

    return removed_count


def sweep(*, apply: bool = False, store=None, clear_trash: bool = True) -> int:
    """Delegate every mutation to the existing locked reconciliation/delete boundary."""
    # 1. Clean trash (errored and quarantined recovery)
    if clear_trash:
        clear_project_trash(publisher.ROOT, apply=apply, store=store)

    # 2. Reconcile and clean published projects
    candidates = list(candidate_dates(publisher.ROOT))
    if not candidates:
        print("No dated candidate directories found")
        return 0
    if store is None:
        store = PublishStore()  # Never silently fall back to audit-only cleanup.
    errors = 0
    for directory, publish_date in candidates:
        try:
            if apply:
                # Do NOT prefilter eligibility: scheduled records need reconciliation.
                # The boundary rechecks paths, all routes and hashes under the lock,
                # writes the audit before deletion, and removes the queue entry last.
                removed = publisher.deactivate_project(
                    directory.name, project_dir=directory, store=store, date=publish_date,
                )
                state = "REMOVED" if removed else "RETAINED"
                print(f"{state}: {directory.name}")
            else:
                eligible, reason, _ = is_project_eligible_for_cleanup(
                    directory.name, project_dir=directory, store=store,
                    date=publish_date, config_path=publisher.CONFIG, root=publisher.ROOT,
                )
                print(f"DRY_RUN: {directory.name}: eligible={eligible}: {reason}")
        except Exception as exc:
            # Provider exceptions may contain credential-bearing URLs.
            print(f"ERROR: {directory.name}: {type(exc).__name__}; cleanup not completed")
            errors += 1
    return 1 if errors else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Reconcile and remove only verified published projects and trash")
    mode.add_argument("--dry-run", action="store_true", help="Read-only inspection (default; no reconciliation)")
    mode.add_argument("--clear-trash-only", action="store_true", help="Only clear errored projects and failed generation trash")
    args = parser.parse_args(argv)
    try:
        if args.clear_trash_only:
            count = clear_project_trash(publisher.ROOT, apply=True)
            print(f"Cleared {count} trash items")
            return 0
        return sweep(apply=args.apply)
    except Exception as exc:
        print(f"ERROR: sweep blocked ({type(exc).__name__}); no further cleanup attempted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
