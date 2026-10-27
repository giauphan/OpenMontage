"""Durable asset cache and gateway job state tracker for OpenMontage visuals."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VisualAssetCache:
    """Manages cache keys, atomic local caching, and durable job recovery."""

    GATEWAY_CONTRACT_VERSION: str = "1.0"
    VISUAL_STYLE_VERSION: str = "1.0"

    def __init__(self, cache_dir: Optional[Path] = None):
        default_cache = Path(os.environ.get("OPENMONTAGE_CACHE_DIR", "/tmp/openmontage_visual_cache"))
        self.cache_dir = Path(cache_dir or default_cache)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.cache_dir = Path("/tmp/openmontage_visual_cache")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
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
        ext = src_path.suffix if src_path.suffix else ".png"
        dest = self.cache_dir / f"{cache_key}{ext}"
        tmp_dest = self.cache_dir / f"{cache_key}.tmp.{os.getpid()}_{int(time.time())}"
        data = src_path.read_bytes()
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
        try:
            jobs = json.loads(self.jobs_file.read_text(encoding="utf-8"))
            jobs[submission_key] = {
                "gateway_job_id": gateway_job_id,
                "status": status,
                "image_path": image_path,
                "updated_at": time.time(),
            }
            tmp_file = self.jobs_file.with_suffix(f".tmp.{os.getpid()}")
            tmp_file.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
            tmp_file.replace(self.jobs_file)
        except Exception as exc:
            logger.warning(f"Failed to record persisted job: {exc}")
