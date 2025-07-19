from unittest.mock import call

from pycliarr.api import RadarrCli

from radarr_renamarr import RadarrRenamarr


class TestRadarrRenamarr:
    def test_no_movies_returned(
        self, get_movie_empty, mock_loguru_info, mock_loguru_error, mocker
    ) -> None:
        rename_files = mocker.patch.object(RadarrCli, "rename_files")

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        mock_loguru_info.assert_has_calls(
            [call("Starting Renamarr"), call("Finished Renamarr")]
        )
        mock_loguru_error.assert_any_call("Radarr returned empty movie list")

        rename_files.assert_not_called()

    def test_when_movie_does_not_need_renamed(
        self, get_movie, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = []
        _sendCommand = mocker.patch.object(RadarrCli, "_sendCommand")

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        mock_loguru_debug.assert_any_call("Nothing to rename")
        _sendCommand.assert_not_called()

    def test_when_movie_need_renamed(self, get_movie, mocker) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = [
            dict(movieId=1, movieFileId=1)
        ]
        _sendCommand = mocker.patch.object(RadarrCli, "_sendCommand")

        rename_payload = dict(
            name="RenameFiles",
            files=[1],
            movieId=1,
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        _sendCommand.assert_called_once_with(rename_payload)

    def test_when_multiple_movies_need_renamed(self, get_movie, caplog, mocker) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = [
            dict(movieId=1, movieFileId=1),
            dict(movieId=1, movieFileId=2),
        ]
        _sendCommand = mocker.patch.object(RadarrCli, "_sendCommand")

        rename_payload1 = dict(
            name="RenameFiles",
            files=[1],
            movieId=1,
        )
        rename_payload2 = dict(
            name="RenameFiles",
            files=[2],
            movieId=1,
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        _sendCommand.assert_has_calls([call(rename_payload1), call(rename_payload2)])

    def test_when_disk_scan_enabled_and_analyze_files_is_not(
        self, get_movie_empty, mock_loguru_warning, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = dict(
            enableMediaInfo=False
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=True).scan()

        mock_loguru_warning.assert_called_once_with(
            "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
        )

    def test_when_disk_scan_enabled(
        self, get_movie_empty, mock_loguru_info, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = dict(
            enableMediaInfo=True
        )
        mocker.patch.object(RadarrCli, "_sendCommand").return_value = dict(id=1)
        mocker.patch.object(RadarrCli, "get_command").return_value = dict(
            status="completed", result="successful"
        )
        mocker.patch("radarr_renamarr.sleep").return_value = None

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=True).scan()

        assert call("Initiated disk scan of library") in mock_loguru_info.call_args_list
        assert (
            call("disk scan finished successfully") in mock_loguru_info.call_args_list
        )

    def test_when_disk_scan_enabled_and_fails(
        self, get_movie_empty, mock_loguru_info, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = dict(
            enableMediaInfo=True
        )
        mocker.patch.object(RadarrCli, "_sendCommand").return_value = dict(id=1)
        mocker.patch.object(RadarrCli, "get_command").return_value = dict(
            status="completed", result="failed"
        )
        mocker.patch("radarr_renamarr.sleep").return_value = None

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=True).scan()

        assert call("disk scan failed") in mock_loguru_info.call_args_list
