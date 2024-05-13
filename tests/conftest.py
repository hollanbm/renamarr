from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data


@pytest.fixture
def get_serie(mocker) -> None:
    series: List[SonarrSerieItem] = [
        SonarrSerieItem(id=1, title="test title", status="continuing")
    ]
    mocker.patch.object(SonarrCli, "get_serie").return_value = series


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


def file_info(id: int, file_name: str) -> json_data:
    return dict(
        id=id,
        path=f"/path/to/{file_name}",
    )
