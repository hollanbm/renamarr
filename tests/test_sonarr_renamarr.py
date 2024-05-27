import logging
from unittest.mock import call

from pycliarr.api import SonarrCli
from sonarr_renamarr import SonarrRenamarr


class TestSonarrRenamarr:
    def test_no_series_returned(self, get_serie_empty, caplog, mocker) -> None:
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            SonarrRenamarr("test", "test.tld", "test-api-key").scan()

        assert "Starting Renamarr" in caplog.text
        assert "Sonarr returned empty series list" in caplog.text
        assert "Finished Renamarr" in caplog.text
        assert not rename_files.called

    def test_when_series_returned_no_episodes(self, get_serie, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = []
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            SonarrRenamarr("test", "test.tld", "test-api-key").scan()

        assert "Retrieved series list" in caplog.text
        assert "No episodes to rename" in caplog.text
        assert not rename_files.called

    def test_when_episode_need_renamed(self, get_serie, caplog, mocker) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = [
            dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=1)
        ]
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        with caplog.at_level(logging.DEBUG):
            SonarrRenamarr("test", "test.tld", "test-api-key").scan()

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
            SonarrRenamarr("test", "test.tld", "test-api-key").scan()

        assert "Found episodes to be renamed" in caplog.text
        assert "Renaming S01E01, S01E02" in caplog.text
        rename_files.assert_called_once_with([1, 2], 1)

    def test_when_disk_scan_enabled_and_analyze_files_is_not(
        self, get_serie_empty, mock_loguru_warning, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = dict(
            enableMediaInfo=False
        )

        SonarrRenamarr("test", "test.tld", "test-api-key", True).scan()

        mock_loguru_warning.assert_called_once_with(
            "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
        )

    def test_when_disk_scan_enabled(
        self, get_serie_empty, mock_loguru_info, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = dict(
            enableMediaInfo=True
        )
        mocker.patch.object(SonarrCli, "_sendCommand").return_value = dict(id=1)
        mocker.patch.object(SonarrCli, "get_command").return_value = dict(
            status="completed", result="successful"
        )
        mocker.patch("sonarr_renamarr.sleep").return_value = None

        SonarrRenamarr("test", "test.tld", "test-api-key", True).scan()

        assert call("Initiated disk scan of library") in mock_loguru_info.call_args_list
        assert (
            call("disk scan finished successfully") in mock_loguru_info.call_args_list
        )

    def test_when_disk_scan_enabled_and_fails(
        self, get_serie_empty, mock_loguru_info, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = dict(
            enableMediaInfo=True
        )
        mocker.patch.object(SonarrCli, "_sendCommand").return_value = dict(id=1)
        mocker.patch.object(SonarrCli, "get_command").return_value = dict(
            status="completed", result="failed"
        )
        mocker.patch("sonarr_renamarr.sleep").return_value = None

        SonarrRenamarr("test", "test.tld", "test-api-key", True).scan()

        assert call("disk scan failed") in mock_loguru_info.call_args_list
