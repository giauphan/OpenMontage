#!/usr/bin/env python3
"""Attach or re-attach custom thumbnail to scheduled/published YouTube videos.

Provides CLI tool to generate and attach thumbnails retroactively to YouTube videos.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.news_visual.thumbnail_orchestrator import ThumbnailOrchestrator
from tools.publishers.youtube_publisher import YoutubePublisher, _upload_thumbnail_if_present

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("attach_thumbnail")


KNOWN_VIDEO_MAP: Dict[str, str] = {
    "cand_0e4153ec05bae47d": "vv8kAc3kcew",
    "cand_4891c883d4ccfa36": "_H8sgDSAAjo",
    "cand_489a1851509a707e": "e6R_HqCxTXw",
    "cand_14677a0ef53452c1": "dPFPR8zLvY4",
    "cand_172e107932cd40f4": "StKCqE5Rv60",
    "cand_1a36bc3cdec38b34": "hhVuFTjmgzI",
    "cand_1fe6d02cd35a931c": "0DX6XRx_eRI",
    "cand_38a2f774ee2b3f4f": "bn6KIB1arj8",
    "cand_7830949b25a9b9ee": "OhbFJfDtUbU",
    "cand_7999dd5faa024c47": "hXILXBToyjo",
    "cand_7d9acfe4bef468f1": "uMRKHuLz-Ss",
    "cand_a7e88d0582d65dc9": "WrcAebyHgZM",
    "cand_b6804253adb42264": "qmNR7O3LiO0",
    "cand_dd067cd4b347e900": "XVn3f0tqs04",
    "cand_e0d407f53099af7f": "Vj7KLV-AfsQ",
    "cand_fd67af8f75f52c15": "4JJHkejs_k4",
}


def resolve_video_id(project_dir: Path, explicit_video_id: Optional[str] = None) -> Optional[str]:
    """Resolve video ID from explicit argument, publish_log, Firestore store, or known map."""
    if explicit_video_id:
        return explicit_video_id.strip()

    # 1. Check publish_log.json
    pub_log_file = project_dir / "publish_log.json"
    if pub_log_file.is_file():
        try:
            data = json.loads(pub_log_file.read_text(encoding="utf-8"))
            for entry in data.get("entries", []):
                if entry.get("platform") == "youtube" and entry.get("video_id"):
                    return str(entry["video_id"])
        except Exception as e:
            logger.warning(f"Failed to parse {pub_log_file}: {e}")

    # 2. Check Firestore PublishStore if available
    try:
        from tools.publish_store import PublishStore, publish_key

        store = PublishStore()
        meta_file = project_dir / "publish_metadata.json"
        topic_id = project_dir.name
        format_type = "short"
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            topic_id = meta.get("id") or topic_id
            format_type = meta.get("format", "short")

        kind = "longform" if format_type in ("long", "longform", "16:9") else "short"

        # Check dates in publish_metadata, schedule config, or recent range
        dates_to_check: set[str] = set()
        from scripts.publish_config import load_config
        cfg = load_config()
        for p in cfg.get("active_projects", []):
            if p.get("project_id") == project_dir.name and p.get("publish_date"):
                dates_to_check.add(p.get("publish_date"))

        from datetime import date, timedelta
        today = date.today()
        for offset in range(-7, 8):
            dates_to_check.add((today + timedelta(days=offset)).isoformat())

        for p_date in sorted(dates_to_check):
            for t_id in (topic_id, project_dir.name):
                for k in (kind, "short", "longform"):
                    key = publish_key(p_date, t_id, "youtube", k)
                    doc = store.get(key)
                    if doc and doc.get("video_id"):
                        return str(doc["video_id"])
    except Exception as e:
        logger.debug(f"Firestore video_id lookup skipped: {e}")

    # 3. Check known candidate video map
    if project_dir.name in KNOWN_VIDEO_MAP:
        return KNOWN_VIDEO_MAP[project_dir.name]

    return None


def attach_thumbnail_to_video(
    project_dir: Path,
    video_id: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
    theme_color: str = "#FFDD00",
    force_regenerate: bool = False,
    min_size_bytes: int = 50_000,
    service: Optional[Any] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Generate if needed and attach thumbnail to YouTube video."""
    pdir = Path(project_dir).resolve()
    if not pdir.is_dir():
        return False, "PROJECT_NOT_FOUND", f"Directory does not exist: {pdir}"

    resolved_vid = resolve_video_id(pdir, video_id)
    if not resolved_vid:
        return False, "MISSING_VIDEO_ID", f"Could not determine YouTube video ID for {pdir.name}"

    # Determine thumbnail path
    thumb_file: Optional[Path] = None
    if thumbnail_path:
        candidate = Path(thumbnail_path).expanduser().resolve()
        if candidate.is_file():
            thumb_file = candidate

    if not thumb_file:
        for fname in ("thumbnail.jpg", "thumbnail.png"):
            cand_thumb = pdir / "thumbnails" / fname
            if cand_thumb.is_file():
                thumb_file = cand_thumb
                break

    # Check if thumbnail should be regenerated (missing, forced, or tiny placeholder)
    needs_generation = False
    if not thumb_file or not thumb_file.is_file():
        needs_generation = True
    elif force_regenerate:
        logger.info(f"Force regeneration requested for {pdir.name}")
        needs_generation = True
    elif thumb_file.stat().st_size < min_size_bytes:
        logger.info(
            f"Thumbnail for {pdir.name} is a placeholder ({thumb_file.stat().st_size} bytes < {min_size_bytes}); regenerating via Muse..."
        )
        needs_generation = True

    if needs_generation:
        logger.info(f"Generating authentic Muse AI thumbnail for {pdir.name}...")
        meta_file = pdir / "publish_metadata.json"
        title = pdir.name
        topic = ""
        fmt = "short"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                title = meta.get("title", title)
                topic = meta.get("topic", topic)
                fmt = meta.get("format", fmt)
            except Exception:
                pass

        res = ThumbnailOrchestrator.generate_thumbnail(
            project_dir=pdir,
            title=title,
            topic=topic,
            format_type=fmt,
            theme_color=theme_color,
            allow_fallback=True,
        )
        if not (res.success and res.thumbnail_path and Path(res.thumbnail_path).is_file()):
            return False, "GENERATE_FAILED", res.error or "Thumbnail generation failed"
        thumb_file = Path(res.thumbnail_path)

    # Attach to YouTube
    logger.info(f"Attaching {thumb_file} ({thumb_file.stat().st_size} bytes) to YouTube video {resolved_vid}...")
    if service is None:
        pub = YoutubePublisher()
        secret_path = Path(os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "~/.openmontage/client_secret.json")).expanduser()
        token_path = Path(os.environ.get("YOUTUBE_TOKEN_PATH", "~/.openmontage/youtube_token.json")).expanduser()
        try:
            service = pub._get_authenticated_service(secret_path, token_path, interactive=False)
        except Exception as e:
            return False, "AUTH_FAILED", f"YouTube authentication failed: {e}"

    status, detail = _upload_thumbnail_if_present(service, resolved_vid, str(thumb_file))
    if status == "THUMBNAIL_ATTACHED":
        logger.info(f"Successfully attached thumbnail to {resolved_vid}")
        return True, status, None

    logger.warning(f"Upload thumbnail result: {status} ({detail})")
    return False, status, detail


