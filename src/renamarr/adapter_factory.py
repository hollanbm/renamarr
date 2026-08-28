from enum import StrEnum

from renamarr.lidarr.lidarr_adapter import LidarrAdapter
from renamarr.protocols import ArrAdapter
from renamarr.radarr.radarr_adapter import RadarrAdapter
from renamarr.sonarr.sonarr_adapter import SonarrAdapter


class ArrService(StrEnum):
    """Arr services supported by Renamarr."""

    LIDARR = "lidarr"
    RADARR = "radarr"
    SONARR = "sonarr"


def create_arr_adapter(service: ArrService, url: str, api_key: str) -> ArrAdapter:
    """Create the adapter for a supported Arr service."""
    match service:
        case ArrService.LIDARR:
            return LidarrAdapter(url, api_key)
        case ArrService.RADARR:
            return RadarrAdapter(url, api_key)
        case ArrService.SONARR:
            return SonarrAdapter(url, api_key)
        case _:
            raise ValueError(f"Unsupported Arr service: {service!r}")
