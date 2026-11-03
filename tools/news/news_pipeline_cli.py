"""CLI entrypoint for the Gateway Daily News to OpenMontage pipeline."""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
from tools.news.daily_news_gateway import DailyNewsGatewayClient
from tools.news.gateway_daily_news_feed import write_feed

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
    if "content_hash" not in candidate:
        import hashlib
        body = candidate.get("body") or candidate.get("summary") or ""
        url = candidate.get("canonical_url") or candidate.get("url") or ""
        title = candidate.get("title") or ""
        candidate["content_hash"] = hashlib.sha256(
            f"{title.strip().lower()}|{url.strip().lower()}|{body[:500].strip().lower()}".encode("utf-8")
        ).hexdigest()
    if "raw_provenance" not in candidate:
        candidate["raw_provenance"] = {"source_id": candidate.get("candidate_id", ""), "source_feed": "fixed_niche"}

    bridge = NewsResearchBridge()
    research_brief = bridge.build_brief(candidate, selection)

    project_id = candidate["candidate_id"]
    pipeline_dir = Path("projects") / project_id
    cand_locale = (
        candidate.get("locale")
        or selection.get("locale")
        or os.environ.get("PROJECT_LOCALE")
        or os.environ.get("OPENMONTAGE_LOCALE")
        or "en-US"
    )
    cand_audience = (
        candidate.get("audience")
        or selection.get("audience")
        or os.environ.get("AUDIENCE_PROFILE")
        or ("us" if cand_locale == "en-US" else "vi")
    )
    init_project(
        project_id,
        title=research_brief["topic"],
        pipeline_type="animated-explainer",
        pipeline_dir=Path("projects"),
        locale=cand_locale,
        audience=cand_audience,
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
    logger.info("Project initialized: projects/%s", _sanitize_log_val(project_id))
    return project_id


def _sanitize_log_val(val: Any) -> str:
    """Sanitize strings before logging to prevent log injection (CWE-117)."""
    clean = str(val).replace("\r", " ").replace("\n", " ").strip()
    return clean[:120]


def _validate_safe_input_path(path: Path | str) -> Path:
    """Validate path against traversal attacks (CWE-22 / CWE-73)."""
    import tempfile
    p = Path(path).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    home_dir = Path.home().resolve()
    cwd_dir = Path.cwd().resolve()
    tmp_dir = Path(tempfile.gettempdir()).resolve()
    is_in_repo = p.is_relative_to(repo_root)
    is_in_home = p.is_relative_to(home_dir)
    is_in_cwd = cwd_dir != Path(cwd_dir.anchor) and p.is_relative_to(cwd_dir)
    is_in_tmp = p.is_relative_to(tmp_dir)
    if not (is_in_repo or is_in_home or is_in_cwd or is_in_tmp):
        logger.error("Path traversal detected or path outside allowed root: %s", _sanitize_log_val(path))
        sys.exit(1)
    if not p.is_file():
        logger.error("Input file not found: %s", _sanitize_log_val(path))
        sys.exit(1)
    if is_in_tmp and hasattr(os, "getuid") and p.stat().st_uid != os.getuid():
        logger.error("Input file in temp directory must be owned by current user: %s", _sanitize_log_val(path))
        sys.exit(1)
    return p


def run_fetch(args: argparse.Namespace) -> None:
    """Fetch discovery leads and write the established raw feed format."""
    gw_url = getattr(args, "url", None)
    if getattr(args, "source", "daily-news") == "muse":
        from tools.news.daily_news_gateway import DailyNewsGatewayClient
        from tools.news.muse_chat import MuseChatClient
        from tools.news.muse_news import discover_news

        origin = gw_url or os.environ.get("MUSE_GATEWAY_URL") or os.environ.get("TOOLCASE_GATEWAY_URL", "http://127.0.0.1:20129")
        state_path = Path(os.environ.get("MUSE_THREAD_CACHE", "data/muse_thread_cache.json"))
        age = float(os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS", "24"))
        items = discover_news(MuseChatClient(origin, state_path), age)
        count = DailyNewsGatewayClient().write_feed(output=Path(args.output), minimum=args.min_items, items=items)
    else:
        count = write_feed(gw_url, Path(args.output), minimum=args.min_items)
    logger.info(f"Wrote {count} raw items to {args.output}")


def _collect_scheduled_ids() -> Set[str]:
    sched_path = Path("config/publish_schedule.json")
    if not sched_path.is_file():
        return set()
    try:
        with sched_path.open("r", encoding="utf-8") as f:
            sched_data = json.load(f)
        return {
            item["project_id"]
            for item in sched_data.get("active_projects", [])
            if isinstance(item, dict) and item.get("project_id")
        }
    except Exception:
        return set()


def _is_completed_project_dir(p: Path) -> bool:
    if not p.is_dir():
        return False
    if (p / "validation_status.json").is_file():
        return True
    renders = p / "renders"
    return renders.is_dir() and any(renders.glob("*.mp4"))


def _collect_directory_project_ids(p_dir: Path) -> Set[str]:
    if not p_dir.is_dir():
        return set()
    return {p.name for p in p_dir.iterdir() if _is_completed_project_dir(p)}


def _collect_used_project_ids() -> Set[str]:
    """Collect project IDs that are already scheduled or completed."""
    used_ids = _collect_scheduled_ids()
    for p_dir in (Path("projects"), Path("projects_news")):
        used_ids.update(_collect_directory_project_ids(p_dir))
    history = Path("data/muse_consumed")
    if history.is_dir() and not history.is_symlink():
        used_ids.update(p.name for p in history.iterdir() if re.fullmatch(r"cand_[0-9a-f]{16}", p.name) and p.is_file() and not p.is_symlink())
    return used_ids


def _mark_muse_used(candidate_id: str) -> None:
    if not re.fullmatch(r"cand_[0-9a-f]{16}", candidate_id):
        raise ValueError("Invalid Muse candidate ID")
    history = Path("data/muse_consumed")
    history.mkdir(parents=True, exist_ok=True)
    if history.is_symlink() or not history.is_dir():
        raise ValueError("Invalid Muse history directory")
    marker = history / candidate_id
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("Invalid Muse history marker")
        return
    os.close(fd)


def _record_no_eligible_marker() -> None:
    marker_file = Path("data/.no_eligible_topic_marker")
    try:
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    except OSError:
        pass


def _clear_no_eligible_marker() -> None:
    marker_file = Path("data/.no_eligible_topic_marker")
    if marker_file.is_file():
        try:
            marker_file.unlink()
        except OSError:
            pass


def _filter_by_scope_gate(
    candidate_pool: List[Dict[str, Any]],
    fail_closed: bool = True,
) -> List[Dict[str, Any]]:
    """Enforce fixed niche scope gating unless explicitly skipped."""
    should_enforce_niche = os.environ.get("SKIP_SCOPE_GATE", "0") not in ("1", "true", "True")
    if not should_enforce_niche:
        return candidate_pool

    from lib.fixed_niche.gate import FixedNicheScopeGate
    gate = FixedNicheScopeGate()
    niche_filtered: List[Dict[str, Any]] = []
    for cand in candidate_pool:
        verdict = gate.evaluate_candidate(cand)
        if verdict.is_eligible:
            cand["topic_family"] = verdict.topic_family
            niche_filtered.append(cand)
        else:
            logger.info("FixedNicheScopeGate rejected candidate '%s': %s", cand.get("candidate_id"), verdict.reason)

    if not niche_filtered and fail_closed:
        logger.info("STATUS=NO_ELIGIBLE_TOPIC: No candidates passed FixedNicheScopeGate.")
        print("STATUS=NO_ELIGIBLE_TOPIC")
        _record_no_eligible_marker()
        sys.exit(2)

    if niche_filtered:
        _clear_no_eligible_marker()
    return niche_filtered


def _ingest_and_filter_candidates(
    input_path: Path,
    count: int,
    used_ids: Set[str],
    fail_closed: bool = True,
    freshness_window_hours: float = 48.0,
) -> List[Dict[str, Any]]:
    """Ingest candidates from input file and apply initial filtering."""
    safe_path = _validate_safe_input_path(input_path)
    if not safe_path.is_file():
        logger.error("Input file not found: %s", _sanitize_log_val(safe_path))
        sys.exit(1)

    with safe_path.open("r", encoding="utf-8") as f:
        raw_items = json.load(f)

    return _normalize_and_filter_candidates(
        raw_items,
        count,
        used_ids,
        fail_closed=fail_closed,
        freshness_window_hours=freshness_window_hours,
    )


def _normalize_and_filter_candidates(
    raw_items: List[Dict[str, Any]],
    count: int,
    used_ids: Set[str],
    fail_closed: bool = True,
    freshness_window_hours: float = 48.0,
) -> List[Dict[str, Any]]:
    """Normalize in-memory raw items and apply the production scope gate."""
    logger.info("Ingesting and normalizing...")
    adapter = NewsNowAdapter(freshness_window_hours=freshness_window_hours)
    candidates, diagnostics = adapter.ingest_and_normalize(raw_items)
    if diagnostics:
        logger.warning(f"Encountered {len(diagnostics)} invalid items during ingestion.")

    available = [c for c in candidates if c.get("candidate_id") not in used_ids]
    return _filter_by_scope_gate(available, fail_closed=fail_closed)


def _gateway_candidate_to_raw_item(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt a Gateway discovery candidate to the strict raw-news input contract."""
    raw: Dict[str, Any] = {
        "id": str(candidate.get("id") or candidate.get("candidate_id") or "").strip(),
        "url": str(candidate.get("url") or candidate.get("canonical_url") or "").strip(),
        "title": str(candidate.get("title") or "").strip(),
        "published_at": str(candidate.get("published_at") or candidate.get("published_at_utc") or "").strip(),
        "publisher": str(candidate.get("publisher") or "Unknown").strip() or "Unknown",
        "source_feed": str(candidate.get("source_feed") or "daily-news-gateway"),
    }
    for field in ("author", "description", "body", "language", "image_url"):
        if candidate.get(field) is not None:
            raw[field] = str(candidate[field])
    if isinstance(candidate.get("tags"), list):
        raw["tags"] = [str(tag) for tag in candidate["tags"]]
    raw["extra"] = {
        "gateway_candidate_id": candidate.get("candidate_id"),
        "discussion_url": candidate.get("discussion_url"),
        "scoring": candidate.get("scoring"),
    }
    return raw


def _select_single_candidate(
    selector: NewsSelector,
    pool: List[Dict[str, Any]],
    used_ids: Set[str],
    attempts: int,
    max_attempts: int,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Execute one LLM selection attempt and return (candidate, selection) if valid."""
    selection = selector.select_and_research(pool)
    if not isinstance(selection, dict):
        logger.warning(
            "Codex returned a non-object selection; retrying selection "
            f"(attempt {attempts}/{max_attempts})."
        )
        return None

    selected_id = selection.get("selected_candidate_id")
    if not isinstance(selected_id, str) or not selected_id:
        logger.warning(
            "Codex selection omitted selected_candidate_id; retrying selection "
            f"(attempt {attempts}/{max_attempts})."
        )
        return None

    if selected_id in used_ids:
        logger.warning(f"Codex selected duplicate candidate {selected_id}; retrying selection.")
        return None

    candidate = next((c for c in pool if c["candidate_id"] == selected_id), None)
    if candidate is None:
        logger.warning(
            "Codex selected candidate outside the current pool; retrying selection "
            f"(attempt {attempts}/{max_attempts})."
        )
        return None

    return candidate, selection


def _select_and_initialize_projects(
    selector: NewsSelector,
    ranked: List[Dict[str, Any]],
    used_ids: Set[str],
    count: int,
) -> Tuple[List[str], int]:
    """Perform bounded selection and project initialization loop."""
    project_ids: List[str] = []
    max_attempts = max(count * 3, len(ranked))
    attempts = 0

    while len(project_ids) < count and attempts < max_attempts:
        pool = [c for c in ranked if c["candidate_id"] not in used_ids]
        if not pool:
            break
        attempts += 1
        res = _select_single_candidate(selector, pool, used_ids, attempts, max_attempts)
        if res is None:
            continue

        candidate, selection = res
        selected_id = candidate["candidate_id"]
        used_ids.add(selected_id)

        logger.info("Selected candidate: %s (%s)", _sanitize_log_val(selected_id), _sanitize_log_val(candidate.get("title", "")))
        logger.info("Rationale: %s", _sanitize_log_val(selection.get("selection_rationale", "")))

        logger.info("Bridging to research artifact...")
        try:
            project_id = _init_candidate_project(candidate, selection)
            project_ids.append(project_id)
        except Exception as e:
            logger.warning(
                "Failed to initialize project for %s: %s; retrying selection "
                "(attempt %s/%s).",
                _sanitize_log_val(selected_id),
                e,
                attempts,
                max_attempts,
            )

    return project_ids, attempts


def _merge_unique_candidates(
    target_pool: List[Dict[str, Any]],
    new_candidates: List[Dict[str, Any]],
    used_ids: Set[str],
) -> None:
    seen_ids = {c.get("candidate_id") or c.get("id") for c in target_pool}
    for c in new_candidates:
        cid = c.get("candidate_id") or c.get("id")
        if cid and cid not in seen_ids and cid not in used_ids:
            target_pool.append(c)
            seen_ids.add(cid)


def _run_discovery_fallback(
    disc_result: Any,
    count: int,
    min_required: int,
    max_age_days: int,
    used_ids: Set[str],
) -> None:
    """Supplement an insufficient current-discovery result from the authorized backlog."""
    from lib.fixed_niche.hybrid_discovery import HybridCandidateDiscovery

    fallback = HybridCandidateDiscovery(
        require_latest_news=False,
        max_age_days=max_age_days,
    ).discover_candidates(count=max(count, min_required * 2))
    if not fallback.is_eligible:
        return
    _merge_unique_candidates(disc_result.candidates, fallback.candidates, used_ids)
    if not disc_result.is_eligible and disc_result.candidates:
        disc_result.status = "ELIGIBLE"


def _filter_fresh_candidates(candidates, max_age_hours, now=None):
    """Keep only items with a known publication time inside the freshness window."""
    from lib.fixed_niche.candidate_helpers import parse_timestamp

    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max_age_hours)).timestamp()
    end = now.timestamp()
    return [c for c in candidates if cutoff <= parse_timestamp(
        c.get("published_at") or c.get("published_at_utc")
    ) <= end]


def _hydrate_from_hybrid_discovery(
    candidate_pool: List[Dict[str, Any]],
    count: int,
    min_required: int,
    used_ids: Set[str],
    args: argparse.Namespace,
) -> List[Dict[str, Any]]:
    """Augment candidate pool with Tier 1 / Tier 2 discovery candidates if below required minimum."""
    if len(candidate_pool) >= min_required:
        return candidate_pool

    logger.info(
        "Candidate pool has %d eligible candidate(s) (need %d); activating HybridCandidateDiscovery.",
        len(candidate_pool),
        min_required,
    )
    from lib.fixed_niche.hybrid_discovery import HybridCandidateDiscovery
    require_latest = getattr(args, "require_latest_news", True)
    max_age_days = getattr(args, "max_age_days", 7)
    discovery = HybridCandidateDiscovery(
        require_latest_news=require_latest,
        max_age_days=max_age_days,
    )
    disc_result = discovery.discover_candidates(count=max(count, min_required * 2))
    need_fallback = (not disc_result.is_eligible or len(disc_result.candidates) < min_required) and require_latest
    if need_fallback:
        logger.info(
            "Latest discovery yielded fewer than %d candidates; supplementing from the authorized backlog.",
            min_required,
        )
        _run_discovery_fallback(disc_result, count, min_required, max_age_days, used_ids)

    if disc_result.is_eligible:
        _merge_unique_candidates(candidate_pool, disc_result.candidates, used_ids)
    return candidate_pool


def _produce_limits(args: argparse.Namespace, count: int) -> tuple[int, float | None]:
    min_produce = int(os.environ.get("MIN_PRODUCE_COUNT") or os.environ.get("EXPECTED_SUCCESS_COUNT") or os.environ.get("TARGET_SUCCESS_COUNT") or 3)
    min_required = min(count, min_produce)
    if getattr(args, "no_hybrid_discovery", False):
        min_required = 1
    max_age_hours = None
    if getattr(args, "require_latest_news", True):
        configured_age = os.environ.get("NEWS_MAX_SOURCE_AGE_HOURS")
        try:
            max_age_hours = float(configured_age) if configured_age is not None else float(getattr(args, "max_age_days", 7)) * 24
            if not math.isfinite(max_age_hours) or not 0 < max_age_hours <= 720:
                raise ValueError("freshness limit outside (0, 720]")
        except (ValueError, TypeError, OverflowError):
            logger.error("Invalid NEWS_MAX_SOURCE_AGE_HOURS freshness policy")
            sys.exit(1)
    return min_required, max_age_hours


def _produce_candidate_pool(args: argparse.Namespace, count: int, min_required: int, used_ids: Set[str], max_age_hours: float | None) -> List[Dict[str, Any]]:
    candidate_pool: List[Dict[str, Any]] = []
    input_value = getattr(args, "input", None)
    gateway_url = getattr(args, "gateway_url", None)
    input_file = Path(input_value) if input_value else None
    is_live_feed = bool(gateway_url) or bool(
        input_file and input_file.name in ("gateway_daily_news_feed.json", "newsnow_feed.json", "daily_candidates.json")
    ) or getattr(args, "fallback_to_curated", False)
    if gateway_url:
        logger.info("Fetching current candidates directly from Daily News Gateway...")
        gateway_items = DailyNewsGatewayClient(base_url=gateway_url).fetch_feed(base_url=gateway_url)
        candidate_pool = _normalize_and_filter_candidates(
            [_gateway_candidate_to_raw_item(item) for item in gateway_items],
            count,
            used_ids,
            fail_closed=False,
            freshness_window_hours=max_age_hours or 48.0,
        )
    elif input_file and input_file.is_file():
        candidate_pool = _ingest_and_filter_candidates(
            input_file,
            count,
            used_ids,
            fail_closed=not is_live_feed,
            freshness_window_hours=max_age_hours or 48.0,
        )
    elif not input_file:
        logger.error("Either --input or --gateway-url is required.")
        sys.exit(2)

    if max_age_hours is not None:
        candidate_pool = _filter_fresh_candidates(candidate_pool, max_age_hours)

    if is_live_feed and not getattr(args, "no_hybrid_discovery", False):
        candidate_pool = _hydrate_from_hybrid_discovery(
            candidate_pool, count, min_required, used_ids, args
        )
        if max_age_hours is not None:
            candidate_pool = _filter_fresh_candidates(candidate_pool, max_age_hours)
    return candidate_pool


def _require_ranked_candidates(candidate_pool: List[Dict[str, Any]], count: int, min_required: int) -> List[Dict[str, Any]]:
    if not candidate_pool:
        logger.info("STATUS=NO_ELIGIBLE_TOPIC: No candidates passed FixedNicheScopeGate across input and hybrid discovery.")
        print("STATUS=NO_ELIGIBLE_TOPIC")
        _record_no_eligible_marker()
        sys.exit(2)
    _clear_no_eligible_marker()
    logger.info("Scoring and ranking...")
    ranked = NewsCandidateScorer().rank_candidates(candidate_pool, limit=max(30, count * 4))
    if not ranked:
        logger.error("No valid candidates found.")
        sys.exit(1)
    if len(ranked) < min_required:
        logger.error(f"Need at least {min_required} distinct candidates but only {len(ranked)} available.")
        sys.exit(1)
    return ranked


def run_produce(args: argparse.Namespace) -> None:
    """Full pipeline: ingest -> score -> LLM select -> research brief -> checkpoint."""
    count = max(1, getattr(args, "count", 1))
    used_ids = _collect_used_project_ids()
    min_required, max_age_hours = _produce_limits(args, count)
    candidate_pool = _produce_candidate_pool(args, count, min_required, used_ids, max_age_hours)
    ranked = _require_ranked_candidates(candidate_pool, count, min_required)

    if args.dry_run:
        logger.info("[DRY RUN] Skipping Codex CLI and checkpoint generation.")
        print(json.dumps(ranked[:count], indent=2))
        return

    logger.info("Running bounded Codex selection...")
    selector = NewsSelector()
    project_ids, attempts = _select_and_initialize_projects(selector, ranked, used_ids, count)

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
    if project_ids and not getattr(args, "no_hybrid_discovery", False):
        try:
            DailyNewsGatewayClient().consume_candidates(project_ids)
        except Exception as e:
            logger.debug("Candidate consume sync to gateway skipped: %s", e)
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
    parser = argparse.ArgumentParser(description="Gateway Daily News to OpenMontage CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest and rank raw feed JSON")
    ingest_parser.add_argument("--input", required=True, help="Path to raw JSON list")
    ingest_parser.add_argument("--output", required=True, help="Path to save ranked candidates")
    ingest_parser.add_argument("--limit", type=int, default=50, help="Max candidates to output")

    produce_parser = subparsers.add_parser("produce", help="Run full ingestion -> selection -> project initialization")
    produce_input = produce_parser.add_mutually_exclusive_group(required=True)
    produce_input.add_argument("--input", help="Path to raw JSON list")
    produce_input.add_argument(
        "--gateway-url",
        help="Daily News Gateway base URL; candidates are fetched directly without a feed file",
    )
    produce_parser.add_argument("--count", type=int, default=1, help="Number of distinct topics/projects to produce")
    produce_parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls and project creation")
    produce_parser.add_argument("--no-hybrid-discovery", action="store_true", help="Use only the supplied feed, without supplementing from backlog")
    produce_parser.add_argument(
        "--require-latest-news",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Prioritize discovery of latest breaking news with real published timestamps (default: True).",
    )
    produce_parser.add_argument(
        "--max-age-days",
        type=int,
        default=7,
        help="Sliding freshness window in days (default: 7 days, meaning [run_date - 7 days, run_date]).",
    )

    fetch_parser = subparsers.add_parser("fetch", help="Fetch latest news feeds via Toolcase Gateway Daily News service")
    fetch_parser.add_argument("--source", choices=("daily-news", "muse"), default="daily-news", help="Discovery provider")
    fetch_parser.add_argument("--url", default=None, help="Daily News Gateway base URL (defaults to TOOLCASE_GATEWAY_URL/custom/daily-news)")
    fetch_parser.add_argument("--output", required=True, help="Path to write the raw feed JSON")
    fetch_parser.add_argument("--min-items", type=int, default=3, help="Minimum valid items required")

    mark_parser = subparsers.add_parser("mark-muse-used", help="Persist a successfully validated Muse candidate ID")
    mark_parser.add_argument("--candidate-id", required=True)

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
    elif args.command == "mark-muse-used":
        _mark_muse_used(args.candidate_id)
    elif args.command == "capture-source":
        return run_capture_source(args)
    elif args.command == "prepare-review":
        return run_prepare_review(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
