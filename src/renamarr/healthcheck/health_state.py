from enum import StrEnum


class HealthState(StrEnum):
    """Application lifecycle states exposed to the container health check."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    RUNNING = "running"
