import pytest
from pytest_mock import MockerFixture

from renamarr.adapter_factory import ArrService, create_arr_adapter


def test_selects_radarr_adapter(mocker: MockerFixture) -> None:
    radarr_adapter = mocker.patch(
        "renamarr.adapter_factory.RadarrAdapter", autospec=True
    )
    sonarr_adapter = mocker.patch(
        "renamarr.adapter_factory.SonarrAdapter", autospec=True
    )

    assert (
        create_arr_adapter(ArrService.RADARR, "https://radarr.test", "radarr-key")
        is radarr_adapter.return_value
    )
    radarr_adapter.assert_called_once_with("https://radarr.test", "radarr-key")
    sonarr_adapter.assert_not_called()


def test_selects_sonarr_adapter(mocker: MockerFixture) -> None:
    radarr_adapter = mocker.patch(
        "renamarr.adapter_factory.RadarrAdapter", autospec=True
    )
    sonarr_adapter = mocker.patch(
        "renamarr.adapter_factory.SonarrAdapter", autospec=True
    )

    assert (
        create_arr_adapter(ArrService.SONARR, "https://sonarr.test", "sonarr-key")
        is sonarr_adapter.return_value
    )
    sonarr_adapter.assert_called_once_with("https://sonarr.test", "sonarr-key")
    radarr_adapter.assert_not_called()


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
