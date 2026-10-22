"""CLI entrypoint for the NewsNow to OpenMontage pipeline."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from lib.checkpoint import init_project, write_checkpoint
from lib.codex_news_selector import CodexNewsSelector as NewsSelector
from lib.news_research_bridge import NewsResearchBridge
from lib.news_scoring import NewsCandidateScorer
from lib.news_claim_review import (
    ReviewWorksheetError,
    ReviewWorksheetPersistenceError,
    prepare_claim_review,
)
from lib.news_source_capture import CaptureError, CapturePersistenceError, capture_source
from tools.news.newsnow_adapter import NewsNowAdapter
from tools.news.newsnow_feed import write_feed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_ingest(args: argparse.Namespace) -> None:
    """Ingest, normalize, and score raw news."""
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    with input_path.open("r", encoding="utf-8") as f:
        raw_items = json.load(f)

    if not isinstance(raw_items, list):
        logger.error("Input must be a JSON array of raw items.")
        sys.exit(1)

    adapter = NewsNowAdapter()
    candidates, diagnostics = adapter.ingest_and_normalize(raw_items)
    logger.info(f"Normalized {len(candidates)} candidates from {len(raw_items)} raw items. Errors: {len(diagnostics)}")


    scorer = NewsCandidateScorer()
    ranked = scorer.rank_candidates(candidates, limit=args.limit)

    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(ranked, f, indent=2)

    logger.info(f"Wrote {len(ranked)} ranked candidates to {out_path}")


def _init_candidate_project(candidate: Dict[str, Any], selection: Dict[str, Any]) -> str:
    """Build research brief and initialize one OpenMontage project for a candidate."""
    bridge = NewsResearchBridge()
    research_brief = bridge.build_brief(candidate, selection)

    project_id = candidate["candidate_id"]
    pipeline_dir = Path("projects") / project_id
    init_project(
        project_id,
        title=research_brief["topic"],
        pipeline_type="animated-explainer",
        pipeline_dir=Path("projects"),
    )

    brief_path = pipeline_dir / "artifacts" / "research_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    with brief_path.open("w", encoding="utf-8") as f:
        json.dump(research_brief, f, indent=2)

    write_checkpoint(
        Path("projects"),
        project_id=project_id,
        stage="research",
        status="completed",
        artifacts={"research_brief": research_brief},
        human_approval_required=False,
    )
    logger.info(f"Project initialized: projects/{project_id}")
    return project_id


def run_fetch(args: argparse.Namespace) -> None:
    """Fetch NewsNow source feeds and write a raw feed file."""
    count = write_feed(args.url, Path(args.output), minimum=args.min_items)
    logger.info(f"Wrote {count} raw items to {args.output}")


def run_produce(args: argparse.Namespace) -> None:
    """Full pipeline: ingest -> score -> LLM select -> research brief -> checkpoint."""
    count = max(1, getattr(args, "count", 1))
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    with input_path.open("r", encoding="utf-8") as f:
        raw_items = json.load(f)

    logger.info("Ingesting and normalizing...")
    adapter = NewsNowAdapter()
    candidates, diagnostics = adapter.ingest_and_normalize(raw_items)
    if diagnostics:
        logger.warning(f"Encountered {len(diagnostics)} invalid items during ingestion.")

    used_ids: set[str] = set()

    # Pre-populate used_ids with already scheduled projects and completed validated/rendered projects
    sched_path = Path("config/publish_schedule.json")
    if sched_path.is_file():
        try:
            with sched_path.open("r", encoding="utf-8") as f:
                sched_data = json.load(f)
            for item in sched_data.get("active_projects", []):
                if isinstance(item, dict) and item.get("project_id"):
                    used_ids.add(item["project_id"])
        except Exception:
            pass

    for p_dir in (Path("projects"), Path("projects_news")):
        if p_dir.is_dir():
            for p in p_dir.iterdir():
                if p.is_dir():
                    has_video = (p / "renders").is_dir() and any((p / "renders").glob("*.mp4"))
                    if (p / "validation_status.json").is_file() or has_video:
                        used_ids.add(p.name)

    # Filter out already used candidates before ranking so we do not artificially truncate the usable pool
    available_candidates = [c for c in candidates if c.get("candidate_id") not in used_ids]
    candidate_pool = available_candidates if len(available_candidates) >= count else candidates

    logger.info("Scoring and ranking...")
    scorer = NewsCandidateScorer()
    ranked = scorer.rank_candidates(candidate_pool, limit=max(30, count * 4))

    min_required = min(count, int(os.environ.get("MIN_PRODUCE_COUNT", 3)))
    if not ranked:
        logger.error("No valid candidates found.")
        sys.exit(1)

    if len(ranked) < min_required:
        logger.error(f"Need at least {min_required} distinct candidates but only {len(ranked)} available.")
        sys.exit(1)

    if args.dry_run:
        logger.info("[DRY RUN] Skipping Codex CLI and checkpoint generation.")
        print(json.dumps(ranked[:count], indent=2))
        return

    logger.info("Running bounded Codex selection...")
    selector = NewsSelector()

    project_ids: List[str] = []

    max_attempts = max(count * 3, len(ranked))
    attempts = 0
    while len(project_ids) < count and attempts < max_attempts:
        pool = [c for c in ranked if c["candidate_id"] not in used_ids]
        if not pool:
            break
        attempts += 1
        selection = selector.select_and_research(pool)
        if not selection:
            logger.warning(
                "Codex returned invalid candidate-bound research; retrying selection "
                f"(attempt {attempts}/{max_attempts})."
            )
            continue

        if not isinstance(selection, dict):
            logger.warning(
                "Codex returned a non-object selection; retrying selection "
                f"(attempt {attempts}/{max_attempts})."
            )
            continue

        selected_id = selection.get("selected_candidate_id")
        if not isinstance(selected_id, str) or not selected_id:
            logger.warning(
                "Codex selection omitted selected_candidate_id; retrying selection "
                f"(attempt {attempts}/{max_attempts})."
            )
            continue
        if selected_id in used_ids:
            logger.warning(f"Codex selected duplicate candidate {selected_id}; retrying selection.")
            continue

        candidate = next((c for c in pool if c["candidate_id"] == selected_id), None)
        if candidate is None:
            logger.warning(
                "Codex selected candidate outside the current pool; retrying selection "
                f"(attempt {attempts}/{max_attempts})."
            )
            continue
        used_ids.add(selected_id)

        logger.info(f"Selected candidate: {selected_id} ({candidate['title']})")
        logger.info(f"Rationale: {selection.get('selection_rationale')}")

        logger.info("Bridging to research artifact...")
        try:
            project_id = _init_candidate_project(candidate, selection)
        except Exception as e:
            logger.warning(
                "Failed to initialize project for %s: %s; retrying selection "
                "(attempt %s/%s).",
                selected_id,
                e,
                attempts,
                max_attempts,
            )
            continue
        project_ids.append(project_id)

    min_required = min(count, int(os.environ.get("MIN_PRODUCE_COUNT", 3)))
    if len(project_ids) < min_required:
        logger.error(
            f"Initialized {len(project_ids)} of {count} requested project(s) (minimum {min_required} required) after "
            f"{attempts} selection attempts."
        )
        sys.exit(1)
    if len(project_ids) < count:
        logger.warning(
            f"Initialized {len(project_ids)} of {count} requested project(s) after "
            f"{attempts} selection attempts; proceeding with {len(project_ids)} projects."
        )

    for pid in project_ids:
        print(f"PROJECT_ID={pid}")
    logger.info(f"Initialized {len(project_ids)} project(s). Research stage completed.")



def run_capture_source(args: argparse.Namespace) -> int:
    """Capture one source for review without advancing the production pipeline."""
    project_dir = Path(args.project_dir)
    if project_dir.is_symlink() or not project_dir.is_dir():
        print("capture-source: --project-dir must be an existing directory", file=sys.stderr)
        return 1

    try:
        provenance = capture_source(project_dir, args.url, args.allowed_host)
    except CapturePersistenceError as exc:
        print(
            json.dumps({
                "status": "capture_persistence_failed",
                "error": str(exc),
                "partial_artifacts": exc.partial_artifacts,
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    except CaptureError as exc:
        # Do not echo the input URL: it may contain sensitive query parameters.
        print(f"capture-source failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(provenance, ensure_ascii=False, indent=2))
    return 0


def run_prepare_review(args: argparse.Namespace) -> int:
    """Build a hash-bound, review-pending worksheet from explicit revisions."""
    selected = []
    for item in args.capture:
        if "=" not in item:
            print("prepare-review: each --capture must be PROVENANCE_PATH=SHA256", file=sys.stderr)
            return 1
        path, digest = item.rsplit("=", 1)
        selected.append((path, digest))
    try:
        result = prepare_claim_review(args.project_dir, selected)
    except ReviewWorksheetPersistenceError as exc:
        print(
            json.dumps({
                "status": "worksheet_persistence_failed",
                "error": str(exc),
                "partial_artifacts": exc.partial_artifacts,
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    except ReviewWorksheetError as exc:
        print(f"prepare-review failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NewsNow to OpenMontage CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest and rank raw feed JSON")
    ingest_parser.add_argument("--input", required=True, help="Path to raw JSON list")
    ingest_parser.add_argument("--output", required=True, help="Path to save ranked candidates")
    ingest_parser.add_argument("--limit", type=int, default=50, help="Max candidates to output")

    produce_parser = subparsers.add_parser("produce", help="Run full ingestion -> selection -> project initialization")
    produce_parser.add_argument("--input", required=True, help="Path to raw JSON list")
    produce_parser.add_argument("--count", type=int, default=1, help="Number of distinct topics/projects to produce")
    produce_parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls and project creation")

    fetch_parser = subparsers.add_parser("fetch", help="Fetch NewsNow source feeds into a raw feed file")
    fetch_parser.add_argument("--url", required=True, help="NewsNow base URL, e.g. http://127.0.0.1:4444")
    fetch_parser.add_argument("--output", required=True, help="Path to write the raw feed JSON")
    fetch_parser.add_argument("--min-items", type=int, default=3, help="Minimum valid items required")

    capture_parser = subparsers.add_parser(
        "capture-source",
        help="Capture an allowlisted article as pending editorial-review provenance",
    )
    capture_parser.add_argument("--project-dir", required=True, help="Existing project directory")
    capture_parser.add_argument("--url", required=True, help="HTTPS source URL to capture")
    capture_parser.add_argument(
        "--allowed-host", action="append", required=True,
        help="Explicit allowed hostname (repeat for redirect/source hosts)",
    )

    review_parser = subparsers.add_parser(
        "prepare-review", help="Create a hash-bound pending claim-review worksheet"
    )
    review_parser.add_argument("--project-dir", required=True, help="Existing project directory")
    review_parser.add_argument(
        "--capture", action="append", required=True,
        help="Explicit provenance path=expected SHA-256 (repeat per capture revision)",
    )

    args = parser.parse_args(argv)

    if args.command == "ingest":
        run_ingest(args)
    elif args.command == "produce":
        run_produce(args)
    elif args.command == "fetch":
        run_fetch(args)
    elif args.command == "capture-source":
        return run_capture_source(args)
    elif args.command == "prepare-review":
        return run_prepare_review(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
