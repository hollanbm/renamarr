import logging
from datetime import timedelta
from typing import List

from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data
from series_scanner import SeriesScanner

from tests.conftest import episode_data


class TestSeriesScanner:
    def test_no_series_returned(self, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "get_serie").return_value = []
        with caplog.at_level(logging.DEBUG):
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()
        assert "Sonarr returned empty series list" in caplog.text
        assert "Finished Series Scan" in caplog.text

    def test_when_series_returned_no_episodes(self, get_serie, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "get_episode").return_value = []
        with caplog.at_level(logging.DEBUG):
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()
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
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()
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
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()

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
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()

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
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        assert refresh_serie.called
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
            SeriesScanner("test", "test.tld", "test-api-key", 4).scan()

        assert refresh_serie.called
        assert "Found previously aired episode with TBA title" in caplog.text
        assert "Series rescan triggered" in caplog.text
