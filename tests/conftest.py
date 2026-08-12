from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from loguru import logger
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data
from pytest_mock import MockerFixture


@pytest.fixture
def get_serie(mocker) -> None:
    series: list[SonarrSerieItem] = [
        SonarrSerieItem(id=1, title="test title", status="continuing")
    ]
    mocker.patch.object(SonarrCli, "get_serie").return_value = series


@pytest.fixture
def mock_loguru_error(mocker) -> None:
    return mocker.patch.object(logger, "error")


@pytest.fixture
def mock_loguru_info(mocker) -> None:
    return mocker.patch.object(logger, "info")


@pytest.fixture
def mock_loguru_debug(mocker) -> None:
    return mocker.patch.object(logger, "debug")


@pytest.fixture
def mock_loguru_warning(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "warning")


def episode_data(
    id: int,
    title: str,
    airDateDelta: timedelta,
    seasonNumber: str = 1,
    episodeNumber: int = 1,
    hasFile: bool = True,
    episodeFileId: int = 1,
) -> json_data:
    return {
        "id": id,
        "title": title,
        "airDateUtc": (datetime.now(UTC) + airDateDelta).isoformat(),
        "seasonNumber": seasonNumber,
        "episodeNumber": episodeNumber,
        "hasFile": hasFile,
        "episodeFileId": episodeFileId,
    }
