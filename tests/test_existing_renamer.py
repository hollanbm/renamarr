import logging

from existing_renamer import ExistingRenamer
from pycliarr.api import SonarrCli


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
        mocker.patch.object(SonarrCli, "request_get").return_value = []
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "Retrieved series list" in caplog.text
        assert "No episodes to rename" in caplog.text
        assert not rename_files.called

    def test_when_episode_need_renamed(self, get_serie, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = [
            dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=1)
        ]
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "Found episodes to be renamed" in caplog.text
        assert "Renaming S01E01" in caplog.text
        rename_files.assert_called_once_with([1], 1)

    def test_when_multiple_episodes_need_renamed(
        self, get_serie, caplog, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = [
            dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=1),
            dict(seasonNumber=1, episodeNumbers=[2], episodeFileId=2),
        ]
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            ExistingRenamer("test", "test.tld", "test-api-key").scan()

        assert "Found episodes to be renamed" in caplog.text
        assert "Renaming S01E01, S01E02" in caplog.text
        rename_files.assert_called_once_with([1, 2], 1)
