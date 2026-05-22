import logging
from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data
from renamarr.sonarr.services.series_scanner import SonarrSeriesScanner

from tests.conftest import episode_data

FIXED_NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def tba_episode_at(air_date_utc: datetime) -> json_data:
    return dict(
        id=1,
        title="TBA",
        airDateUtc=air_date_utc.isoformat(),
        seasonNumber=1,
        episodeNumber=1,
        hasFile=True,
        episodeFileId=1,
    )


class TestSeriesScanner:
    @pytest.fixture(autouse=True)
    def mediamanagement_always(self, mocker) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = dict(
            episodeTitleRequired=True
        )

    @pytest.fixture
    def fixed_now(self, mocker) -> datetime:
        datetime_mock = mocker.patch("renamarr.sonarr.services.series_scanner.datetime")
        datetime_mock.now.return_value = FIXED_NOW
        return FIXED_NOW

    def test_when_episode_title_required_false(self, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = dict(
            episodeTitleRequired=False
        )

        with caplog.at_level(logging.ERROR):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        assert "Episode Title Required is not set to always" in caplog.text
        assert "Exiting Series Scan" in caplog.text

    def test_no_series_returned(self, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "get_serie").return_value = []
        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()
        assert "Sonarr returned empty series list" in caplog.text
        assert "Finished Series Scan" in caplog.text

    def test_when_series_returned_no_episodes(self, get_serie, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "get_episode").return_value = []
        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()
        assert "Retrieved series list" in caplog.text
        assert "Error fetching episode list" in caplog.text

    def test_when_show_status_not_continuuing(self, caplog, mocker) -> None:
        series: List[SonarrSerieItem] = [
            SonarrSerieItem(id=1, title="test title", status="ended")
        ]
        mocker.patch.object(SonarrCli, "get_serie").return_value = series
        get_episode = mocker.patch.object(SonarrCli, "get_episode")
        get_episode.return_value = []

        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()
        # assert "Error fetching episode list" in caplog.text

        assert not get_episode.called

    def test_when_multiple_shows_continuing_and_ended(self, caplog, mocker) -> None:
        series: List[SonarrSerieItem] = [
            SonarrSerieItem(id=1, title="title 1", status="continuing"),
            SonarrSerieItem(id=2, title="title 2", status="ended"),
        ]
        mocker.patch.object(SonarrCli, "get_serie").return_value = series

        get_episode = mocker.patch.object(SonarrCli, "get_episode")
        get_episode.return_value = []

        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        get_episode.assert_called_once_with(1)

    def test_when_episodes_filtered_out(self, get_serie, caplog, mocker) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="TBA",
                airDateDelta=timedelta(hours=8),
            ),
            episode_data(
                id=2,
                title="title",
                airDateDelta=timedelta(hours=-2),
            ),
            episode_data(
                id=3,
                title="TBA",
                airDateDelta=timedelta(hours=2),
                seasonNumber=0,
            ),
            dict(
                id=4,
                title="TBA",
                airDateUtc=None,
                seasonNumber=1,
            ),
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes

        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        assert "Retrieved episode list" in caplog.text
        assert not refresh_serie.called

    def test_when_tba_episode_is_airing_soon(self, get_serie, caplog, mocker) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="TBA",
                airDateDelta=timedelta(hours=2),
                seasonNumber=1,
            )
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes

        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        refresh_serie.assert_called_once_with(1)
        assert "Found TBA episode, airing within the next 4 hours" in caplog.text
        assert "Series rescan triggered" in caplog.text

    def test_when_tba_episode_has_already_aired(
        self, get_serie, caplog, mocker
    ) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="TBA",
                airDateDelta=timedelta(days=-1),
                seasonNumber=1,
            )
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes

        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        with caplog.at_level(logging.DEBUG):
            SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        refresh_serie.assert_called_once_with(1)
        assert "Found previously aired episode with TBA title" in caplog.text
        assert "Series rescan triggered" in caplog.text

    def test_when_hours_before_air_above_max_is_capped(
        self, get_serie, fixed_now, mocker
    ) -> None:
        mocker.patch.object(
            SonarrCli,
            "get_episode",
            return_value=[tba_episode_at(fixed_now + timedelta(hours=13))],
        )
        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        SonarrSeriesScanner("test", "test.tld", "test-api-key", 99).scan()

        refresh_serie.assert_not_called()

    def test_when_tba_episode_is_exactly_at_future_limit_refreshes(
        self, get_serie, fixed_now, mocker
    ) -> None:
        mocker.patch.object(
            SonarrCli,
            "get_episode",
            return_value=[tba_episode_at(fixed_now + timedelta(hours=4))],
        )
        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        refresh_serie.assert_called_once_with(1)

    def test_when_tba_episode_is_just_beyond_future_limit_does_not_refresh(
        self, get_serie, fixed_now, mocker
    ) -> None:
        mocker.patch.object(
            SonarrCli,
            "get_episode",
            return_value=[tba_episode_at(fixed_now + timedelta(hours=4, seconds=1))],
        )
        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        refresh_serie.assert_not_called()

    def test_when_tba_episode_is_exactly_now_does_not_refresh(
        self, get_serie, fixed_now, mocker
    ) -> None:
        mocker.patch.object(
            SonarrCli,
            "get_episode",
            return_value=[tba_episode_at(fixed_now)],
        )
        refresh_serie = mocker.patch.object(SonarrCli, "refresh_serie")

        SonarrSeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        refresh_serie.assert_not_called()
