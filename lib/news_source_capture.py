"""Bounded, review-pending capture of explicitly allowlisted HTTPS sources.

Public API: ``capture_source(project_dir, url, allowed_hosts) -> dict``.
The private ``_transport`` hook is for network-free contract tests only. It is
trusted test code and bypasses production DNS/socket/TLS controls.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import multiprocessing
import os

import re
import secrets
import socket
import ssl
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

MAX_BYTES = 2_000_000
MAX_WALL_SECONDS = 20
WORKER_CLEANUP_GRACE_SECONDS = 0.5
MAX_REDIRECTS = 3
MAX_TEXT_CHARS = 500_000
OUTPUT_DIR = Path("artifacts/news_source_capture")
_ALLOWED_TYPES = {"text/html", "text/plain"}
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.ASCII)


class CaptureError(ValueError):
    """Invalid, unsafe, or unavailable source capture."""


class CapturePersistenceError(CaptureError):
    """Persistence stopped after immutable partial artifacts were retained."""

    def __init__(self, message: str, partial_artifacts: list[str]):
        super().__init__(message)
        self.partial_artifacts = partial_artifacts


class _ArtifactPersistenceError(OSError):
    def __init__(self, staged_name: str, cause: OSError):
        super().__init__(str(cause))
        self.staged_name = staged_name


def _canonical_host(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise CaptureError("allowed host must be a bare hostname or IP address")
    if value.endswith(".") or "/" in value or "\\" in value or "@" in value or "%" in value:
        raise CaptureError("allowed host must be a bare hostname or IP address")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not value.isascii() or len(value) > 253:
        raise CaptureError("allowed host must be an ASCII DNS name")
    host = value.lower()
    if any(not _LABEL.fullmatch(label) for label in host.split(".")):
        raise CaptureError("allowed host must be a valid bare DNS name")
    return host


def _host_url(url: str, allowed_hosts: set[str]) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 or ord(c) == 127 for c in url) or "\\" in url:
        raise CaptureError("URL must be a bounded string without controls")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise CaptureError("malformed URL") from exc
    if parts.scheme.lower() != "https" or not host or parts.username is not None or parts.password is not None:
        raise CaptureError("only credential-free HTTPS URLs are allowed")
    if port not in (None, 443):
        raise CaptureError("only HTTPS port 443 is allowed")
    host = _canonical_host(host)
    if host not in allowed_hosts:
        raise CaptureError("URL host is not explicitly allowlisted")
    if parts.fragment:
        raise CaptureError("URL fragments are not accepted")
    authority = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", authority, parts.path or "/", parts.query, "")), host


def _validated_addresses(host: str) -> list[str]:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CaptureError("DNS lookup failed") from exc
    addresses: list[str] = []
    for answer in answers:
        try:
            ip = ipaddress.ip_address(str(answer[4][0]).split("%", 1)[0])
        except ValueError as exc:
            raise CaptureError("DNS returned an invalid address") from exc
        if not ip.is_global:
            raise CaptureError("host resolves to a non-public IP address")
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise CaptureError("host has no usable public address")
    return addresses


def _request_pinned(url: str, host: str) -> tuple[int, dict[str, str], bytes, str | None]:
    """One direct HTTPS request, connecting only to a validated resolved IP."""
    addresses = _validated_addresses(host)
    sock = None
    last_error: OSError | None = None
    for address in addresses:
        try:
            sock = socket.create_connection((address, 443), timeout=MAX_WALL_SECONDS)
            break
        except OSError as exc:
            last_error = exc
    if sock is None:
        raise CaptureError("could not connect to validated public address") from last_error
    tls_sock = None
    try:
        tls_sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        parts = urlsplit(url)
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            path += "?" + quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        host_header = f"[{host}]" if ":" in host else host
        request = (f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\n"
                   "User-Agent: OpenMontage-News-Capture/1.0\r\nAccept: text/html, text/plain\r\n"
                   "Accept-Encoding: identity\r\nConnection: close\r\n\r\n")
        tls_sock.sendall(request.encode("ascii"))
        response = http.client.HTTPResponse(tls_sock)
        response.begin()
        header_items = response.getheaders()
        if len(header_items) > 100 or sum(len(key) + len(value) for key, value in header_items) > 65_536:
            raise CaptureError("response headers exceed maximum size")
        headers = {key.lower(): value for key, value in header_items}
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise CaptureError("encoded responses are not accepted")
        length = headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
            raise CaptureError("response exceeds maximum size")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise CaptureError("response exceeds maximum size")
        return response.status, headers, body, headers.get("location")
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise CaptureError("HTTPS source request failed") from exc
    finally:
        try:
            (tls_sock or sock).close()
        except OSError:
            pass


def _worker_entry(connection: Any, url: str, host: str, result_path: str) -> None:
    try:
        status, headers, body, location = _request_pinned(url, host)
        metadata = json.dumps([status, headers, location], separators=(",", ":")).encode("utf-8")
        if len(metadata) > 65_536:
            raise CaptureError("response metadata exceeds maximum size")
        with open(result_path, "wb") as stream:
            stream.write(len(metadata).to_bytes(4, "big"))
            stream.write(metadata)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        connection.send_bytes(b"OK")
    except (OSError, ValueError, TypeError) as exc:
        try:
            connection.send_bytes((f"ERR:{type(exc).__name__}: {exc}").encode("utf-8", errors="replace")[:4096])
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _supervise_worker(target: Callable[..., None], args: tuple[Any, ...], deadline: float) -> Any:
    """Watch a spawned worker; large body data stays off the control pipe."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(child, *args), daemon=True)
    started = False
    try:
        process.start()
        started = True
        child.close()
        remaining = max(0.0, deadline - WORKER_CLEANUP_GRACE_SECONDS - time.monotonic())
        if not parent.poll(remaining):
            raise CaptureError(f"source capture exceeded {MAX_WALL_SECONDS}s wall-time limit")
        try:
            payload = parent.recv_bytes(4096)
        except (EOFError, OSError) as exc:
            raise CaptureError("source worker exited without a complete result") from exc
        process.join(max(0.0, deadline - WORKER_CLEANUP_GRACE_SECONDS - time.monotonic()))
        if process.is_alive():
            raise CaptureError("source worker did not exit before deadline")
        return payload
    except CaptureError:
        raise
    except (OSError, EOFError, BrokenPipeError, AssertionError) as exc:
        raise CaptureError(f"source worker failed: {exc}") from exc
    finally:
        parent.close()
        child.close()
        if started and process.is_alive():
            process.terminate()
            process.join(WORKER_CLEANUP_GRACE_SECONDS / 2)
        if started and process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(WORKER_CLEANUP_GRACE_SECONDS / 2)