def attach_all_thumbnails(
    projects_dir: Optional[Path] = None,
    force_regenerate: bool = False,
    min_size_bytes: int = 50_000,
    theme_color: str = "#FFDD00",
) -> Dict[str, Any]:
    """Scan all candidate projects and attach Muse AI thumbnails to any associated YouTube videos."""
    p_root = (projects_dir or ROOT / "projects").resolve()
    logger.info(f"Scanning {p_root} for candidate projects with YouTube videos...")

    # Authenticate once
    pub = YoutubePublisher()
    secret_path = Path(os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "~/.openmontage/client_secret.json")).expanduser()
    token_path = Path(os.environ.get("YOUTUBE_TOKEN_PATH", "~/.openmontage/youtube_token.json")).expanduser()
    try:
        service = pub._get_authenticated_service(secret_path, token_path, interactive=False)
    except Exception as e:
        logger.error(f"YouTube authentication failed: {e}")
        return {"total": 0, "success": 0, "failed": 0, "results": {}, "error": str(e)}

    # Collect projects to process
    candidate_dirs = sorted([p for p in p_root.iterdir() if p.is_dir() and p.name.startswith("cand_")])
    results: Dict[str, Dict[str, Any]] = {}
    success_count = 0
    fail_count = 0

    for pdir in candidate_dirs:
        vid = resolve_video_id(pdir)
        if not vid:
            continue

        cand_thumb = None
        for fname in ("thumbnail.jpg", "thumbnail.png"):
            cand = pdir / "thumbnails" / fname
            if cand.is_file():
                cand_thumb = cand
                break
        if not cand_thumb:
            cand_thumb = pdir / "thumbnails" / "thumbnail.png"
        is_placeholder = not cand_thumb.is_file() or cand_thumb.stat().st_size < min_size_bytes

        if not force_regenerate and not is_placeholder:
            logger.info(f"Project {pdir.name} already has high-quality thumbnail ({cand_thumb.stat().st_size} bytes). Uploading...")
            status, detail = _upload_thumbnail_if_present(service, vid, str(cand_thumb))
            is_ok = status == "THUMBNAIL_ATTACHED"
            results[pdir.name] = {
                "video_id": vid,
                "status": status,
                "success": is_ok,
                "detail": detail,
                "size_bytes": cand_thumb.stat().st_size,
            }
            if is_ok:
                success_count += 1
            else:
                fail_count += 1
            continue

        logger.info(f"Processing {pdir.name} (Video ID: {vid})...")
        success, status, err = attach_thumbnail_to_video(
            project_dir=pdir,
            video_id=vid,
            theme_color=theme_color,
            force_regenerate=force_regenerate,
            min_size_bytes=min_size_bytes,
            service=service,
        )
        results[pdir.name] = {
            "video_id": vid,
            "status": status,
            "success": success,
            "detail": err,
        }
        if success:
            success_count += 1
        else:
            fail_count += 1

    summary = {
        "total": len(results),
        "success": success_count,
        "failed": fail_count,
        "results": results,
    }
    logger.info(f"Batch thumbnail processing complete: {success_count}/{len(results)} successful.")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach thumbnail to YouTube video(s)")
    parser.add_argument("project_id", nargs="?", default=None, help="Candidate project ID or path (e.g. cand_0e4153ec05bae47d)")
    parser.add_argument("--all", action="store_true", help="Process all candidate projects with YouTube videos")
    parser.add_argument("--projects-dir", help="Custom projects directory path (for --all)")
    parser.add_argument("--video-id", help="Explicit YouTube video ID (optional)")
    parser.add_argument("--thumbnail", help="Explicit thumbnail image path (optional)")
    parser.add_argument("--theme-color", default="#FFDD00", help="Headline theme color")
    parser.add_argument("--force", action="store_true", help="Force regenerate thumbnail even if one exists")
    parser.add_argument("--min-size", type=int, default=50_000, help="Min thumbnail bytes to consider valid non-placeholder")
    args = parser.parse_args()

    if args.all:
        p_dir = Path(args.projects_dir) if args.projects_dir else None
        summary = attach_all_thumbnails(
            projects_dir=p_dir,
            force_regenerate=args.force,
            min_size_bytes=args.min_size,
            theme_color=args.theme_color,
        )
        print(json.dumps(summary, indent=2))
        return 0 if summary.get("failed", 0) == 0 else 1

    if not args.project_id:
        parser.error("project_id is required unless --all is specified")

    pdir = ROOT / "projects" / args.project_id if not Path(args.project_id).is_dir() else Path(args.project_id)
    success, status, err = attach_thumbnail_to_video(
        project_dir=pdir,
        video_id=args.video_id,
        thumbnail_path=args.thumbnail,
        theme_color=args.theme_color,
        force_regenerate=args.force,
        min_size_bytes=args.min_size,
    )
    if success:
        print(f"SUCCESS: Thumbnail attached to video for project {pdir.name}")
        return 0
    else:
        print(f"FAILED: {status} - {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
