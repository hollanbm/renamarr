from enum import StrEnum

from renamarr.protocols import ArrAdapter
from renamarr.radarr.radarr_adapter import RadarrAdapter
from renamarr.sonarr_py.sonarr_py_adapter import SonarrPyAdapter


class ArrService(StrEnum):
    """Arr services supported by Renamarr."""

    RADARR = "radarr"
    SONARR = "sonarr"


def create_arr_adapter(service: ArrService, url: str, api_key: str) -> ArrAdapter:
    """Create the adapter for a supported Arr service."""
    match service:
        case ArrService.RADARR:
            return RadarrAdapter(url, api_key)
        case ArrService.SONARR:
            return SonarrPyAdapter(url, api_key)
        case _:
            raise ValueError(f"Unsupported Arr service: {service!r}")