def _bounded_request(url: str, host: str, deadline: float) -> tuple[int, dict[str, str], bytes, str | None]:
    """Run DNS, connect, TLS, headers, and body under the capture wall deadline."""
    descriptor, body_path = tempfile.mkstemp(prefix="openmontage-news-capture-")
    os.close(descriptor)
    try:
        signal = _supervise_worker(_worker_entry, (url, host, body_path), deadline)
        if signal != b"OK":
            raise CaptureError(signal.decode("utf-8", errors="replace").removeprefix("ERR:"))
        if time.monotonic() > deadline:
            raise CaptureError(f"source capture exceeded {MAX_WALL_SECONDS}s wall-time limit")
        body_size = os.path.getsize(body_path)
        if body_size > MAX_BYTES + 65_540:
            raise CaptureError("response envelope exceeds maximum size")
        with open(body_path, "rb") as stream:
            prefix = stream.read(4)
            if len(prefix) != 4:
                raise CaptureError("source worker returned incomplete response metadata")
            metadata_size = int.from_bytes(prefix, "big")
            if metadata_size > 65_536:
                raise CaptureError("response metadata exceeds maximum size")
            metadata = json.loads(stream.read(metadata_size).decode("utf-8"))
            body = stream.read(MAX_BYTES + 1)
        if len(body) != body_size - 4 - metadata_size:
            raise CaptureError("source worker returned an incomplete response body")
        if len(body) > MAX_BYTES:
            raise CaptureError("response exceeds maximum size")
        if time.monotonic() > deadline:
            raise CaptureError(f"source capture exceeded {MAX_WALL_SECONDS}s wall-time limit")
        status, headers, location = metadata
        return status, headers, body, location
    except CaptureError:
        raise
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CaptureError(f"cannot read bounded worker result: {exc}") from exc
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


