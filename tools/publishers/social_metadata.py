"""Platform-specific social publishing metadata helpers."""


def meta_caption(title: str, description: str) -> str:
    """Prefix a Meta caption with its title without duplicating it."""
    if description.strip().startswith(title.strip()):
        return description[:2000]
    return f"{title.strip()}\n\n{description.strip()}"[:2000]
