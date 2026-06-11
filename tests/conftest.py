from collections.abc import Generator
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from loguru import logger
from renamarr.observability import DisabledObservability
import renamarr.observability as observability_module
from pycliarr.api import RadarrCli, RadarrMovieItem, SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data


@pytest.fixture(autouse=True)
def reset_observability() -> Generator[None]:
    observability_module._observability = DisabledObservability()
    yield
    observability_module._observability = DisabledObservability()


@pytest.fixture
def get_serie(mocker) -> None:
    series: List[SonarrSerieItem] = [
        SonarrSerieItem(id=1, title="test title", status="continuing")
    ]
    mocker.patch.object(SonarrCli, "get_serie").return_value = series


@pytest.fixture
def get_serie_empty(mocker) -> None:
    mocker.patch.object(SonarrCli, "get_serie").return_value = []


@pytest.fixture
def get_movie(mocker) -> None:
    movies: List[RadarrMovieItem] = [RadarrMovieItem(id=1, title="test title")]
    mocker.patch.object(RadarrCli, "get_movie").return_value = movies


@pytest.fixture
def get_movie_empty(mocker) -> None:
    mocker.patch.object(RadarrCli, "get_movie").return_value = []


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
def mock_loguru_warning(mocker) -> None:
    return mocker.patch.object(logger, "warning")


@pytest.fixture
def fake_observability(mocker):
    observability = mocker.Mock()
    observability.start_span.side_effect = lambda *args, **kwargs: nullcontext()
    return observability


def episode_data(
    id: int,
    title: str,
    airDateDelta: timedelta,
    seasonNumber: str = 1,
    episodeNumber: int = 1,
    hasFile: bool = True,
    episodeFileId: int = 1,
) -> json_data:
    return dict(
        id=id,
        title=title,
        airDateUtc=(datetime.now(timezone.utc) + airDateDelta).isoformat(),
        seasonNumber=seasonNumber,
        episodeNumber=episodeNumber,
        hasFile=hasFile,
        episodeFileId=episodeFileId,
    )
