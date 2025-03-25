from unittest.mock import call

from pycliarr.api import SonarrCli

from sonarr_renamarr import SonarrRenamarr


class TestSonarrRenamarr:
    def test_no_series_returned(
        self, get_serie_empty, mock_loguru_info, mock_loguru_error, mocker
    ) -> None:
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        mock_loguru_error.assert_any_call("Sonarr returned empty series list")

        mock_loguru_info.assert_has_calls(
            [
                call("Starting Renamarr"),
                call("Finished Renamarr"),
            ]
        )
        rename_files.assert_not_called()

    def test_when_series_returned_no_episodes(
        self, get_serie, mock_loguru_debug, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = []
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        mock_loguru_debug.assert_has_calls(
            [
                call("Retrieved series list"),
                call("No episodes to rename"),
            ]
        )

        rename_files.assert_not_called

    def test_when_episode_need_renamed(
        self, get_serie, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = [
            dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=1)
        ]
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        mock_loguru_info.assert_has_calls(
            [
                call("Starting Renamarr"),
                call("Renaming S01E01"),
                call("Finished Renamarr"),
            ]
        )

        mock_loguru_debug.assert_any_call("Found episodes to be renamed")

        rename_files.assert_called_once_with([1], 1)

    def test_when_multiple_episodes_need_renamed(
        self, get_serie, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = [
            dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=1),
            dict(seasonNumber=1, episodeNumbers=[2], episodeFileId=2),
        ]
        rename_files = mocker.patch.object(SonarrCli, "rename_files")

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        mock_loguru_info.assert_has_calls(
            [
                call("Starting Renamarr"),
                call("Renaming S01E01, S01E02"),
                call("Finished Renamarr"),
            ]
        )
        mock_loguru_debug.assert_any_call("Found episodes to be renamed")

        rename_files.assert_called_once_with([1, 2], 1)

    def test_when_disk_scan_enabled_and_analyze_files_is_not(
        self, get_serie_empty, mock_loguru_warning, mocker
    ) -> None:
        mocker.patch.object(SonarrCli, "request_get").return_value = dict(
            enableMediaInfo=False
        )

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=False,
        ).scan()

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

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=False,
        ).scan()

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan finished successfully"),
            ]
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

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=False,
        ).scan()

        mock_loguru_info.assert_any_call("disk scan failed")
