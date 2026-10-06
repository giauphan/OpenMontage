"""Independent published-candidate cleanup; inspection is read-only by default."""

from __future__ import annotations

import argparse
import json
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


def sweep(*, apply: bool = False, store=None) -> int:
    """Delegate every mutation to the existing locked reconciliation/delete boundary."""
    # Read inventory before constructing the store; malformed queue fails closed.
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
    mode.add_argument("--apply", action="store_true", help="Reconcile and remove only verified published projects")
    mode.add_argument("--dry-run", action="store_true", help="Read-only inspection (default; no reconciliation)")
    args = parser.parse_args(argv)
    try:
        return sweep(apply=args.apply)
    except Exception as exc:
        print(f"ERROR: sweep blocked ({type(exc).__name__}); no further cleanup attempted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
