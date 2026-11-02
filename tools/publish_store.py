from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/datastore"]
DEFAULT_COLLECTION = "openmontage_publish_state"


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


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key.strip() != name:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        return val
    return None


def _load_service_account() -> dict[str, Any]:
    value = _env_value("FIREBASE_SERVICE_ACCOUNT")
    if not value:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT is missing in .env; add it or provide requested Firebase config.")

    text = value.strip()
    if text.startswith("file://"):
        text = text[7:]

    path = Path(text).expanduser()
    if path.is_file():
        info = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            info = json.loads(text)
        except json.JSONDecodeError:
            padding = "=" * (-len(text) % 4)
            try:
                info = json.loads(base64.b64decode(text + padding).decode("utf-8"))
            except Exception as exc:
                raise RuntimeError(
                    "FIREBASE_SERVICE_ACCOUNT must be service account JSON, base64 JSON, or a JSON file path."
                ) from exc

    if not info.get("project_id"):
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT has no project_id; provide valid Firebase service account config.")
    return info


def _to_firestore_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _to_firestore_value(v) for k, v in value.items() if v is not None}}}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_to_firestore_value(v) for v in value]}}
    return {"stringValue": str(value)}


def _from_firestore_value(value: dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "mapValue" in value:
        return {k: _from_firestore_value(v) for k, v in value.get("mapValue", {}).get("fields", {}).items()}
    if "arrayValue" in value:
        return [_from_firestore_value(v) for v in value.get("arrayValue", {}).get("values", [])]
    if "timestampValue" in value:
        return value["timestampValue"]
    if "nullValue" in value:
        return None
    return None


def _fields(data: dict[str, Any]) -> dict[str, Any]:
    return {k: _to_firestore_value(v) for k, v in data.items() if v is not None}


def _decode_document(document: dict[str, Any]) -> dict[str, Any]:
    return {k: _from_firestore_value(v) for k, v in document.get("fields", {}).items()}


class PublishStore:
    def __init__(self, collection: str = DEFAULT_COLLECTION):
        info = _load_service_account()
        credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
        self.session = AuthorizedSession(credentials)
        self.documents_url = (
            f"https://firestore.googleapis.com/v1/projects/{info['project_id']}"
            "/databases/(default)/documents"
        )
        self.base_url = f"{self.documents_url}/{collection}"
        self.commit_url = self.documents_url.rsplit("/documents", 1)[0] + "/documents:commit"

    def _url(self, key: str) -> str:
        return f"{self.base_url}/{quote(key, safe='')}"

    def _document_name(self, key: str) -> str:
        return self._url(key).split("https://firestore.googleapis.com/v1/", 1)[1]

    def get(self, key: str) -> dict[str, Any] | None:
        response = self.session.get(self._url(key), timeout=30)
        if response.status_code == 404:
            return None
        self._raise_for_error(response)
        return _decode_document(response.json())

    def create_once(self, key: str, data: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        response = self.session.patch(
            self._url(key),
            params={"currentDocument.exists": "false"},
            json={"fields": _fields(data)},
            timeout=30,
        )
        if 200 <= response.status_code < 300:
            return True, _decode_document(response.json())
        if response.status_code in {409, 412}:
            existing = self.get(key)
            if existing is not None:
                return False, existing
        self._raise_for_error(response)
        return False, None

    def create_many_once(self, documents: dict[str, dict[str, Any]]) -> bool:
        writes = [
            {
                "update": {
                    "name": self._document_name(key),
                    "fields": _fields(data),
                },
                "currentDocument": {"exists": False},
            }
            for key, data in documents.items()
        ]
        response = self.session.post(self.commit_url, json={"writes": writes}, timeout=30)
        if 200 <= response.status_code < 300:
            return True
        if response.status_code in {409, 412}:
            return False
        self._raise_for_error(response)
        return False

    def update(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in data.items() if v is not None}
        response = self.session.patch(
            self._url(key),
            params=[("updateMask.fieldPaths", field) for field in clean],
            json={"fields": _fields(clean)},
            timeout=30,
        )
        self._raise_for_error(response)
        return _decode_document(response.json())

    def _build_claim_documents(
        self,
        key: str,
        data: dict[str, Any],
        identities: dict[str, str],
        platform: str,
        account: str,
        kind: str,
    ) -> tuple[dict[str, Any], list[str]]:
        documents = {key: data}
        unique_keys = []
        for identity_type, value in identities.items():
            unique_key = uniqueness_key(platform, account, kind, identity_type, value)
            unique_keys.append(unique_key)
            documents[unique_key] = {
                "record_type": "uniqueness",
                "identity_type": identity_type,
                "identity_value": normalize_identity(value) if identity_type != "source" else value,
                "publish_key": key,
                **data,
            }
        return documents, unique_keys

    def _recover_failed_claim(self, documents: dict[str, Any]) -> None:
        for doc_key, doc_data in documents.items():
            try:
                self.update(doc_key, doc_data)
            except Exception:
                self.session.patch(
                    self._url(doc_key),
                    json={"fields": _fields(doc_data)},
                    timeout=30,
                )

    def _resolve_conflicting_claim(
        self,
        key: str,
        data: dict[str, Any],
        documents: dict[str, Any],
        candidates: list[str],
    ) -> tuple[str, bool, dict[str, Any]]:
        for candidate in candidates:
            existing = self.get(candidate)
            if existing is None:
                continue
            status = existing.get("status")
            if status in {"scheduled", "published", "scheduling"}:
                return key, False, existing
            if status == "failed":
                self._recover_failed_claim(documents)
                return key, True, data
            return key, False, existing
        raise RuntimeError("Firestore uniqueness claim failed without a conflicting record")

    def claim(
        self,
        *,
        date: str,
        topic: str,
        platform: str,
        account: str,
        kind: str,
        status: str,
        job: str | None = None,
        title: str | None = None,
        asset_path: str | None = None,
        source_topic: str | None = None,
        scheduled_for: str | None = None,
        content_hash: str | None = None,
        template_id: str | None = None,
    ) -> tuple[str, bool, dict[str, Any] | None]:
        if not title or not asset_path:
            raise ValueError("title and asset_path are required for duplicate protection")
        source_sha256 = file_sha256(asset_path)
        visual_sha256 = media_fingerprint(asset_path)
        resolved_source_topic = source_topic or topic
        identities = {
            "topic": topic,
            "title": title,
            "source_topic": resolved_source_topic,
            "source_path": str(Path(asset_path).resolve()),
            "source_visual": visual_sha256,
            "source": source_sha256,
        }
        now = utc_now()
        key = publish_key(date, topic, platform, kind)
        data = {
            "date": date,
            "topic": topic,
            "source_topic": resolved_source_topic,
            "platform": platform,
            "account": account,
            "kind": kind,
            "job": job,
            "title": title,
            "normalized_title": normalize_identity(title),
            "asset_path": str(asset_path),
            "source_sha256": source_sha256,
            "media_sha256": source_sha256,
            "visual_sha256": visual_sha256,
            "content_hash": content_hash,
            "template_id": template_id,
            "scheduled_for": scheduled_for,
            "status": status,
            "claimed_at": now,
            "updated_at": now,
        }

        documents, unique_keys = self._build_claim_documents(
            key, data, identities, platform, account, kind
        )

        if self.create_many_once(documents):
            return key, True, data
        return self._resolve_conflicting_claim(key, data, documents, [key, *unique_keys])

    def mark_scheduled(
        self,
        key: str,
        *,
        video_id: str | None,
        video_url: str | None,
        scheduled_for: str,
    ) -> dict[str, Any]:
        return self.update(
            key,
            {
                "status": "scheduled",
                "video_id": video_id,
                "video_url": video_url,
                "scheduled_for": scheduled_for,
                "scheduled_at": utc_now(),
                "updated_at": utc_now(),
            },
        )

    def mark_published(
        self,
        key: str,
        *,
        video_id: str | None = None,
        video_url: str | None = None,
        platform_id: str | None = None,
        published_at: str | None = None,
        verified_at: str | None = None,
        remote_status: dict[str, Any] | None = None,
        media_sha256: str | None = None,
    ) -> dict[str, Any]:
        update_data = {
            "status": "published",
            "video_id": video_id,
            "video_url": video_url,
            "platform_id": platform_id,
            "published_at": published_at or utc_now(),
            "updated_at": utc_now(),
        }
        if verified_at is not None:
            update_data["verified_at"] = verified_at
        if remote_status is not None:
            update_data["remote_status"] = remote_status
        if media_sha256 is not None:
            update_data["media_sha256"] = media_sha256
        return self.update(key, update_data)

    def mark_failed(self, key: str, error: str) -> dict[str, Any]:
        return self.update(
            key,
            {
                "status": "failed",
                "error": error[:1000],
                "failed_at": utc_now(),
                "updated_at": utc_now(),
            },
        )

    def _raise_for_error(self, response: Any) -> None:
        if 200 <= response.status_code < 300:
            return
        try:
            error = response.json().get("error", {})
            message = error.get("message") or response.text
        except Exception:
            message = response.text
        raise RuntimeError(f"Firestore publish state error {response.status_code}: {message}")
