"""Platform-specific social publishing metadata helpers."""


def youtube_short_title(title: str) -> str:
    """Fit a YouTube title within 100 characters while retaining #Shorts."""
    suffix = " #Shorts"
    if "#shorts" in title.lower():
        return title[:100]
    return f"{title[:100 - len(suffix)].rstrip()}{suffix}"


def meta_caption(title: str, description: str) -> str:
    """Prefix a Meta caption with its title without duplicating it."""
    if description.strip().startswith(title.strip()):
        return description[:2000]
    return f"{title.strip()}\n\n{description.strip()}"[:2000]
