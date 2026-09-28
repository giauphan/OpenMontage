"""Tests for news research bridge enum normalization and publish store force clear uniqueness."""

import json
from unittest.mock import MagicMock

import pytest

from lib.news_research_bridge import NewsResearchBridge
from tools.publish_store import PublishStore


def test_news_research_bridge_angle_type_normalization():
    bridge = NewsResearchBridge()
    candidate = {
        "candidate_id": "cand_test123",
        "title": "Test AI News Topic Title",
        "content_hash": "abc123hash",
        "raw_provenance": {"source_feed": "newsnow"},
    }
    agent_draft = {
        "research_draft": {
            "landscape": {
                "existing_content": [],
                "saturated_angles": ["Angle 1"],
                "underserved_gaps": ["Gap 1"],
            },
            "data_points": [
                {
                    "claim": "Test claim for news article",
                    "source_url": "https://example.com/source1",
                    "credibility": "primary_source",
                    "source_name": "Test Source",
                }
            ],
            "audience_insights": {
                "common_questions": ["Question 1?"],
                "misconceptions": [{"myth": "Myth 1", "reality": "Reality 1"}],
                "knowledge_level": "intermediate",
            },
            "angles_discovered": [
                {
                    "name": "Technical Angle",
                    "hook": "Super cool technical hook for test",
                    "type": "technical",
                    "why_now": "Recently updated technical spec",
                },
                {
                    "name": "Standard Angle",
                    "hook": "Standard hook for test",
                    "type": "trending",
                    "why_now": "Trending topic today",
                },
            ],
            "sources": [
                {
                    "url": "https://example.com/source1",
                    "title": "Test Source",
                    "used_for": "Testing",
                    "reliability": "primary",
                }
            ],
        }
    }
    brief = bridge.build_brief(candidate, agent_draft)
    angles = brief["angles_discovered"]
    assert len(angles) >= 2
    assert angles[0]["type"] == "data_driven"
    assert angles[1]["type"] == "trending"


def test_clear_uniqueness_for_topic():
    from scripts.publish_manual_video import _clear_uniqueness_for_topic

    store = MagicMock(spec=PublishStore)
    store.base_url = "https://firestore.googleapis.com/v1/projects/test/databases/(default)/documents/records"
    store.documents_url = store.base_url
    store.session = MagicMock()

    mock_docs = {
        "documents": [
            {
                "name": "projects/test/databases/(default)/documents/records/doc1",
                "fields": {
                    "record_type": {"stringValue": "uniqueness"},
                    "publish_key": {"stringValue": "2026-09-05_youtube_topic123_short"},
                },
            },
            {
                "name": "projects/test/databases/(default)/documents/records/doc2",
                "fields": {
                    "record_type": {"stringValue": "main"},
                    "publish_key": {"stringValue": "2026-09-05_youtube_topic123_short"},
                },
            },
        ]
    }

    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    mock_get_res.json.return_value = mock_docs

    mock_del_res = MagicMock()
    mock_del_res.status_code = 200

    store.session.get.return_value = mock_get_res
    store.session.delete.return_value = mock_del_res

    deleted = _clear_uniqueness_for_topic(store, "topic123")
    assert deleted == 1
    store.session.delete.assert_called_once()
