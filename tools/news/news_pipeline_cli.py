"""CLI entrypoint for the NewsNow to OpenMontage pipeline."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from lib.checkpoint import init_project, write_checkpoint
from lib.claude_news_selector import ClaudeNewsSelector
from lib.news_research_bridge import NewsResearchBridge
from lib.news_scoring import NewsCandidateScorer
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
    init_project(project_id, title=research_brief["topic"], pipeline_type="animated-explainer")

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

    logger.info("Scoring and ranking...")
    scorer = NewsCandidateScorer()
    ranked = scorer.rank_candidates(candidates, limit=max(10, count * 3))

    if not ranked:
        logger.error("No valid candidates found.")
        sys.exit(1)

    if len(ranked) < count:
        logger.error(f"Need {count} distinct candidates but only {len(ranked)} available.")
        sys.exit(1)

    if args.dry_run:
        logger.info("[DRY RUN] Skipping Claude CLI and checkpoint generation.")
        print(json.dumps(ranked[:count], indent=2))
        return

    logger.info("Running bounded Claude selection...")
    selector = ClaudeNewsSelector()

    project_ids: List[str] = []
    used_ids: set[str] = set()
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
                "Claude returned invalid candidate-bound research; retrying selection "
                f"(attempt {attempts}/{max_attempts})."
            )
            continue

        selected_id = selection["selected_candidate_id"]
        if selected_id in used_ids:
            logger.warning(f"Claude selected duplicate candidate {selected_id}; retrying selection.")
            continue

        candidate = next(c for c in pool if c["candidate_id"] == selected_id)
        used_ids.add(selected_id)

        logger.info(f"Selected candidate: {selected_id} ({candidate['title']})")
        logger.info(f"Rationale: {selection.get('selection_rationale')}")

        logger.info("Bridging to research artifact...")
        try:
            project_id = _init_candidate_project(candidate, selection)
        except Exception as e:
            logger.error(f"Failed to initialize project: {e}")
            sys.exit(1)
        project_ids.append(project_id)

    if len(project_ids) != count:
        logger.error(
            f"Initialized {len(project_ids)} of {count} requested project(s) after "
            f"{attempts} selection attempts."
        )
        sys.exit(1)

    for pid in project_ids:
        print(f"PROJECT_ID={pid}")
    logger.info(f"Initialized {len(project_ids)} project(s). Research stage completed.")



def main() -> None:
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

    args = parser.parse_args()

    if args.command == "ingest":
        run_ingest(args)
    elif args.command == "produce":
        run_produce(args)
    elif args.command == "fetch":
        run_fetch(args)


if __name__ == "__main__":
    main()
