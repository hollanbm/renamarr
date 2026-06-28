from enum import StrEnum


class OperationResult(StrEnum):
    """Telemetry operation result labels."""

    ACCEPTED = "accepted"
    FAILED = "failed"
    NOOP = "noop"
