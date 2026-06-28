from enum import StrEnum


class ServiceName(StrEnum):
    """Supported Arr service names."""

    SONARR = "sonarr"
    RADARR = "radarr"
