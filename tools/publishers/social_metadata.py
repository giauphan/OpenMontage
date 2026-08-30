"""Platform-specific social publishing metadata helpers."""


def meta_caption(title: str, description: str) -> str:
    """Prefix a Meta caption with its title without duplicating it."""
    clean_title = title.strip()
    clean_description = description.strip()
    if clean_description.startswith(clean_title):
        return clean_description[:2000]
    return f"{clean_title}\n\n{clean_description}"[:2000]
