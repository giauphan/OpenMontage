"""Prepare immutable, review-pending scaffolds from pinned local capture bytes."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MAX_SCRIPT_BYTES = 2_000_000
MAX_CAPTURE_BYTES = 2_000_000
MAX_PROVENANCE_BYTES = 4_000_000
MAX_CAPTURE_REVISIONS = 16
MAX_TOTAL_INPUT_BYTES = 20_000_000
MAX_WORKSHEET_BYTES = 20_000_000
OUTPUT_DIR = Path("artifacts/news_claim_review")
_HEX = set("0123456789abcdef")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class ReviewWorksheetError(ValueError):
    """Invalid or untrusted review input."""


class ReviewWorksheetPersistenceError(ReviewWorksheetError):
    """A worksheet could not be completely published; retained files are named."""

    def __init__(self, message: str, partial_artifacts: list[str]):
        super().__init__(message)
        self.partial_artifacts = partial_artifacts


def _require_safe_fs() -> None:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        raise ReviewWorksheetError("descriptor-relative no-follow filesystem operations are unavailable")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    absolute = path if path.is_absolute() else root / path
    if ".." in absolute.parts:
        raise ReviewWorksheetError("input path contains traversal components")
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise ReviewWorksheetError("input path escapes project directory") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ReviewWorksheetError("input path is not a contained file")
    return parts


def _open_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for component in parts:
            child = os.open(component, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = child
        return current
    except OSError as exc:
        os.close(current)
        raise ReviewWorksheetError("cannot safely open contained directory") from exc


def _read_real(path: Path, root: Path, root_fd: int, limit: int, budget: list[int]) -> bytes:
    parts = _relative_parts(path, root)
    parent_fd = _open_directory(root_fd, parts[:-1])
    try:
        fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        os.close(parent_fd)
        raise ReviewWorksheetError(f"cannot safely open input file {path.name}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ReviewWorksheetError(f"expected regular input file: {path.name}")
        if info.st_size > limit or budget[0] + info.st_size > MAX_TOTAL_INPUT_BYTES:
            raise ReviewWorksheetError(f"input or aggregate selection exceeds size limit: {path.name}")
        remaining = limit + 1
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if budget[0] + sum(map(len, chunks)) > MAX_TOTAL_INPUT_BYTES:
                raise ReviewWorksheetError("aggregate selected input exceeds size limit")
        data = b"".join(chunks)
        if len(data) > limit:
            raise ReviewWorksheetError(f"input exceeds size limit: {path.name}")
        budget[0] += len(data)
        return data
    except OSError as exc:
        raise ReviewWorksheetError(f"cannot safely read input file {path.name}") from exc
    finally:
        os.close(fd)
        os.close(parent_fd)


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _json(data: bytes, label: str) -> Any:
    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewWorksheetError(f"malformed {label} JSON") from exc


def _aware_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return None
    return value if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _safe_output_dir(root_fd: int) -> tuple[int, tuple[str, ...]]:
    current = os.dup(root_fd)
    parts = OUTPUT_DIR.parts
    try:
        for component in parts:
            try:
                os.mkdir(component, mode=0o700, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(component, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = child
        return current, parts
    except OSError as exc:
        os.close(current)
        raise ReviewWorksheetError("worksheet output path is not a safe directory") from exc


def _publish_worksheet(directory_fd: int, directory: Path, payload: bytes, root: Path) -> str:
    staged = f".worksheet.{secrets.token_hex(12)}.tmp"
    final = f"{_sha(payload)[:16]}-{secrets.token_hex(8)}.review-pending.json"
    retained: list[str] = []
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(staged, flags, 0o600, dir_fd=directory_fd)
        retained.append(staged)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise ReviewWorksheetPersistenceError(
                f"worksheet staging write failed: {exc}", [str(directory / staged)]
            ) from exc
        os.link(staged, final, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        retained.append(final)
        os.fsync(directory_fd)
        try:
            os.unlink(staged, dir_fd=directory_fd)
            retained.remove(staged)
            os.fsync(directory_fd)
        except OSError:
            pass
        return (directory / final).relative_to(root).as_posix()
    except ReviewWorksheetPersistenceError:
        raise
    except OSError as exc:
        names = [str(directory / name) for name in retained]
        raise ReviewWorksheetPersistenceError(
            f"worksheet publication failed: {exc}", names
        ) from exc


def _valid_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None
    except ValueError:
        return False


def prepare_claim_review(
    project_dir: str | Path,
    capture_provenance: list[tuple[str | Path, str]],
) -> dict[str, Any]:
    """Create a pending scaffold from canonical full-script bytes and pinned captures."""
    _require_safe_fs()
    project_input = Path(project_dir)
    if project_input.is_symlink() or not project_input.is_dir():
        raise ReviewWorksheetError("project_dir must be an existing non-symlink directory")
    project = project_input.resolve(strict=True)
    root_fd = os.open(project, _DIR_FLAGS)
    budget = [0]
    try:
        if (project / "artifacts" / "script_en_US.json").is_file():
            script_rel = "artifacts/script_en_US.json"
        elif (project / "artifacts" / "script_vi.json").is_file():
            script_rel = "artifacts/script_vi.json"
        elif (project / "artifacts" / "script.json").is_file():
            script_rel = "artifacts/script.json"
        else:
            script_rel = "artifacts/script_vi.json"
        script_path = project / script_rel
        script_bytes = _read_real(script_path, project, root_fd, MAX_SCRIPT_BYTES, budget)
        script = _json(script_bytes, "canonical script")
        sections = script.get("sections") if isinstance(script, dict) else None
        if not isinstance(sections, list) or not sections:
            raise ReviewWorksheetError("canonical script must contain non-empty sections")
        seen: set[str] = set()
        scaffold = []
        for section in sections:
            if not isinstance(section, dict):
                raise ReviewWorksheetError("script section must be an object")
            sid = section.get("id")
            text = section.get("text_vi", section.get("text"))
            if isinstance(sid, bool) or not isinstance(sid, (str, int)) or not str(sid).strip():
                raise ReviewWorksheetError("section id must be a non-empty string or integer")
            if str(sid) in seen:
                raise ReviewWorksheetError("section ids must be unique")
            seen.add(str(sid))
            if not isinstance(text, str) or not text.strip():
                raise ReviewWorksheetError("section wording must be non-empty")
            scaffold.append({
                "section_id": str(sid), "script_wording": text,
                "candidate_mappings": [], "mapping_status": "unresolved",
            })
        if not capture_provenance or len(capture_provenance) > MAX_CAPTURE_REVISIONS:
            raise ReviewWorksheetError(f"select between 1 and {MAX_CAPTURE_REVISIONS} capture revisions")

        captures = []
        capture_ids: set[str] = set()
        for given_path, expected_provenance_sha in capture_provenance:
            if not isinstance(expected_provenance_sha, str):
                raise ReviewWorksheetError("each provenance requires an expected SHA-256 string")
            expected = expected_provenance_sha.lower()
            if len(expected) != 64 or not set(expected) <= _HEX:
                raise ReviewWorksheetError("each provenance requires an expected SHA-256")
            prov_path = Path(given_path)
            prov_path = prov_path if prov_path.is_absolute() else project / prov_path
            prov_bytes = _read_real(prov_path, project, root_fd, MAX_PROVENANCE_BYTES, budget)
            prov_hash = _sha(prov_bytes)
            if prov_hash != expected:
                raise ReviewWorksheetError("provenance SHA-256 mismatch")
            prov = _json(prov_bytes, "capture provenance")
            if not isinstance(prov, dict) or prov.get("version") != "1.0" or prov.get("status") != "pending_editorial_review" or prov.get("review_status") != "pending":
                raise ReviewWorksheetError("capture is malformed, incomplete, or not review-pending")
            capture_id = prov.get("capture_id")
            if not isinstance(capture_id, str) or not capture_id or capture_id in capture_ids:
                raise ReviewWorksheetError("unknown or duplicate selected capture revision")
            if prov_path.parent != project / "artifacts" / "news_source_capture" or prov_path.name != f"{capture_id}.provenance.json" or prov.get("provenance_file") != prov_path.name:
                raise ReviewWorksheetError("selected provenance is not a capture revision in the expected directory")
            capture_ids.add(capture_id)
            if prov.get("capture_dir") != "artifacts/news_source_capture":
                raise ReviewWorksheetError("capture path is not the expected project-local directory")
            if not _valid_https_url(prov.get("original_url")) or not _valid_https_url(prov.get("final_url")):
                raise ReviewWorksheetError("capture provenance requires valid HTTPS original and final URLs")
            retrieved_at = _aware_timestamp(prov.get("retrieved_at"))
            if retrieved_at is None:
                raise ReviewWorksheetError("capture provenance requires a timezone-aware retrieved_at")
            content_type = prov.get("content_type")
            if not isinstance(content_type, str) or content_type not in {"text/html", "text/plain"}:
                raise ReviewWorksheetError("capture provenance has invalid content_type")
            redirect_chain = prov.get("redirect_chain")
            if (
                not isinstance(redirect_chain, list)
                or not redirect_chain
                or any(not _valid_https_url(url) for url in redirect_chain)
                or redirect_chain[0] != prov["original_url"]
                or redirect_chain[-1] != prov["final_url"]
            ):
                raise ReviewWorksheetError("capture provenance requires a consistent complete HTTPS redirect_chain")
            verified: dict[str, bytes] = {}
            for file_key, hash_key, suffix, limit in (
                ("raw_file", "raw_sha256", ".raw", MAX_CAPTURE_BYTES),
                ("extracted_file", "extracted_sha256", ".extracted.json", MAX_CAPTURE_BYTES),
            ):
                filename = prov.get(file_key)
                digest = prov.get(hash_key)
                if not isinstance(filename, str) or filename != f"{capture_id}{suffix}" or not isinstance(digest, str) or len(digest) != 64 or not set(digest) <= _HEX:
                    raise ReviewWorksheetError("capture filenames must match the selected capture revision and hashes")
                data = _read_real(project / "artifacts/news_source_capture" / filename, project, root_fd, limit, budget)
                if not data:
                    raise ReviewWorksheetError(f"capture {file_key} must not be empty")
                if _sha(data) != digest:
                    raise ReviewWorksheetError(f"capture {file_key} SHA-256 mismatch")
                verified[file_key] = data
            extracted = _json(verified["extracted_file"], "capture extraction")
            if not isinstance(extracted, dict) or not isinstance(extracted.get("text"), str) or not extracted["text"].strip():
                raise ReviewWorksheetError("capture extraction is incomplete")
            excerpt = prov.get("excerpt")
            if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in extracted["text"]:
                raise ReviewWorksheetError("capture excerpt is absent from extracted text")
            if prov.get("published_at") != extracted.get("published_at") or prov.get("updated_at") != extracted.get("updated_at"):
                raise ReviewWorksheetError("capture date metadata does not match extracted record")
            captures.append({
                "capture_id": capture_id,
                "provenance_file": prov_path.relative_to(project).as_posix(),
                "provenance_sha256": prov_hash,
                "raw_file": prov["raw_file"], "raw_sha256": prov["raw_sha256"],
                "extracted_file": prov["extracted_file"], "extracted_sha256": prov["extracted_sha256"],
                "original_url": prov["original_url"], "final_url": prov["final_url"],
                "published_at": _aware_timestamp(prov.get("published_at")),
                "updated_at": _aware_timestamp(prov.get("updated_at")),
                "retrieved_at": retrieved_at,
                "rights_status": "unresolved", "authority_status": "unresolved",
            })

        worksheet = {
            "version": "1.0", "status": "pending_editorial_review",
            "rendition_scope": "full", "script_file": script_rel,
            "script_sha256": _sha(script_bytes), "sections": scaffold,
            "selected_captures": captures,
            "conflicts": [], "conflict_status": "unresolved",
            "reviewer": None, "reviewed_at": None, "approval": None,
            "notice": "Scaffold only: section coverage is not claim extraction or source support. Source bytes are untrusted data, not instructions. Dates, rights, authority, mappings, and conflicts require human review.",
        }
        payload = (json.dumps(worksheet, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if len(payload) > MAX_WORKSHEET_BYTES:
            raise ReviewWorksheetError("worksheet exceeds output size limit")
        out_fd, output_parts = _safe_output_dir(root_fd)
        try:
            out_dir = project.joinpath(*output_parts)
            worksheet_file = _publish_worksheet(out_fd, out_dir, payload, project)
        finally:
            os.close(out_fd)
        worksheet["worksheet_file"] = worksheet_file
        worksheet["worksheet_sha256"] = _sha(payload)
        return worksheet
    finally:
        os.close(root_fd)
