import pytest
from pathlib import Path
from lib.audience_profile import (
    load_audience_profile,
    AudienceProfile,
    AudienceProfileValidationError,
    validate_profile_dict,
)

def test_load_en_us_profile():
    profile = load_audience_profile("en-US")
    assert isinstance(profile, AudienceProfile)
    assert profile.profile_id == "en-us-practical-ai-v1"
    assert profile.primary_market == "US"
    assert profile.secondary_markets == ("CA",)
    assert profile.spoken_language == "en-US"
    assert profile.metadata_language == "en-US"
    assert profile.is_english is True
    assert profile.is_vietnamese is False

    # Check format definitions
    assert "short" in profile.formats
    assert profile.formats["short"].output == "renders/final_short_en_US_9x16.mp4"
    assert profile.formats["short"].aspect == "9:16"
    assert profile.formats["short"].internal_pilot_max_seconds == 60

    assert "longform" in profile.formats
    assert profile.formats["longform"].output == "renders/final_long_en_US_16x9.mp4"
    assert profile.formats["longform"].aspect == "16:9"

    # Check publishing settings
    assert profile.publishing.application_timezone == "America/New_York"
    assert profile.publishing.default_canary_visibility == "private"
    assert profile.publishing.enabled is False
    assert profile.safety.fail_closed is True

def test_load_vi_vn_legacy_profile():
    profile = load_audience_profile("vi-VN")
    assert isinstance(profile, AudienceProfile)
    assert profile.profile_id == "vi-vn-daily-news-v1"
    assert profile.primary_market == "VN"
    assert profile.spoken_language == "vi-VN"
    assert profile.is_vietnamese is True
    assert profile.formats["short"].output == "renders/final_reels_vi_9x16.mp4"

def test_invalid_profile_schema_fails_closed():
    invalid_data = {
        "profile_id": "bad-profile",
        "primary_market": "INVALID_MARKET",
    }
    with pytest.raises(AudienceProfileValidationError):
        validate_profile_dict(invalid_data)
