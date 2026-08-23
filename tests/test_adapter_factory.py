import pytest
from pytest_mock import MockerFixture

from renamarr.adapter_factory import ArrService, create_arr_adapter
from renamarr.radarr.radarr_adapter import RadarrAdapter
from renamarr.sonarr_py.sonarr_py_adapter import SonarrPyAdapter


def test_creates_radarr_adapter() -> None:
    adapter = create_arr_adapter(ArrService.RADARR, "https://radarr.test", "radarr-key")

    assert isinstance(adapter, RadarrAdapter)
    assert adapter._client.host_url == "https://radarr.test"
    assert adapter._client.api_key == "radarr-key"


def test_creates_sonarr_adapter() -> None:
    adapter = create_arr_adapter(ArrService.SONARR, "https://sonarr.test", "sonarr-key")

    assert isinstance(adapter, SonarrPyAdapter)
    assert adapter._client.configuration.host == "https://sonarr.test"
    assert adapter._client.configuration.api_key["X-Api-Key"] == "sonarr-key"


def test_rejects_unsupported_service_value() -> None:
    with pytest.raises(ValueError, match="'lidarr' is not a valid ArrService"):
        ArrService("lidarr")


def test_factory_rejects_unsupported_future_service_member(
    mocker: MockerFixture,
) -> None:
    with pytest.raises(ValueError, match="Unsupported Arr service"):
        create_arr_adapter(
            mocker.sentinel.unsupported_service,
            "https://lidarr.test",
            "lidarr-key",
        )
