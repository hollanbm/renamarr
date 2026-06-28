from enum import StrEnum


class JobResult(StrEnum):
    """Telemetry job result labels."""

    SUCCESS = "success"
    FAILED = "failed"