class _HTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"og:title", "twitter:title", "article:published_time", "date", "pubdate", "article:modified_time"} and values.get("content"):
                self.meta.setdefault(key, values["content"].strip())
        if tag.lower() == "title":
            self._title = True
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._title = False
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._title:
            self.title_parts.append(data)
        if not self._skip:
            text = " ".join(data.split())
            if text:
                self.text_parts.append(text)


def _interpret_date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _extract(body: bytes, content_type: str) -> dict[str, Any]:
    charset_match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        decoded = body.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise CaptureError("source content cannot be decoded using its declared or default charset") from exc
    if content_type.split(";", 1)[0].strip().lower() == "text/plain":
        title = None
        text = decoded
        raw_dates: dict[str, str | None] = {}
    else:
        parser = _HTMLExtractor()
        parser.feed(decoded)
        title = " ".join("".join(parser.title_parts).split()) or parser.meta.get("og:title") or parser.meta.get("twitter:title") or None
        text = "\n".join(parser.text_parts)
        raw_dates = {
            "article:published_time": parser.meta.get("article:published_time"),
            "date": parser.meta.get("date"),
            "pubdate": parser.meta.get("pubdate"),
            "article:modified_time": parser.meta.get("article:modified_time"),
        }
    if len(text) > MAX_TEXT_CHARS:
        raise CaptureError(f"extracted text exceeds {MAX_TEXT_CHARS} characters; capture rejected without truncation")
    raw_published = next((raw_dates.get(key) for key in ("article:published_time", "date", "pubdate") if raw_dates.get(key) is not None), None)
    raw_updated = raw_dates.get("article:modified_time")
    return {
        "title": title,
        "text": text,
        "excerpt": text[:500],
        "published_at": _interpret_date(raw_published),
        "published_at_raw": raw_published,
        "published_at_source_key": next((key for key in ("article:published_time", "date", "pubdate") if raw_dates.get(key) is not None), None),
        "updated_at": _interpret_date(raw_updated),
        "updated_at_raw": raw_updated,
        "updated_at_source_key": "article:modified_time" if raw_updated is not None else None,
        "date_metadata_raw": raw_dates,
    }


def _safe_directory(root: Path) -> Path:
    root = root.resolve(strict=True)
    current = root
    for part in OUTPUT_DIR.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise CaptureError("capture output path contains a symlink or non-directory")
        else:
            current.mkdir()
    current.resolve(strict=True).relative_to(root)
    return current


