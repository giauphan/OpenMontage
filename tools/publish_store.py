from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from tools.storage.datastore_transport import (
    _decode_document,
    _env_value,
    _fields,
    _from_firestore_value,
    _load_service_account,
    _to_firestore_value,
)
from tools.system_media_utils import (
    _ffmpeg,
    existing_record_summary,
    file_sha256,
    media_fingerprint,
    normalize_identity,
    publish_key,
    uniqueness_key,
    utc_now,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/datastore"]
DEFAULT_COLLECTION = "openmontage_publish_state"


class PublishStore:
    """Manages persistent publish state, duplicate protection, and locks in Google Datastore."""

    @staticmethod
    def _is_precondition_conflict(response: Any) -> bool:
        if response.status_code in {409, 412}:
            return True
        if response.status_code == 400:
            try:
                return response.json().get("error", {}).get("status") == "FAILED_PRECONDITION"
            except (ValueError, TypeError, AttributeError):
                return False
        return False

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

    def reclaim_failed(self, key: str, data: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        """Conditionally reclaim the exact failed record; never overwrite a remote ID."""
        response = self.session.get(self._url(key), timeout=30)
        if response.status_code == 404:
            return False, None
        self._raise_for_error(response)
        document = response.json()
        existing = _decode_document(document)
        version = document.get("updateTime")
        if (existing.get("status") != "failed" or not version
                or existing.get("video_id") or existing.get("platform_id")):
            return False, existing
        for field in ("date", "topic", "platform", "account", "kind", "title", "source_topic", "asset_path", "source_sha256", "visual_sha256"):
            if field in data and existing.get(field) != data[field]:
                return False, existing
        update = {"status": data.get("status", "scheduling"), "updated_at": utc_now(), "retry_started_at": utc_now()}
        if data.get("scheduled_for"):
            update["scheduled_for"] = data["scheduled_for"]
        mask_fields = [*update, "error", "failed_at"]
        params = [("currentDocument.updateTime", version)] + [("updateMask.fieldPaths", field) for field in mask_fields]
        response = self.session.patch(self._url(key), params=params, json={"fields": _fields(update)}, timeout=30)
        if self._is_precondition_conflict(response):
            return False, existing
        self._raise_for_error(response)
        return True, existing

    def claim_instagram_reservation(self, key: str) -> tuple[bool, dict[str, Any] | None]:
        """Move a queued Instagram slot to uploading with a version precondition."""
        response = self.session.get(self._url(key), timeout=30)
        if response.status_code == 404:
            return False, None
        self._raise_for_error(response)
        document = response.json()
        existing = _decode_document(document)
        version = document.get("updateTime")
        if (existing.get("status") != "scheduling" or existing.get("platform") != "instagram"
                or not version or existing.get("video_id") or existing.get("platform_id")):
            return False, existing
        update = {"status": "uploading", "updated_at": utc_now(), "worker_started_at": utc_now()}
        params = [("currentDocument.updateTime", version)] + [("updateMask.fieldPaths", field) for field in update]
        response = self.session.patch(self._url(key), params=params, json={"fields": _fields(update)}, timeout=30)
        if self._is_precondition_conflict(response):
            return False, existing
        self._raise_for_error(response)
        return True, existing

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
                if candidate != key:
                    return key, False, existing
                claimed, snapshot = self.reclaim_failed(key, data)
                return key, claimed, snapshot or existing
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


__all__ = [
    "PublishStore",
    "SCOPES",
    "DEFAULT_COLLECTION",
    "_ffmpeg",
    "shutil",
    "utc_now",
    "publish_key",
    "normalize_identity",
    "file_sha256",
    "media_fingerprint",
    "uniqueness_key",
    "existing_record_summary",
    "_env_value",
    "_load_service_account",
    "_to_firestore_value",
    "_from_firestore_value",
    "_fields",
    "_decode_document",
    "AuthorizedSession",
    "Credentials",
]
