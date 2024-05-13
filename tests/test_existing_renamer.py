import logging
from datetime import timedelta
from typing import List

from existing_renamer import ExistingRenamer
from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data

from tests.conftest import episode_data, file_info


class TestExistingRenamer:
    def test_no_series_returned(self, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "get_serie").return_value = []
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "Starting Existing Renamer" in caplog.text
        assert "Sonarr returned empty series list" in caplog.text
        assert "Finished Existing Renamer" in caplog.text
        assert not rename_files.called

    def test_when_series_returned_no_episodes(self, get_serie, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "get_episode").return_value = []
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "Starting Existing Renamer" in caplog.text
        assert "Retrieved series list" in caplog.text
        assert "Error fetching episode list" in caplog.text
        assert not rename_files.called

    def test_when_episodes_filtered_out(self, get_serie, caplog, mocker) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="TBA",
                airDateDelta=timedelta(hours=2),
                seasonNumber=0,
            ),
            episode_data(
                id=2,
                title="TBA",
                airDateDelta=timedelta(hours=8),
            ),
            dict(id=3, title="NOT TBA", airDateUtc=None, seasonNumber=1, hasFile=False),
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "Starting Existing Renamer" in caplog.text
        assert "Retrieved series list" in caplog.text
        assert "No rename needed" in caplog.text
        assert not rename_files.called

    def test_when_episode_file_name_contains_TBA(
        self, get_serie, caplog, mocker
    ) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="NOT TBA",
                airDateDelta=timedelta(days=-1),
                seasonNumber=1,
            ),
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        file: json_data = file_info(
            id=1,
            file_name="The Series Titles (2010) - S01E01 - TBA.mkv",
        )

        mocker.patch.object(SonarrCli, "get_episode_file").return_value = file

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "S01E01 Queuing for rename" in caplog.text
        assert "Renaming S01E01" in caplog.text
        rename_files.assert_called_once_with([1], 1)

    def test_when_renaming_multiple_files(self, get_serie, caplog, mocker) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="NOT TBA",
                airDateDelta=timedelta(days=-1),
                seasonNumber=1,
                episodeNumber=1,
            ),
            episode_data(
                id=2,
                title="NOT TBA",
                airDateDelta=timedelta(days=-1),
                seasonNumber=1,
                episodeNumber=2,
            ),
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        file1: json_data = file_info(
            id=1,
            file_name="The Series Titles (2010) - S01E01 - TBA.mkv",
        )

        file2: json_data = file_info(
            id=2,
            file_name="The Series Titles (2010) - S01E02 - TBA.mkv",
        )

        get_episode_file = mocker.patch.object(SonarrCli, "get_episode_file")
        get_episode_file.return_value = file1
        get_episode_file.side_effect = [file1, file2]

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "S01E01 Queuing for rename" in caplog.text
        assert "S01E02 Queuing for rename" in caplog.text
        assert "Renaming S01E01, S01E02" in caplog.text
        rename_files.assert_called_once_with([1, 2], 1)

    def test_when_episode_file_name_does_not_contain_TBA(
        self, get_serie, caplog, mocker
    ) -> None:
        episodes: List[json_data] = [
            episode_data(
                id=1,
                title="NOT TBA",
                airDateDelta=timedelta(days=-1),
                seasonNumber=1,
            ),
        ]
        mocker.patch.object(SonarrCli, "get_episode").return_value = episodes
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        file: json_data = file_info(
            id=1,
            file_name="The Series Titles (2010) - S01E01 - Episode1.mkv",
        )

        mocker.patch.object(SonarrCli, "get_episode_file").return_value = file

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "No rename needed" in caplog.text
        assert not rename_files.called
