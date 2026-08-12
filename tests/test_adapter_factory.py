import pytest

from renamarr.adapter_factory import ArrService, create_arr_adapter
from renamarr.radarr.adapter import RadarrAdapter
from renamarr.sonarr.adapter import SonarrAdapter


def test_creates_radarr_adapter() -> None:
    adapter = create_arr_adapter(ArrService.RADARR, "https://radarr.test", "radarr-key")

    assert isinstance(adapter, RadarrAdapter)
    assert adapter._client.host_url == "https://radarr.test"
    assert adapter._client.api_key == "radarr-key"


def test_creates_sonarr_adapter() -> None:
    adapter = create_arr_adapter(ArrService.SONARR, "https://sonarr.test", "sonarr-key")

    assert isinstance(adapter, SonarrAdapter)
    assert adapter._client.host_url == "https://sonarr.test"
    assert adapter._client.api_key == "sonarr-key"


def test_rejects_unsupported_service_value() -> None:
    with pytest.raises(ValueError, match="'lidarr' is not a valid ArrService"):
        ArrService("lidarr")
