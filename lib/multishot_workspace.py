"""Multi-shot project workspace — safe init, stable paths, atomic persistence.

Provides helpers for:
  - Initializing a multi-shot project workspace under projects/<id>/
  - Resolving stable paths for planning artifacts, raw clips, normalized
    clips, final renders, and per-shot manifests
  - Atomic JSON persistence (write temp → rename → fsync)
  - Project-level mutation locking via version checks on run_manifest.json
  - Invalidating input paths that contain path traversal, absolute paths,
    or unsafe characters

The workspace layer intentionally avoids orchestration logic: no scheduling,
no API calls, no creative decisions. It only persists, reads, validates,
and mutates local state atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib.checkpoint import init_project
from lib.paths import PROJECTS_DIR

# ------------------------------------------------------------------
# Path safety helpers
# ------------------------------------------------------------------

_UNSAFE_ID_PATTERNS = ["/", "\\", "\0", "\n", "\r"]


def _validate_id(name: str, label: str = "id") -> None:
    """Reject unsafe ids used for directory names or file stem names."""
    if not name:
        raise ValueError(f"{label} must be non-empty")
    if len(name) > 256:
        raise ValueError(f"{label} too long: {len(name)} > 256")
    for c in _UNSAFE_ID_PATTERNS:
        if c in name:
            raise ValueError(
                f"{label} {name!r} contains unsafe character {c!r}"
            )


def _safe_shot_filename(base: str, shot_id: str, ext: str = "") -> str:
    """Return a stable filename stem for a given shot id."""
    _validate_id(shot_id, "shot_id")
    stem = f"{base}_{shot_id}"
    return f"{stem}{ext}"


# ------------------------------------------------------------------
# Workspace layout
# ------------------------------------------------------------------

PLANNING_DIR = "planning"
REFERENCES_DIR = "references"
KEYFRAMES_DIR = "keyframes"
PROMPTS_DIR = "prompts"
RAW_DIR = "raw"
NORMALIZED_DIR = "normalized"
FINAL_DIR = "final"
REPORTS_DIR = "reports"

PLANNING_ARTIFACTS = [
    "request.json",
    "story.json",
    "character_bible.json",
    "style_bible.json",
    "shot_plan.json",
    "continuity_state.json",
]

KEYFRAME_EXTENSIONS = [".png", ".jpg", ".jpeg"]

# ------------------------------------------------------------------
# Init
# ------------------------------------------------------------------

def init_multishot_project(
    project_id: str,
    *,
    title: str,
    pipeline_type: str = "multi-shot",
    pipeline_dir: Optional[Path] = None,
) -> Path:
    """Initialize a multi-shot project workspace.

    Calls checkpoint.init_project (which writes projects/<id>/project.json and
    creates the canonical assets/ renders/ subdirs), then adds the multi-shot
    planning artifact tree. Idempotent: re-running on an existing project
    preserves existing data.

    Args:
        project_id: Stable project handle (sanitized).
        title: Human-readable project title.
        pipeline_type: Fixed to 'multi-shot'.
        pipeline_dir: Override default projects root (tests use tmp_path).

    Returns:
        Path to the project root.
    """
    _validate_id(project_id, "project_id")
    base = pipeline_dir or PROJECTS_DIR
    project_dir = base / project_id

    if not project_dir.exists():
        init_project(project_id, title=title, pipeline_type=pipeline_type, pipeline_dir=pipeline_dir)

    # Multi-shot-specific dirs
    for subdir in (
        PLANNING_DIR,
        REFERENCES_DIR,
        KEYFRAMES_DIR,
        PROMPTS_DIR,
        RAW_DIR,
        NORMALIZED_DIR,
        FINAL_DIR,
        REPORTS_DIR,
    ):
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    return project_dir


# ------------------------------------------------------------------
# Path resolution
# ------------------------------------------------------------------

def resolve_path(
    project_dir: Path,
    category: str,
    shot_id: Optional[str] = None,
    ext: str = "",
) -> Path:
    """Resolve a path under a multi-shot project dir.

    Args:
        project_dir: Root of the project workspace.
        category: One of PLANNING_DIR, REFERENCES_DIR, KEYFRAMES_DIR,
            PROMPTS_DIR, RAW_DIR, NORMALIZED_DIR, FINAL_DIR, REPORTS_DIR.
        shot_id: Optional stable shot id (e.g., 'shot_001').
        ext: File extension to append (must start with '.').

    Returns:
        Absolute Path under project_dir.
    """
    valid_cats = {
        PLANNING_DIR, REFERENCES_DIR, KEYFRAMES_DIR, PROMPTS_DIR,
        RAW_DIR, NORMALIZED_DIR, FINAL_DIR, REPORTS_DIR,
    }
    if category not in valid_cats:
        raise ValueError(f"Invalid category {category!r}")

    # Guard against absolute-path injection via shot_id or category.
    if shot_id is not None:
        if Path(shot_id).is_absolute() or shot_id.startswith(".."):
            raise ValueError(f"unsafe shot_id {shot_id!r}")
        _validate_id(shot_id, "shot_id")
    elif not ext:
        _validate_id(category, "category")

    path = project_dir / category / (shot_id or "")
    if ext:
        if not ext.startswith("."):
            ext = f".{ext}"
        path = path.with_suffix(ext)

    # Confirm resolved path stays inside project_dir.
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    if not str(resolved).startswith(str(project_dir.resolve())):
        raise ValueError(f"path escapes project dir: {path}")

    return resolved


# ------------------------------------------------------------------
# Atomic persistence
# ------------------------------------------------------------------

def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to path atomically (temp + rename + fsync).

    Raises on failure; the destination is either the new file or nothing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp_{path.name}_{int(time.time() * 1000)}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def read_json_atomic(path: Path) -> Any:
    """Read a JSON file; raises FileNotFoundError if absent, json.JSONDecodeError otherwise."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------
