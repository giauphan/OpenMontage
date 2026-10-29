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


def resolve_video_id(project_dir: Path, explicit_video_id: Optional[str] = None) -> Optional[str]:
    """Resolve video ID from explicit argument, publish_log, or Firestore store."""
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

        # Check date in publish_metadata or schedule config
        from scripts.publish_config import load_config
        cfg = load_config()
        for p in cfg.get("active_projects", []):
            if p.get("project_id") == project_dir.name:
                p_date = p.get("publish_date")
                if p_date:
                    key = publish_key(p_date, topic_id, "youtube", kind)
                    doc = store.get(key)
                    if doc and doc.get("video_id"):
                        return str(doc["video_id"])
    except Exception as e:
        logger.debug(f"Firestore video_id lookup skipped: {e}")

    return None


def attach_thumbnail_to_video(
    project_dir: Path,
    video_id: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
    theme_color: str = "#FFDD00",
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
        cand_thumb = pdir / "thumbnails" / "thumbnail.png"
        if cand_thumb.is_file():
            thumb_file = cand_thumb

    # Generate if missing
    if not thumb_file:
        logger.info(f"Thumbnail missing for {pdir.name}; generating via ThumbnailOrchestrator...")
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
    logger.info(f"Attaching {thumb_file} to YouTube video {resolved_vid}...")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach thumbnail to a YouTube video")
    parser.add_argument("project_id", help="Candidate project ID or path (e.g. cand_0e4153ec05bae47d)")
    parser.add_argument("--video-id", help="Explicit YouTube video ID (optional)")
    parser.add_argument("--thumbnail", help="Explicit thumbnail image path (optional)")
    parser.add_argument("--theme-color", default="#FFDD00", help="Headline theme color")
    args = parser.parse_args()

    pdir = ROOT / "projects" / args.project_id if not Path(args.project_id).is_dir() else Path(args.project_id)
    success, status, err = attach_thumbnail_to_video(
        project_dir=pdir,
        video_id=args.video_id,
        thumbnail_path=args.thumbnail,
        theme_color=args.theme_color,
    )
    if success:
        print(f"SUCCESS: Thumbnail attached to video for project {pdir.name}")
        return 0
    else:
        print(f"FAILED: {status} - {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
