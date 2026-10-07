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
import re
import tempfile
from contextlib import contextmanager
from copy import deepcopy
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
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
        raise ValueError(f"{label} {name!r} is unsafe")
    if name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError(f"{label} {name!r} is unsafe")
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

    if pipeline_type != "multi-shot":
        raise ValueError("pipeline_type must be 'multi-shot'")
    if project_dir.is_symlink():
        raise ValueError("unsafe project directory symlink")
    with project_lock(project_dir):
        marker_path = project_dir / "project.json"
        if marker_path.exists():
            marker = read_json_atomic(marker_path)
            if marker.get("project_id") != project_id or marker.get("pipeline_type") != pipeline_type:
                raise ValueError("project marker identity mismatch")
        else:
            init_project(project_id, title=title, pipeline_type=pipeline_type, pipeline_dir=base)
        for subdir in ("artifacts", "assets/images", "assets/video", "assets/audio", "assets/music", "renders", "history"):
            (project_dir / subdir).mkdir(parents=True, exist_ok=True)

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
    if not resolved.is_relative_to(project_dir.resolve()):
        raise ValueError(f"path escapes project dir: {path}")

    return resolved


# ------------------------------------------------------------------
# Atomic persistence
# ------------------------------------------------------------------

@contextmanager
def project_lock(project_dir: Path, timeout: float = 10.0):
    """Bounded cross-process mutation lock, released by the OS after a crash.

    Lock files are intentionally retained: unlinking a lock file can allow two
    processes to lock different inodes. This lock is not reentrant.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_dir / ".multishot.lock", "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Project mutation lock busy: {project_dir}")
                time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_record_path(path: Path, data: Any) -> None:
    from schemas.multishot import MULTISHOT_ARTIFACT_NAMES
    from schemas.artifacts import validate_artifact
    if path.suffix == ".json" and path.stem in MULTISHOT_ARTIFACT_NAMES:
        validate_artifact(path.stem, data)


def write_artifact(project_dir: Path, name: str, data: dict) -> Path:
    """Persist a registered supporting record to canonical artifacts/.

    Checkpoint payloads remain inline objects, not filename references. This
    operation never advances stages or grants approval.
    """
    from schemas.artifacts import ARTIFACT_NAMES, validate_artifact
    if name not in ARTIFACT_NAMES:
        raise ValueError(f"Unknown artifact {name!r}")
    validate_artifact(name, data)
    path = project_dir / "artifacts" / f"{name}.json"
    with project_lock(project_dir):
        write_json_atomic(path, data)
    return path


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to path atomically (temp + rename + fsync).

    Raises on failure; the destination is either the new file or nothing.
    """
    _validate_record_path(path, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=f".tmp_{path.name}_", dir=path.parent)
    tmp = Path(filename)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def read_json_atomic(path: Path) -> Any:
    """Read a JSON file; raises FileNotFoundError if absent, json.JSONDecodeError otherwise."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _validate_record_path(path, data)
    return data


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
        "revision": 0,
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
    with project_lock(project_dir):
        manifest_path = _run_manifest_path(project_dir)
        if manifest_path.exists():
            manifest = load_run_manifest(project_dir)
            if manifest["shot_count"] != shot_count:
                raise ValueError("run_manifest shot_count mismatch")
            return manifest
        manifest = _new_run_manifest(project_dir.name, shot_count)
        write_json_atomic(manifest_path, manifest)
        return manifest


def load_run_manifest(project_dir: Path) -> dict:
    """Load the current run manifest or raise FileNotFoundError."""
    manifest = read_json_atomic(_run_manifest_path(project_dir))
    if manifest["project_id"] != project_dir.name:
        raise ValueError("run_manifest project_id mismatch")
    return manifest


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
    with project_lock(project_dir):
        disk = load_run_manifest(project_dir)
        if disk != manifest:
            raise ValueError("Stale run_manifest snapshot; reload before mutation")
        if required_status and disk["project_status"] != required_status:
            raise ValueError(f"Cannot mutate run_manifest: expected status {required_status!r}")
        updated = deepcopy(disk)
        updater(updated)
        if updated.get("project_id") != disk["project_id"]:
            raise ValueError("run_manifest project_id is immutable")
        updated["revision"] = disk.get("revision", 0) + 1
        updated["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(_run_manifest_path(project_dir), updated)
        manifest.clear()
        manifest.update(updated)
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
    return mutate_run_manifest(
        manifest,
        project_dir=project_dir,
        updater=lambda m: m.update(project_status=new_status),
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