def _publish_artifact(path: Path, data: bytes) -> str | None:
    """Write to a unique sibling, then publish atomically without replacement.

    A failed staged write is retained under its unique temporary name and
    returned to the caller for accurate failure reporting. The destination is
    visible only after all bytes have been flushed and fsynced.
    """
    staged = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(staged, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise _ArtifactPersistenceError(staged.name, exc) from exc
    try:
        os.link(staged, path)
    except OSError as exc:
        raise _ArtifactPersistenceError(staged.name, exc) from exc
    try:
        os.unlink(staged)
    except OSError:
        # The complete final artifact is already immutably published; a
        # redundant complete staging link is not a failed capture.
        pass
    return None


def capture_source(
    project_dir: str | Path,
    url: str,
    allowed_hosts: set[str] | list[str] | tuple[str, ...],
    *,
    _transport: Callable[[str, str], tuple[int, dict[str, str], bytes, str | None]] | None = None,
) -> dict[str, Any]:
    """Capture one allowlisted HTTPS source for pending editorial review."""
    if not isinstance(allowed_hosts, (set, list, tuple)) or not allowed_hosts:
        raise CaptureError("an explicit non-empty allowed_hosts collection is required")
    allowed = {_canonical_host(item) for item in allowed_hosts}
    root = Path(project_dir)
    if root.is_symlink() or not root.is_dir():
        raise CaptureError("project_dir must be an existing non-symlink directory")
    root = root.resolve(strict=True)
    first_url, _ = _host_url(url, allowed)
    current = first_url
    chain = [current]
    deadline = time.monotonic() + MAX_WALL_SECONDS
    for hop in range(MAX_REDIRECTS + 1):
        _, host = _host_url(current, allowed)
        if _transport is None:
            status, headers, body, location = _bounded_request(current, host, deadline)
        else:
            status, headers, body, location = _transport(current, host)
            headers = {str(key).lower(): str(value) for key, value in headers.items()}
            if not isinstance(body, bytes) or len(body) > MAX_BYTES:
                raise CaptureError("test transport returned invalid or oversized body")
        if status in {301, 302, 303, 307, 308}:
            if hop >= MAX_REDIRECTS or not location:
                raise CaptureError("redirect limit exceeded or missing redirect location")
            target, _ = _host_url(urljoin(current, location), allowed)
            if target in chain:
                raise CaptureError("redirect loop")
            chain.append(target)
            current = target
            continue
        if status != 200:
            raise CaptureError(f"source returned HTTP status {status}")
        content_type_header = headers.get("content-type", "")
        content_type = content_type_header.split(";", 1)[0].strip().lower()
        if content_type not in _ALLOWED_TYPES:
            raise CaptureError("unsupported content type")
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise CaptureError("encoded responses are not accepted")
        if len(body) > MAX_BYTES:
            raise CaptureError("response exceeds maximum size")
        break
    else:
        raise CaptureError("redirect limit exceeded")

    extracted = _extract(body, content_type_header)
    if not extracted["text"].strip():
        raise CaptureError("source contains no extractable text")
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out_dir = _safe_directory(root)
    capture_id = f"{hashlib.sha256(first_url.encode('utf-8')).hexdigest()[:16]}-{secrets.token_hex(8)}"
    raw_name = f"{capture_id}.raw"
    extracted_name = f"{capture_id}.extracted.json"
    record_name = f"{capture_id}.provenance.json"
    raw_hash = hashlib.sha256(body).hexdigest()
    extracted_bytes = (json.dumps(extracted, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    extracted_hash = hashlib.sha256(extracted_bytes).hexdigest()
    record = {
        "version": "1.0", "capture_id": capture_id, "status": "pending_editorial_review", "original_url": first_url,
        "final_url": current, "redirect_chain": chain, "retrieved_at": retrieved_at,
        "content_type": content_type, "raw_file": raw_name, "raw_sha256": raw_hash,
        "extracted_file": extracted_name, "extracted_sha256": extracted_hash,
        "published_at": extracted["published_at"], "updated_at": extracted["updated_at"],
        "published_at_raw": extracted["published_at_raw"], "published_at_source_key": extracted["published_at_source_key"],
        "updated_at_raw": extracted["updated_at_raw"], "updated_at_source_key": extracted["updated_at_source_key"],
        "date_metadata_raw": extracted["date_metadata_raw"], "excerpt": extracted["excerpt"], "review_status": "pending",
        "provenance_file": record_name, "capture_dir": OUTPUT_DIR.as_posix(),
        "rights_attribution_notes": "Not assessed by capture; editorial review required.",
    }
    record_bytes = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    partial: list[str] = []
    try:
        _publish_artifact(out_dir / raw_name, body)
        partial.append(raw_name)
        _publish_artifact(out_dir / extracted_name, extracted_bytes)
        partial.append(extracted_name)
        _publish_artifact(out_dir / record_name, record_bytes)
        partial.append(record_name)
    except Exception as exc:
        staged_name = exc.staged_name if isinstance(exc, _ArtifactPersistenceError) else None
        retained = partial + ([staged_name] if staged_name else [])
        raise CapturePersistenceError(
            f"capture persistence failed; retained published/staged artifacts {retained!r}; no ready provenance is reported: {exc}",
            partial_artifacts=retained,
        ) from exc
    return record
