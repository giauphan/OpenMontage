"""Tests for publishing governor quota, spacing, CAS lease, and idempotency."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from tools.publishing_governor import PublishingGovernor, GovernorDecision

def test_daily_cap_allows_three_and_rejects_fourth():
    gov = PublishingGovernor()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    local_date = "2026-10-13"

    for i in range(3):
        scheduled = datetime(2026, 10, 13, 9 + (i * 3), 15, tzinfo=tz)
        decision = gov.evaluate_and_reserve(
            platform="youtube",
            account="primary",
            local_date=local_date,
            slot_time=f"{9 + (i * 3):02d}:15",
            rendition_id=f"rend_{i}",
            worker_id="w1",
            scheduled_for=scheduled,
        )
        assert decision.allowed is True

    # Fourth attempt on same local day/platform/account should exceed quota
    scheduled_4 = datetime(2026, 10, 13, 22, 15, tzinfo=tz)
    dec_4 = gov.evaluate_and_reserve(
        platform="youtube",
        account="primary",
        local_date=local_date,
        slot_time="22:15",
        rendition_id="rend_3",
        worker_id="w1",
        scheduled_for=scheduled_4,
    )
    assert dec_4.allowed is False
    assert dec_4.reason == "daily_quota_exceeded_max_3"


def test_two_hour_spacing_violation():
    gov = PublishingGovernor()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    local_date = "2026-10-13"

    t1 = datetime(2026, 10, 13, 9, 15, tzinfo=tz)
    d1 = gov.evaluate_and_reserve(
        platform="youtube",
        account="primary",
        local_date=local_date,
        slot_time="09:15",
        rendition_id="rend_1",
        worker_id="w1",
        scheduled_for=t1,
    )
    assert d1.allowed is True

    # 1 hour later (violates 2h spacing)
    t2 = datetime(2026, 10, 13, 10, 15, tzinfo=tz)
    d2 = gov.evaluate_and_reserve(
        platform="youtube",
        account="primary",
        local_date=local_date,
        slot_time="10:15",
        rendition_id="rend_2",
        worker_id="w1",
        scheduled_for=t2,
    )
    assert d2.allowed is False
    assert d2.reason == "minimum_2h_spacing_violation"


def test_idempotent_rendition():
    gov = PublishingGovernor()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    t1 = datetime(2026, 10, 13, 9, 15, tzinfo=tz)

    d1 = gov.evaluate_and_reserve(
        platform="youtube",
        account="primary",
        local_date="2026-10-13",
        slot_time="09:15",
        rendition_id="same_rend",
        worker_id="w1",
        scheduled_for=t1,
    )
    assert d1.allowed is True

    # Same rendition ID repeated
    d2 = gov.evaluate_and_reserve(
        platform="youtube",
        account="primary",
        local_date="2026-10-13",
        slot_time="09:15",
        rendition_id="same_rend",
        worker_id="w2",
        scheduled_for=t1,
    )
    assert d2.allowed is True
    assert d2.reason == "idempotent_existing_reservation"
    assert d2.reservation_id == d1.reservation_id


def test_cas_lease_acquisition():
    gov = PublishingGovernor()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    t1 = datetime(2026, 10, 13, 9, 15, tzinfo=tz)

    d1 = gov.evaluate_and_reserve(
        platform="youtube",
        account="primary",
        local_date="2026-10-13",
        slot_time="09:15",
        rendition_id="rend_cas",
        worker_id="w1",
        scheduled_for=t1,
    )
    assert d1.allowed is True

    lease_res = gov.acquire_lease(d1.reservation_id, "w1", d1.version)
    assert lease_res.allowed is True
    assert lease_res.reason == "lease_acquired"

    # Stale version CAS conflict
    conflict_res = gov.acquire_lease(d1.reservation_id, "w2", d1.version)
    assert conflict_res.allowed is False
    assert conflict_res.reason == "cas_version_conflict"
