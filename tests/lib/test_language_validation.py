import pytest
from lib.language_validation import (
    get_language_validator,
    EnglishLanguageValidator,
    VietnameseLanguageValidator,
)

def test_valid_english_prose():
    validator = get_language_validator("en-US")
    assert isinstance(validator, EnglishLanguageValidator)
    
    text = "OpenAI released a new API update today with reduced latency for developers."
    errors = validator.validate_prose(text)
    assert not errors

def test_english_rejects_vietnamese_diacritics():
    validator = get_language_validator("en-US")
    # Text with Vietnamese diacritic
    text = "We tested the new công nghệ tool with our workflow."
    errors = validator.validate_prose(text)
    assert errors
    assert any("Vietnamese diacritics" in err or "Vietnamese words" in err for err in errors)

def test_english_rejects_vietnamese_leak_words():
    validator = get_language_validator("en-US")
    text = "Check out this AI tool today with tintuc and congnghe."
    errors = validator.validate_prose(text)
    assert errors
    assert any("Vietnamese words" in err for err in errors)

def test_english_metadata_validation():
    validator = get_language_validator("en-US")
    errors = validator.validate_metadata(
        title="AST Repo Map Context Compression: Fitting 100k Lines of Code into Agent Context Windows #AI #Tech",
        description="Hands-on walkthrough with 32k context and 128k tokens for developers.",
        tags=["ai", "coding", "devtools"]
    )
    assert not errors

    # With Vietnamese currency leak
    bad_currency_errors = validator.validate_metadata(
        title="AI Assistant subscription price is 100k vnd #AI",
        description="Cost is 50k đ per month.",
        tags=["ai", "coding"]
    )
    assert bad_currency_errors
    assert any("Vietnamese currency format" in err for err in bad_currency_errors)

    # With Vietnamese tag
    bad_errors = validator.validate_metadata(
        title="New AI Code Assistant Tested #AI",
        description="Hands-on walkthrough of the latest developer tool.",
        tags=["ai", "#tintuc"]
    )
    assert bad_errors
    assert any("Vietnamese tag" in err for err in bad_errors)

def test_vietnamese_validator_retained():
    validator = get_language_validator("vi-VN")
    assert isinstance(validator, VietnameseLanguageValidator)
    
    # Valid Vietnamese passes
    assert not validator.validate_prose("Công nghệ AI mới nhất năm 2026.")
    
    # English prose fails Vietnamese validator
    eng_errors = validator.validate_prose("This is English prose.")
    assert eng_errors
