"""Platform-specific social publishing metadata helpers."""

import re


def meta_caption(title: str, description: str) -> str:
    """Prefix a Meta caption with its title without duplicating it."""
    clean_title = title.strip()
    clean_description = description.strip()
    title_prefix = re.escape(clean_title)
    if re.match(rf"^{title_prefix}(?:$|[\s:|.!?,;()-])", clean_description):
        return clean_description
    return f"{clean_title}\n\n{clean_description}"
