"""Regression tests for strict post-publish completion checks."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_manual_video import canonical_platform_records_published
from tools.publish_store import publish_key


class FakeStore:
    def __init__(self, records):
        self.records = records

    def get(self, key):
        return self.records.get(key)


def records_with_facebook_status(status):
    date = "2026-09-05"
    topic = "topic"
    records = {
        publish_key(date, topic, "youtube", "short"): {"status": "published"},
        publish_key(date, topic, "instagram", "reels"): {"status": "published"},
        publish_key(date, topic, "facebook", "reels"): {"status": status},
    }
    return date, topic, records


def test_canonical_platform_records_published_requires_three_published_records():
    date, topic, records = records_with_facebook_status("published")

    assert canonical_platform_records_published(FakeStore(records), date=date, topic=topic) is True


@pytest.mark.parametrize("status", [None, "scheduling", "failed"])
def test_canonical_platform_records_published_rejects_nonpublished_state(status):
    date, topic, records = records_with_facebook_status("published")
    facebook_key = publish_key(date, topic, "facebook", "reels")
    records[facebook_key] = None if status is None else {"status": status}

    assert canonical_platform_records_published(FakeStore(records), date=date, topic=topic) is False


def test_canonical_platform_records_published_rejects_firestore_error():
    class ErrorStore:
        def get(self, _key):
            raise RuntimeError("Firestore unavailable")

    assert canonical_platform_records_published(ErrorStore(), date="2026-09-05", topic="topic") is False
