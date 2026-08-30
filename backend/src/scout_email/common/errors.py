class ScoutEmailError(Exception):
    """Base class for expected domain errors."""


class NotFoundError(ScoutEmailError):
    """Raised when a requested persistent entity does not exist."""


class InvalidStateTransitionError(ScoutEmailError):
    """Raised when a workflow state transition is not allowed."""


class DuplicateOperationError(ScoutEmailError):
    """Raised when a stale/idempotent operation loses a compare-and-set race."""
