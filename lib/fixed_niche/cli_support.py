"""CLI argument parsing and candidate resolution support for Fixed Niche Video Runner.

Extracts CLI input validation and candidate loading to preserve Clean Architecture
module ceilings (< 450 lines).
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from lib.fixed_niche.gate import FixedNicheScopeGate
from tools.news.fixed_niche_sources import FixedNicheSourceAdapter

logger = logging.getLogger(__name__)


def configure_cli_environment(args: argparse.Namespace) -> None:
    """Set global environment variables based on CLI flags."""
    os.environ["AI_VISUAL_ENABLED"] = "1" if getattr(args, "enable_ai_visuals", False) else "0"
    os.environ["OPENMONTAGE_VISUAL_STYLE"] = getattr(args, "visual_style", "progressive_svg")
    diag_active = getattr(args, "visual_style", "") == "animated_agent_diagram_v1" and getattr(args, "enable_diagram_animation", True)
    os.environ["ANIMATED_AGENT_DIAGRAM_V1_ENABLED"] = "1" if diag_active else "0"


def validate_safe_path(path: Path | str, root_dir: Path) -> Path:
    """Validate path against traversal attacks (CWE-22 / CWE-73)."""
    p = Path(path).expanduser().resolve()
    allowed = (root_dir.resolve(), Path.home().resolve(), Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve())
    if not any(p.is_relative_to(root) for root in allowed if root != Path(root.anchor)):
        raise ValueError(f"Path traversal detected or path outside allowed root: {path}")
    if not p.is_file():
        raise FileNotFoundError(f"Candidate file does not exist: {path}")
    if p.is_relative_to(Path(tempfile.gettempdir()).resolve()) and hasattr(os, "getuid") and p.stat().st_uid != os.getuid():
        raise PermissionError(f"Candidate file in temp directory must be owned by current user: {path}")
    return p


def load_yaml_candidates(file_path: Path) -> List[Dict[str, Any]]:
    """Safely load candidate dictionaries from a YAML file."""
    try:
        import yaml
        raw_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            return raw_data.get("positive_cases", [])
        return raw_data if isinstance(raw_data, list) else []
    except Exception as e:
        logger.warning("Failed to load candidates from %s: %s", file_path, e)
        return []


def load_cli_candidates_pool(args: argparse.Namespace, root_dir: Path) -> List[Dict[str, Any]]:
    """Load candidates from specified file, test fixtures, or production source adapter."""
    if getattr(args, "candidates_file", None):
        candidates = load_yaml_candidates(validate_safe_path(args.candidates_file, root_dir))
        if not candidates:
            raise ValueError(f"No candidates could be loaded from specified --candidates-file: {args.candidates_file}")
        return candidates
    if getattr(args, "use_test_fixtures", False):
        candidates = load_yaml_candidates(validate_safe_path(root_dir / "tests/fixtures/fixed_niche_cases.yaml", root_dir))
        if not candidates:
            raise ValueError("No candidates could be loaded from test fixtures")
        return candidates
    return FixedNicheSourceAdapter().discover_production_candidates()


def apply_topic_overrides(topic: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """Apply explicit CLI argument overrides to topic metadata."""
    res = dict(topic)
    res.update({k: getattr(args, k) for k in ("title", "topic_family", "canonical_url") if getattr(args, k, None)})
    return res


def auto_select_topic(
    candidates_pool: List[Dict[str, Any]], gate: FixedNicheScopeGate, args: argparse.Namespace
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Auto-select the highest ranked eligible candidate from pool."""
    eligible = [c for c in candidates_pool if gate.evaluate_candidate(c).is_eligible]
    if not eligible:
        return None, None
    from lib.fixed_niche.ranker import FixedNicheTopicScorer
    ranked = FixedNicheTopicScorer().rank_candidates([(c, gate.evaluate_candidate(c)) for c in eligible])
    top_cand = ranked[0] if ranked else eligible[0]
    cid = top_cand.get("id") or top_cand.get("candidate_id") or "cand_selected"
    topic = apply_topic_overrides(top_cand, args)
    topic["candidate_id"] = cid
    return cid, topic


def resolve_cli_topic_and_candidate(
    args: argparse.Namespace, candidates_pool: List[Dict[str, Any]], gate: FixedNicheScopeGate
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve target candidate ID and topic dictionary according to auto-select/explicit args."""
    cid = getattr(args, "candidate_id", None)
    if cid:
        matched = next((c for c in candidates_pool if c.get("candidate_id") == cid or c.get("id") == cid), None)
        if matched:
            t = apply_topic_overrides(matched, args)
            t["candidate_id"] = cid
            return cid, t
    if getattr(args, "auto_select", False) or not cid:
        return auto_select_topic(candidates_pool, gate, args)
    fallback = apply_topic_overrides({
        "candidate_id": cid, "title": "Why coding agents lose project requirements between sessions",
        "topic_family": "context_memory", "canonical_url": "https://docs.anthropic.com/claude/context-window",
    }, args)
    fallback["candidate_id"] = cid
    return cid, fallback


def build_cli_parser() -> argparse.ArgumentParser:
    """Build production CLI argument parser for Fixed Niche explainer video generation."""
    parser = argparse.ArgumentParser(description="Fixed Niche Video Production CLI")
    parser.add_argument("--candidate-id", default=None, help="Candidate ID to produce")
    parser.add_argument("--auto-select", action="store_true", default=False, help="Auto-discover in-scope candidate")
    parser.add_argument("--candidates-file", default=None, help="Path to YAML/JSON candidates pool file")
    parser.add_argument("--use-test-fixtures", action="store_true", default=False, help="Allow loading test fixtures")
    parser.add_argument("--renderer", choices=["auto", "hyperframes", "ffmpeg"], default="auto", help="Renderer")
    parser.add_argument("--project-dir", help="Custom project output directory")
    parser.add_argument("--format", default="short", choices=["short", "shorts"], help="Video format")
    for flag in ("--title", "--topic-family", "--canonical-url", "--provider", "--voice"):
        parser.add_argument(flag, default=None)
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--dry-run", action="store_true", help="Stage project without media rendering")
    parser.add_argument("--burn-captions", action="store_true", default=False, help="Burn subtitles into video")
    parser.add_argument("--enable-ai-visuals", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--visual-style",
        default=os.environ.get("OPENMONTAGE_VISUAL_STYLE", "progressive_svg"),
        choices=["progressive_svg", "animated_agent_diagram_v1", "legacy"],
    )
    parser.add_argument("--enable-diagram-animation", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-latest-news", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-age-days", type=int, default=7)
    return parser
