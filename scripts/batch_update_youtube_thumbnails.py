#!/usr/bin/env python3
"""Batch update YouTube video thumbnails with authentic Muse AI generated artwork.

Iterates over published/scheduled candidate videos, generates high-converting
thumbnails using Muse AI with high-contrast typography safe-zone overlays,
and attaches them to YouTube.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.attach_youtube_thumbnail import (
    KNOWN_VIDEO_MAP,
    attach_thumbnail_to_video,
    resolve_video_id,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("batch_update_thumbnails")

TARGET_VIDEOS: List[Tuple[str, str]] = [
    # Scheduled for today (14:15 ICT):
    ("cand_489a1851509a707e", "e6R_HqCxTXw"),
    # Scheduled for tomorrow:
    ("cand_14677a0ef53452c1", "dPFPR8zLvY4"),
    # Historical videos requiring retrofitted Muse thumbnails:
    ("cand_172e107932cd40f4", "StKCqE5Rv60"),
    ("cand_1a36bc3cdec38b34", "hhVuFTjmgzI"),
    ("cand_1fe6d02cd35a931c", "0DX6XRx_eRI"),
    ("cand_38a2f774ee2b3f4f", "bn6KIB1arj8"),
    ("cand_7830949b25a9b9ee", "OhbFJfDtUbU"),
    ("cand_7999dd5faa024c47", "hXILXBToyjo"),
    ("cand_7d9acfe4bef468f1", "uMRKHuLz-Ss"),
    ("cand_a7e88d0582d65dc9", "WrcAebyHgZM"),
    ("cand_b6804253adb42264", "qmNR7O3LiO0"),
    ("cand_dd067cd4b347e900", "XVn3f0tqs04"),
    ("cand_e0d407f53099af7f", "Vj7KLV-AfsQ"),
    ("cand_fd67af8f75f52c15", "4JJHkejs_k4"),
    # Already verified authentic Muse thumbnails (skipped unless forced):
    ("cand_0e4153ec05bae47d", "vv8kAc3kcew"),
    ("cand_4891c883d4ccfa36", "_H8sgDSAAjo"),
]


def update_single_candidate(
    project_dir: Path,
    video_id: Optional[str] = None,
    force: bool = False,
    min_size_bytes: int = 100_000,
) -> Dict[str, Any]:
    """Process a single candidate project and attach thumbnail to YouTube."""
    pdir = project_dir.resolve()
    if not pdir.is_dir():
        return {
            "candidate_id": pdir.name,
            "status": "DIR_NOT_FOUND",
            "success": False,
            "error": f"Project directory not found: {pdir}",
        }

    vid = resolve_video_id(pdir, video_id)
    if not vid:
        return {
            "candidate_id": pdir.name,
            "status": "MISSING_VIDEO_ID",
            "success": False,
            "error": f"No YouTube video ID found for {pdir.name}",
        }

    thumb_file = pdir / "thumbnails" / "thumbnail.png"
    if not force and thumb_file.is_file() and thumb_file.stat().st_size >= min_size_bytes:
        logger.info(
            f"Candidate {pdir.name} already has high-res thumbnail ({thumb_file.stat().st_size} bytes); skipping."
        )
        return {
            "candidate_id": pdir.name,
            "video_id": vid,
            "status": "ALREADY_PRESENT",
            "success": True,
            "size": thumb_file.stat().st_size,
        }

    start_time = time.time()
    logger.info(f"Processing candidate {pdir.name} (Video ID: {vid})...")
    success, status, err = attach_thumbnail_to_video(
        project_dir=pdir,
        video_id=vid,
        force_regenerate=force,
        min_size_bytes=min_size_bytes,
    )
    elapsed = round(time.time() - start_time, 2)

    thumb_size = thumb_file.stat().st_size if thumb_file.is_file() else 0
    return {
        "candidate_id": pdir.name,
        "video_id": vid,
        "status": status,
        "success": success,
        "error": err,
        "size": thumb_size,
        "elapsed_seconds": elapsed,
    }


def run_batch_update(
    projects_dir: Path,
    candidates: Optional[List[Tuple[str, str]]] = None,
    force: bool = False,
    delay_seconds: float = 3.0,
) -> List[Dict[str, Any]]:
    """Iterate and update thumbnails for all specified candidates."""
    targets = candidates or TARGET_VIDEOS
    results: List[Dict[str, Any]] = []

    logger.info(f"Starting batch update for {len(targets)} candidates in {projects_dir}...")
    for idx, (cid, vid) in enumerate(targets, 1):
        logger.info(f"[{idx}/{len(targets)}] Candidate {cid} (Video ID: {vid})")
        pdir = projects_dir / cid
        res = update_single_candidate(pdir, video_id=vid, force=force)
        results.append(res)
        logger.info(f"Result for {cid}: status={res['status']} success={res['success']}")

        if idx < len(targets) and res.get("status") != "ALREADY_PRESENT":
            time.sleep(delay_seconds)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch update YouTube thumbnails with Muse AI")
    parser.add_argument(
        "--projects-dir",
        default=str(ROOT / "projects"),
        help="Root projects directory path",
    )
    parser.add_argument(
        "--candidates",
        nargs="*",
        help="Specific candidate IDs to update (e.g. cand_489a1851509a707e)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regenerate and re-upload even if high-res thumbnail already exists",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Delay in seconds between generations to avoid rate limiting",
    )
    args = parser.parse_args()

    p_root = Path(args.projects_dir).expanduser().resolve()
    target_list: Optional[List[Tuple[str, str]]] = None
    if args.candidates:
        target_list = [(c, KNOWN_VIDEO_MAP.get(c, "")) for c in args.candidates]

    results = run_batch_update(
        projects_dir=p_root,
        candidates=target_list,
        force=args.force,
        delay_seconds=args.delay,
    )

    success_count = sum(1 for r in results if r["success"])
    fail_count = sum(1 for r in results if not r["success"])
    already_count = sum(1 for r in results if r["status"] == "ALREADY_PRESENT")

    logger.info(
        f"Batch summary: Total={len(results)}, Succeeded={success_count} "
        f"(Already Present={already_count}), Failed={fail_count}"
    )

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
