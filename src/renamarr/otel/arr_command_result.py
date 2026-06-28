from enum import StrEnum


class ArrCommandResult(StrEnum):
    """Telemetry Arr command result labels."""

    SUCCESSFUL = "successful"
    FAILED = "failed"
    TIMEOUT = "timeout"
