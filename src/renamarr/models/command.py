from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandPollingSettings:
    """Settings for polling asynchronous Arr commands for completion."""

    timeout_seconds: int = 120
    check_interval_seconds: int = 3

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        if (
            type(self.check_interval_seconds) is not int
            or self.check_interval_seconds <= 0
        ):
            raise ValueError("check_interval_seconds must be a positive integer")
        if self.check_interval_seconds > self.timeout_seconds:
            raise ValueError("check_interval_seconds must not exceed timeout_seconds")


@dataclass(frozen=True, slots=True)
class CommandStatus:
    """The normalized state of an Arr command."""

    completed: bool
    successful: bool
