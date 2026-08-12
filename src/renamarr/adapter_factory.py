from enum import StrEnum

from renamarr.protocols import ArrAdapter
from renamarr.radarr.adapter import RadarrAdapter
from renamarr.sonarr.adapter import SonarrAdapter


class ArrService(StrEnum):
    """Arr services supported by Renamarr."""

    RADARR = "radarr"
    SONARR = "sonarr"


def create_arr_adapter(service: ArrService, url: str, api_key: str) -> ArrAdapter:
    """Create the adapter for a supported Arr service."""
    if service is ArrService.RADARR:
        return RadarrAdapter(url, api_key)
    return SonarrAdapter(url, api_key)
