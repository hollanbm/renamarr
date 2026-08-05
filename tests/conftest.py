from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from loguru import logger
from pycliarr.api import RadarrCli, RadarrMovieItem, SonarrCli, SonarrSerieItem

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pycliarr.api.base_api import json_data
    from pytest_mock import MockerFixture


@pytest.fixture
def get_serie(mocker: MockerFixture) -> None:
    series: list[SonarrSerieItem] = [
        SonarrSerieItem(id=1, title="test title", status="continuing")
    ]
    mocker.patch.object(SonarrCli, "get_serie").return_value = series


@pytest.fixture
def get_serie_empty(mocker: MockerFixture) -> None:
    mocker.patch.object(SonarrCli, "get_serie").return_value = []


@pytest.fixture
def get_movie(mocker: MockerFixture) -> None:
    movies: list[RadarrMovieItem] = [RadarrMovieItem(id=1, title="test title")]
    mocker.patch.object(RadarrCli, "get_movie").return_value = movies


@pytest.fixture
def get_movie_empty(mocker: MockerFixture) -> None:
    mocker.patch.object(RadarrCli, "get_movie").return_value = []


@pytest.fixture
def mock_loguru_error(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "error")


@pytest.fixture
def mock_loguru_info(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "info")


@pytest.fixture
def mock_loguru_debug(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "debug")


@pytest.fixture
def mock_loguru_warning(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "warning")


def episode_data(
    episode_id: int,
    title: str,
    airDateDelta: timedelta,
    seasonNumber: str = 1,
    episodeNumber: int = 1,
    hasFile: bool = True,
    episodeFileId: int = 1,
) -> json_data:
    return {
        "id": episode_id,
        "title": title,
        "airDateUtc": (datetime.now(UTC) + airDateDelta).isoformat(),
        "seasonNumber": seasonNumber,
        "episodeNumber": episodeNumber,
        "hasFile": hasFile,
        "episodeFileId": episodeFileId,
    }
