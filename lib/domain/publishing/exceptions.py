"""Domain exceptions for video publishing and scheduling."""


class PublishDomainError(Exception):
    """Base domain exception for publishing lifecycle errors."""


class InvalidPublishSlotError(PublishDomainError):
    """Raised when a publish slot format, time, or date is invalid."""


class VideoFileMissingError(PublishDomainError):
    """Raised when a referenced video file does not exist or is unreadable."""


class PlatformQuotaExceededError(PublishDomainError):
    """Raised when a publishing platform's rate/quota limit has been exceeded."""


class PublishConcurrencyConflictError(PublishDomainError):
    """Raised when another worker or process has already claimed or locked the publish job."""
