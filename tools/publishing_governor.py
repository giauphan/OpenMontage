"""Publishing governor enforcing daily slot limits, spacing, CAS leases and idempotency."""
from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

class GovernorDecision(NamedTuple):
    allowed: bool
    reason: str
    reservation_id: str | None = None
    lease_token: str | None = None
    version: int = 0

class PublishingGovernor:
    def __init__(self, store=None):
        self.store = store
        self._lock = threading.Lock()
        self._memory_store: dict[str, dict[str, Any]] = {}

    def _scope_key(self, platform: str, account: str, local_date: str) -> str:
        return f"{platform}_{account}_{local_date}"

    def evaluate_and_reserve(
        self,
        *,
        platform: str,
        account: str,
        local_date: str,
        slot_time: str,
        rendition_id: str,
        worker_id: str,
        scheduled_for: datetime,
    ) -> GovernorDecision:
        if scheduled_for.tzinfo is None:
            raise ValueError("scheduled_for must be timezone-aware")

        with self._lock:
            scope = self._scope_key(platform, account, local_date)

            # Check daily quota (max 3 per scope)
            scope_entries = [
                d for d in self._memory_store.values()
                if d.get("scope") == scope and d.get("status") in ("reserved", "uploading", "scheduled", "published", "unknown")
            ]

            # Check idempotency for same rendition
            existing_rendition = next(
                (d for d in self._memory_store.values() if d.get("rendition_id") == rendition_id and d.get("scope") == scope),
                None
            )
            if existing_rendition:
                return GovernorDecision(
                    allowed=True,
                    reason="idempotent_existing_reservation",
                    reservation_id=existing_rendition["reservation_id"],
                    lease_token=None,
                    version=existing_rendition.get("version", 1),
                )

            if len(scope_entries) >= 3:
                return GovernorDecision(allowed=False, reason="daily_quota_exceeded_max_3")

            # Check 2h spacing between scheduled times
            for entry in scope_entries:
                existing_time = datetime.fromisoformat(entry["scheduled_for"])
                if abs(scheduled_for - existing_time) < timedelta(hours=2):
                    return GovernorDecision(allowed=False, reason="minimum_2h_spacing_violation")

            reservation_id = f"res_{platform}_{account}_{local_date}_{rendition_id}"
            lease_token = f"lease_{worker_id}_{int(datetime.now(timezone.utc).timestamp())}"

            doc = {
                "reservation_id": reservation_id,
                "scope": scope,
                "platform": platform,
                "account": account,
                "local_date": local_date,
                "slot_time": slot_time,
                "rendition_id": rendition_id,
                "scheduled_for": scheduled_for.isoformat(),
                "status": "reserved",
                "lease_token": lease_token,
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._memory_store[reservation_id] = doc
            return GovernorDecision(
                allowed=True,
                reason="reserved_ok",
                reservation_id=reservation_id,
                lease_token=lease_token,
                version=1,
            )

    def acquire_lease(self, reservation_id: str, worker_id: str, expected_version: int) -> GovernorDecision:
        with self._lock:
            doc = self._memory_store.get(reservation_id)
            if not doc:
                return GovernorDecision(allowed=False, reason="reservation_not_found")
            if doc.get("version") != expected_version:
                return GovernorDecision(allowed=False, reason="cas_version_conflict", version=doc.get("version", 0))
            if doc.get("status") != "reserved":
                return GovernorDecision(allowed=False, reason="invalid_status_for_lease", version=doc.get("version", 0))

            lease_token = f"lease_{worker_id}_{int(datetime.now(timezone.utc).timestamp())}"
            doc["lease_token"] = lease_token
            doc["status"] = "uploading"
            doc["version"] += 1
            doc["updated_at"] = datetime.now(timezone.utc).isoformat()
            return GovernorDecision(
                allowed=True,
                reason="lease_acquired",
                reservation_id=reservation_id,
                lease_token=lease_token,
                version=doc["version"],
            )

    def complete(self, reservation_id: str, lease_token: str, outcome: str, remote_id: str | None = None) -> bool:
        with self._lock:
            doc = self._memory_store.get(reservation_id)
            if not doc or doc.get("lease_token") != lease_token:
                return False
            doc["status"] = outcome
            if remote_id:
                doc["remote_id"] = remote_id
            doc["version"] += 1
            doc["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True
