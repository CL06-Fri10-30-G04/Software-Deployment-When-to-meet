class RepositoryError(Exception):
    """Base exception for repository-boundary errors."""


class DuplicateEmailError(RepositoryError):
    """Raised when a user email address is already registered."""


class NotFound(RepositoryError):
    """Raised when a requested document or embedded item does not exist."""


class PermissionDenied(RepositoryError):
    """Raised when an actor cannot perform a repository operation."""


class ParticipantsUnavailable(RepositoryError):
    """Raised when finalizing a slot that excludes one or more participants."""


class ConcurrencyError(RepositoryError):
    """Raised after a document update repeatedly loses an ETag race."""


class ValidationError(RepositoryError):
    """Raised when repository input does not satisfy the data contract."""
