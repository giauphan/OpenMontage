from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    candidates = list(Path.home().glob(".local/share/uv/**/ffmpeg"))
    return str(candidates[0]) if candidates else "ffmpeg"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def publish_key(date: str, topic: str, platform: str, kind: str) -> str:
    raw = f"{date}_{platform}_{topic}_{kind}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")


def normalize_identity(value: str) -> str:
    value = re.sub(r"(?i)#\s*(shorts?|reels?)\b", " ", value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\b(shorts?|reels?)$", "", value).strip()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def media_fingerprint(path: str | Path) -> str:
    result = subprocess.run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-t",
            "60",
            "-vf",
            "fps=1,scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2:black,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def uniqueness_key(platform: str, account: str, kind: str, identity_type: str, value: str) -> str:
    normalized = normalize_identity(value) if identity_type in {"topic", "title"} else value.lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    raw = f"unique_{platform}_{account}_{kind}_{identity_type}_{digest}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")


def existing_record_summary(record: dict[str, Any] | None) -> str:
    if not record:
        return "missing"
    parts = [str(record.get("status") or "recorded")]
    value = record.get("video_url") or record.get("video_id") or record.get("platform_id")
    if value:
        parts.append(str(value))
    return " ".join(parts)
