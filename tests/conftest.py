from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from pycliarr.api import SonarrCli, SonarrSerieItem


@pytest.fixture
def get_serie(mocker) -> None:
    series: List[SonarrSerieItem] = [
        SonarrSerieItem(id=1, title="test title", status="continuing")
    ]
    mocker.patch.object(SonarrCli, "get_serie").return_value = series


def episode_data(
    id: int, title: str, airDateDelta: timedelta, seasonNumber: str
) -> dict:
    return dict(
        id=id,
        title=title,
        airDateUtc=(datetime.now(timezone.utc) + airDateDelta).isoformat(),
        seasonNumber=seasonNumber,
    )
