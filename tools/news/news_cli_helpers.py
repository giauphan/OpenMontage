"""Validation and sanitization helper utilities for News CLI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

logger = logging.getLogger(__name__)


def _sanitize_log_val(val: Any) -> str:
    """Sanitize strings before logging to prevent log injection (CWE-117)."""
    clean = str(val).replace("\r", " ").replace("\n", " ").strip()
    return clean[:120]


def _validate_safe_input_path(path: Path | str, *, must_exist: bool = True) -> Path:
    """Validate path against traversal attacks (CWE-22 / CWE-73)."""
    raw_obj = Path(path)
    if any(part == ".." for part in raw_obj.parts) or raw_obj.is_symlink():
        logger.error("Path traversal or symlink detected: %s", _sanitize_log_val(path))
        sys.exit(1)
    p = raw_obj.expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    home_dir = Path.home().resolve()
    cwd_dir = Path.cwd().resolve()
    tmp_dir = Path(tempfile.gettempdir()).resolve()
    is_in_tmp = p.is_relative_to(tmp_dir)
    if not (p.is_relative_to(repo_root) or p.is_relative_to(home_dir) or (cwd_dir != Path(cwd_dir.anchor) and p.is_relative_to(cwd_dir)) or is_in_tmp):
        logger.error("Path traversal detected or path outside allowed root: %s", _sanitize_log_val(path))
        sys.exit(1)
    if must_exist and not p.is_file():
        logger.error("Input file not found: %s", _sanitize_log_val(path))
        sys.exit(1)
    if must_exist and is_in_tmp and hasattr(os, "getuid") and p.stat().st_uid != os.getuid():
        logger.error("Input file in temp directory must be owned by current user: %s", _sanitize_log_val(path))
        sys.exit(1)
    return p


def _validate_safe_output_path(path: Path | str) -> Path:
    return _validate_safe_input_path(path, must_exist=False)