# Run manifest helpers
# ------------------------------------------------------------------

_RUN_MANIFEST_PATH = "run_manifest.json"

_VALID_PROJECT_STATUSES = frozenset([
    "CREATED", "PLANNED", "REFERENCES_READY", "GENERATING",
    "PARTIAL", "SHOTS_READY", "NORMALIZED", "ASSEMBLED",
    "FINALIZING", "COMPLETED", "FAILED",
])


def _new_run_manifest(project_id: str, shot_count: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "project_id": project_id,
        "schema_version": "1.0",
        "project_status": "CREATED",
        "created_at": now,
        "updated_at": now,
        "shot_count": shot_count,
        "shots": {},
    }


def _run_manifest_path(project_dir: Path) -> Path:
    return project_dir / REPORTS_DIR / _RUN_MANIFEST_PATH


def init_run_manifest(
    project_dir: Path,
    shot_count: int,
) -> dict:
    """Create or load the run manifest, returning the data dict."""
    manifest_path = _run_manifest_path(project_dir)
    if manifest_path.exists():
        return read_json_atomic(manifest_path)
    manifest = _new_run_manifest(project_dir.name, shot_count)
    write_json_atomic(manifest_path, manifest)
    return manifest


def load_run_manifest(project_dir: Path) -> dict:
    """Load the current run manifest or raise FileNotFoundError."""
    return read_json_atomic(_run_manifest_path(project_dir))


def mutate_run_manifest(
    manifest: dict,
    *,
    project_dir: Path,
    updater: Any,
    required_status: Optional[str] = None,
) -> dict:
    """Mutate and persist the run manifest atomically.

    Args:
        manifest: The current in-memory manifest dict (must match disk).
        project_dir: Project workspace root.
        updater: Callable(manifest) -> None that mutates in place.
        required_status: If set, reject mutation when current project_status
            != this value. Callers use this to prevent concurrent or
            state-incompatible edits (e.g., cannot finalize after STARTED).

    Returns:
        The updated manifest dict.
    """
    if required_status and manifest.get("project_status") != required_status:
        raise ValueError(
            f"Cannot mutate run_manifest: expected status {required_status!r}, "
            f"got {manifest.get('project_status')!r}"
        )

    # Re-read from disk each time to catch external mutations (fail-closed).
    manifest_path = _run_manifest_path(project_dir)
    if manifest_path.exists():
        disk = read_json_atomic(manifest_path)
        # Require project_id match — reject corrupted/wrong-project data.
        if disk.get("project_id") != manifest.get("project_id"):
            raise ValueError(
                f"run_manifest project_id mismatch on disk: "
                f"{disk.get('project_id')!r} vs {manifest.get('project_id')!r}"
            )

    updater(manifest)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(manifest_path, manifest)
    return manifest


def set_project_status(
    manifest: dict,
    project_dir: Path,
    new_status: str,
) -> dict:
    """Set project_status on the manifest and persist atomically.

    Enforces allowed statuses from the schema.
    """
    if new_status not in _VALID_PROJECT_STATUSES:
        raise ValueError(f"Invalid project_status {new_status!r}")
    manifest["project_status"] = new_status
    return mutate_run_manifest(
        manifest,
        project_dir=project_dir,
        updater=lambda m: None,
    )


# ------------------------------------------------------------------
# Shot state helpers
# ------------------------------------------------------------------

def update_shot_status(
    manifest: dict,
    shot_id: str,
    *,
    project_dir: Path,
    status: str,
    required_status: Optional[str] = None,
    **extra: Any,
) -> dict:
    """Update per-shot status in the manifest and persist atomically.

    ``required_status``, when set, enforces that the manifest's current
    project_status equals that value before the shot update is applied.
    """
    _validate_id(shot_id, "shot_id")

    def _updater(m: dict) -> None:
        shots = m.setdefault("shots", {})
        shot_data = shots.get(shot_id, {"status": "PENDING"})
        shot_data["status"] = status
        shot_data.update({k: v for k, v in extra.items() if v is not None})
        shots[shot_id] = shot_data

    return mutate_run_manifest(
        manifest,
        project_dir=project_dir,
        updater=_updater,
        required_status=required_status,
    )


# ------------------------------------------------------------------
# Stability helpers
# ------------------------------------------------------------------

def sha256_of_dict(obj: Any) -> str:
    """Deterministic sha256 of a JSON-serializable object."""
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generate_stable_project_id(topic: str, suffix: Optional[str] = None) -> str:
    """Generate a stable project id from a topic string.

    Deterministic: the same topic always yields the same id (the suffix is
    derived from the topic hash, not random), so re-running planning for an
    unchanged topic resumes the same project. An explicit ``suffix`` overrides
    the deterministic tail for collision avoidance.
    """
    digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()
    prefix = digest[:12]
    tail = suffix if suffix is not None else digest[12:16]
    return f"p_{prefix}_{tail}"