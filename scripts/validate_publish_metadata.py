#!/usr/bin/env python3
"""Validate publish_metadata.json text fields before Firebase claim.

The strict quality gate validates video/audio content (dimensions, codecs,
black frames, silent audio). This validator complements it by checking text
metadata that platforms will display or require:
  * required hashtags present in title/description
  * no shell command syntax (unclosed quotes/backticks/expansions)
  * no unexpanded placeholders
"""

import argparse
import json
import re
import sys
from pathlib import Path

from tools.publishers.platform_routes import youtube_shorts_title


REQUIRED_HASHTAGS = {"#tintuc", "#congnghe", "#ai"}
SHELL_PATTERNS = [
    r"\$\(",  # command substitution
    r"\$\{",  # variable expansion
    r"`",     # backtick command substitution
]


def validate_text_field(field_name: str, value: str) -> list[str]:
    """Return list of validation errors for a text field."""
    errors = []

    # Check for shell command syntax
    for pattern in SHELL_PATTERNS:
        if re.search(pattern, value):
            errors.append(f"{field_name} contains shell command syntax: {pattern}")

    # Check for unexpanded placeholders
    if re.search(r"\{\{.*?\}\}|\$\w+", value):
        errors.append(f"{field_name} contains unexpanded placeholder")

    return errors


def validate_hashtags(field_name: str, value: str, required: set[str]) -> list[str]:
    """Return list of hashtag validation errors."""
    errors = []
    normalized = value.lower()
    missing = [tag for tag in required if tag not in normalized]

    if missing:
        errors.append(
            f"{field_name} missing required hashtags: {', '.join(missing)}"
        )

    return errors



def validate_metadata(metadata_path: Path) -> tuple[bool, list[str]]:
    """Validate publish_metadata.json. Returns (success, errors)."""
    if not metadata_path.is_file():
        return False, [f"publish_metadata.json not found: {metadata_path}"]

    try:
        with metadata_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON in {metadata_path}: {e}"]

    errors = []

    # Validate title
    title = metadata.get("title", "")
    if not title:
        errors.append("title field is missing or empty")
    else:
        errors.extend(validate_text_field("title", title))
        errors.extend(validate_hashtags("title", title, REQUIRED_HASHTAGS))
        try:
            youtube_shorts_title(title)
        except ValueError as exc:
            errors.append(f"YouTube Shorts title invalid: {exc}")

    # Validate description
    description = metadata.get("description", "")
    if description:
        errors.extend(validate_text_field("description", description))
        errors.extend(validate_hashtags("description", description, REQUIRED_HASHTAGS))

    return len(errors) == 0, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate publish_metadata.json text fields"
    )
    parser.add_argument("project_path", type=Path, help="Project directory path")
    args = parser.parse_args()

    metadata_path = args.project_path / "publish_metadata.json"
    success, errors = validate_metadata(metadata_path)

    if not success:
        print(f"METADATA VALIDATION FAILED for {args.project_path}:", file=sys.stderr)
        for error in errors:
            print(f"  • {error}", file=sys.stderr)
        return 1

    print(f"✓ Metadata validation passed for {args.project_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
