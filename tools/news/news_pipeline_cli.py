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


def run_produce(args: argparse.Namespace) -> None:
    """Full pipeline: ingest -> score -> LLM select -> research brief -> checkpoint."""
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
    ranked = scorer.rank_candidates(candidates, limit=10)

    if not ranked:
        logger.error("No valid candidates found.")
        sys.exit(1)

    if args.dry_run:
        logger.info("[DRY RUN] Skipping Claude CLI and checkpoint generation.")
        print(json.dumps(ranked[:1], indent=2))
        return

    logger.info("Running bounded Claude selection...")
    selector = ClaudeNewsSelector()
    selection = selector.select_and_research(ranked)

    if not selection:
        logger.error("Claude selection failed or returned invalid data.")
        sys.exit(1)

    selected_id = selection["selected_candidate_id"]
    candidate = next(c for c in ranked if c["candidate_id"] == selected_id)

    logger.info(f"Selected candidate: {selected_id} ({candidate['title']})")
    logger.info(f"Rationale: {selection.get('selection_rationale')}")

    logger.info("Bridging to research artifact...")
    bridge = NewsResearchBridge()
    try:
        research_brief = bridge.build_brief(candidate, selection)
    except Exception as e:
        logger.error(f"Failed to bridge research artifact: {e}")
        sys.exit(1)

    logger.info("Initializing OpenMontage project...")
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
        human_approval_required=False
    )

    logger.info(f"Project initialized: projects/{project_id}")
    logger.info("Research stage completed. Proposal work has not started.")


def main() -> None:
    parser = argparse.ArgumentParser(description="NewsNow to OpenMontage CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest and rank raw feed JSON")
    ingest_parser.add_argument("--input", required=True, help="Path to raw JSON list")
    ingest_parser.add_argument("--output", required=True, help="Path to save ranked candidates")
    ingest_parser.add_argument("--limit", type=int, default=50, help="Max candidates to output")

    produce_parser = subparsers.add_parser("produce", help="Run full ingestion -> selection -> project initialization")
    produce_parser.add_argument("--input", required=True, help="Path to raw JSON list")
    produce_parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls and project creation")

    args = parser.parse_args()

    if args.command == "ingest":
        run_ingest(args)
    elif args.command == "produce":
        run_produce(args)


if __name__ == "__main__":
    main()
