import logging
from typing import List

import pytest
from pycliarr.api import SonarrCli, SonarrSerieItem
from series_scanner import SeriesScanner


class TestSeriesScanner:
    @pytest.fixture
    def get_serie(self, mocker) -> None:
        series: List[SonarrSerieItem] = [
            SonarrSerieItem(id=1, title="test title", status="continuing")
        ]
        mocker.patch.object(SonarrCli, "get_serie").return_value = series

    @pytest.fixture
    def get_ended_serie(self, mocker) -> None:
        series: List[SonarrSerieItem] = [
            SonarrSerieItem(id=1, title="test title", status="ended")
        ]
        mocker.patch.object(SonarrCli, "get_serie").return_value = series

    @pytest.fixture
    def get_episode(self, mocker) -> None:
        series: List[SonarrSerieItem] = [
            SonarrSerieItem(id=1, title="test title", status="continuing")
        ]
        mocker.patch.object(SonarrCli, "get_serie").return_value = series

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

    def test_when_show_status_not_continuuing(
        self, get_ended_serie, caplog, mocker
    ) -> None:
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
        # assert "Error fetching episode list" in caplog.text

        get_episode.assert_called_once_with(1)
