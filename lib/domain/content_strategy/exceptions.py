from __future__ import annotations


class ContentStrategyDomainError(Exception):
    """Base domain exception for content strategy and hook evaluation."""
    pass


class InvalidHookError(ContentStrategyDomainError):
    """Raised when hook input text is empty, malformed, or exceeds valid length."""
    pass


class PlatformMismatchError(ContentStrategyDomainError):
    """Raised when a hook style contradicts platform-specific audience policy."""
    pass


class LowQualityWeakHookError(ContentStrategyDomainError):
    """Raised when a weak hook lacks audience filtering, trust signals, or content alignment."""
    pass
