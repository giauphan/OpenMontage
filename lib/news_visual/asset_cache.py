"""Durable asset cache and gateway job state tracker for OpenMontage visuals."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _secure_cache_dir(path: Path) -> Path:
    if path.is_symlink():
        raise PermissionError(f"Cache directory cannot be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise PermissionError(f"Cannot securely open cache directory: {path}") from exc

    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise PermissionError(f"Cache path is not a directory: {path}")
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise PermissionError(f"Unsafe cache directory owner: {path}")
        if st.st_mode & 0o077:
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o700)
                else:
                    path.chmod(0o700)
                st = os.fstat(fd)
            except OSError:
                pass
        if st.st_mode & 0o077:
            raise PermissionError(f"Cache directory is accessible by other users: {path}")
    finally:
        os.close(fd)
    return path.resolve()


class VisualAssetCache:
    """Manages cache keys, atomic local caching, and durable job recovery."""

    GATEWAY_CONTRACT_VERSION: str = "1.0"
    VISUAL_STYLE_VERSION: str = "1.0"

    def __init__(self, cache_dir: Optional[Path] = None):
        raw_uid = os.getuid() if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
        uid = re.sub(r"[^A-Za-z0-9_-]", "_", str(raw_uid))
        fallback_cache = Path(tempfile.gettempdir()) / f"openmontage_visual_cache_{uid}"
        default_cache = Path(os.environ["OPENMONTAGE_CACHE_DIR"]) if os.environ.get("OPENMONTAGE_CACHE_DIR") else fallback_cache
        target = Path(cache_dir or default_cache)
        try:
            self.cache_dir = _secure_cache_dir(target)
        except (OSError, PermissionError) as exc:
            logger.warning("Cache dir %s unusable (%s); using fallback %s", target, exc, fallback_cache)
            try:
                self.cache_dir = _secure_cache_dir(fallback_cache)
            except (OSError, PermissionError) as fallback_exc:
                logger.warning("Fallback cache %s unusable (%s); creating private temp dir", fallback_cache, fallback_exc)
                secure_tmp = Path(tempfile.mkdtemp(prefix="openmontage_visual_cache_"))
                self.cache_dir = _secure_cache_dir(secure_tmp)
        self.jobs_file = self.cache_dir / "gateway_jobs.json"
        self._init_jobs_file()

    def _init_jobs_file(self) -> None:
        if not self.jobs_file.is_file():
            self.jobs_file.write_text("{}", encoding="utf-8")

    def compute_cache_key(
        self,
        prompt: str,
        aspect_ratio: str,
        provider: str = "muse",
        model: str = "muse-image",
        visual_intent: str = "",
        visual_plan_sha256: str = "",
        script_sha256: str = "",
        claim_ledger_sha256: str = "",
        source_capture_hashes: str = "",
        policy_sha256: str = "",
    ) -> str:
        """Derive authoritative SHA256 cache key covering all factual and stylistic inputs."""
        payload = {
            "model_alias": model,
            "provider": provider,
            "prompt": prompt.strip(),
            "aspect_ratio": aspect_ratio,
            "gateway_contract_version": self.GATEWAY_CONTRACT_VERSION,
            "visual_intent": visual_intent.strip(),
            "visual_plan_sha256": visual_plan_sha256,
            "script_sha256": script_sha256,
            "claim_ledger_sha256": claim_ledger_sha256,
            "source_capture_hashes": source_capture_hashes,
            "visual_style_version": self.VISUAL_STYLE_VERSION,
            "policy_sha256": policy_sha256,
        }
        canonical_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def get_cached_asset(self, cache_key: str) -> Optional[Path]:
        """Return cached image path if present and content is non-empty."""
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            cached_file = self.cache_dir / f"{cache_key}{ext}"
            if cached_file.is_file() and cached_file.stat().st_size > 100:
                return cached_file
        return None

    def store_cached_asset(self, cache_key: str, src_path: Path) -> Path:
        """Atomically cache asset bytes under cache key."""
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", str(cache_key)):
            raise ValueError(f"Invalid cache key: {cache_key}")
        src_obj = Path(src_path)
        if any(part == ".." for part in src_obj.parts) or src_obj.is_symlink():
            raise ValueError(f"Path traversal detected in source path: {src_path}")
        src_resolved = src_obj.resolve()
        if not src_resolved.is_file():
            raise ValueError(f"Source file not found: {src_path}")
        ext = src_resolved.suffix if src_resolved.suffix else ".png"
        dest = (self.cache_dir / f"{cache_key}{ext}").resolve()
        try:
            dest.relative_to(self.cache_dir.resolve())
        except ValueError:
            raise ValueError(f"Destination path traverses outside cache directory: {dest}")
        tmp_dest = (self.cache_dir / f"{cache_key}.tmp.{uuid.uuid4().hex}").resolve()
        try:
            tmp_dest.relative_to(self.cache_dir.resolve())
        except ValueError:
            raise ValueError("Temporary destination outside cache directory")
        data = src_resolved.read_bytes()
        tmp_dest.write_bytes(data)
        tmp_dest.replace(dest)
        return dest

    def get_persisted_job(self, submission_key: str) -> Optional[Dict[str, Any]]:
        """Recover persisted gateway job by submission key across process restarts."""
        try:
            jobs = json.loads(self.jobs_file.read_text(encoding="utf-8"))
            return jobs.get(submission_key)
        except Exception as exc:
            logger.warning(f"Failed to read gateway_jobs.json: {exc}")
            return None

    def record_persisted_job(
        self,
        submission_key: str,
        gateway_job_id: str,
        status: str,
        image_path: Optional[str] = None,
    ) -> None:
        """Atomically persist gateway job state for idempotent recovery."""
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", str(submission_key)):
            raise ValueError(f"Invalid submission key: {submission_key}")
        if image_path:
            img_p = Path(image_path)
            if any(part == ".." for part in img_p.parts) or img_p.is_symlink():
                raise ValueError(f"Path traversal detected in image_path: {image_path}")
        tmp_file = self.jobs_file.with_suffix(f".tmp.{uuid.uuid4().hex}").resolve()
        try:
            tmp_file.relative_to(self.cache_dir.resolve())
        except ValueError as err:
            raise ValueError(f"Temporary jobs file outside cache directory: {tmp_file}") from err
        try:
            jobs = json.loads(self.jobs_file.read_text(encoding="utf-8"))
            jobs[submission_key] = {
                "gateway_job_id": gateway_job_id,
                "status": status,
                "image_path": image_path,
                "updated_at": time.time(),
            }
            tmp_file.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
            tmp_file.replace(self.jobs_file)
        except Exception as exc:
            logger.warning(f"Failed to record persisted job: {exc}")
