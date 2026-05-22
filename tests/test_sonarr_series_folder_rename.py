from unittest.mock import call

from pycliarr.api import SonarrCli, SonarrSerieItem

from renamarr.sonarr.services.series_folder_rename import SeriesFolderRename


class TestSeriesFolderRename:
    def test_process_skips_already_correct_series_folder(
        self, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Show")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="Show"))
        request_put = mocker.patch.object(sonarr_cli, "request_put")
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        SeriesFolderRename(sonarr_cli).process([series])

        request_put.assert_not_called()
        send_command.assert_not_called()
        assert (
            call("Processing pending series folder renames")
            not in mock_loguru_debug.mock_calls
        )

    def test_process_batches_series_folder_renames_by_root(
        self, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series_a = SonarrSerieItem(id=1, title="Show A", path="/rootA/OldA")
        series_b = SonarrSerieItem(id=2, title="Show B", path="/rootB/OldB")
        series_c = SonarrSerieItem(id=3, title="Show C", path="/rootA/OldC")
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[dict(path="/rootA"), dict(path="/rootB")],
        )
        mocker.patch.object(sonarr_cli, "request_get").side_effect = [
            dict(folder="NewA"),
            dict(folder="NewB"),
            dict(folder="NewC"),
        ]
        request_put = mocker.patch.object(
            sonarr_cli,
            "request_put",
            side_effect=[mocker.Mock(status_code=200), mocker.Mock(status_code=299)],
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")
        send_command.side_effect = [dict(id=10), dict(id=20)]
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            side_effect=[
                dict(status="completed", result="successful"),
                dict(status="completed", result="successful"),
            ],
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series_a, series_b, series_c])

        mock_loguru_debug.assert_any_call("Processing pending series folder renames")
        request_put.assert_has_calls(
            [
                call(
                    path="/api/v3/series/editor",
                    json_data=dict(
                        rootFolderPath="/rootA",
                        seriesIds=[1, 3],
                        moveFiles=True,
                    ),
                ),
                call(
                    path="/api/v3/series/editor",
                    json_data=dict(
                        rootFolderPath="/rootB",
                        seriesIds=[2],
                        moveFiles=True,
                    ),
                ),
            ]
        )
        get_command.assert_has_calls([call(cid=10), call(cid=20)])
        send_command.assert_has_calls(
            [
                call(dict(name="RescanSeries", priority="high", seriesIds=[1, 3])),
                call(dict(name="RescanSeries", priority="high", seriesIds=[2])),
            ]
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Renaming Series folders for: Show A, Show C"),
                call("Series folder rename successful for series: Show A, Show C"),
                call("Initiated disk scan of updated series"),
                call("disk scan finished successfully"),
                call("Renaming Series folder for: Show B"),
                call("Series folder rename successful for series: Show B"),
                call("Initiated disk scan of updated series"),
                call("disk scan finished successfully"),
            ]
        )

    def test_process_logs_when_series_rescan_fails(
        self, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="failed"),
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of updated series"),
                call("disk scan failed"),
            ]
        )

    def test_process_skips_rescan_when_folder_rename_status_is_unsuccessful(
        self, mock_loguru_error, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=300)
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        SeriesFolderRename(sonarr_cli).process([series])

        send_command.assert_not_called()
        mock_loguru_info.assert_any_call("Renaming Series folder for: Show")
        mock_loguru_error.assert_called_once_with(
            "Series folder rename failed for series: Show: status code 300"
        )
        assert (
            call("Series folder rename successful for series: Show")
            not in mock_loguru_info.mock_calls
        )
        assert (
            call("Initiated disk scan of updated series")
            not in mock_loguru_info.mock_calls
        )

    def test_process_warns_and_skips_series_without_matching_root_folder(
        self, mock_loguru_warning, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/unmatched/Show")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        request_get = mocker.patch.object(sonarr_cli, "request_get")
        request_put = mocker.patch.object(sonarr_cli, "request_put")
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        SeriesFolderRename(sonarr_cli).process([series])

        mock_loguru_warning.assert_called_once_with(
            "Unable to determine matching Sonarr root folder for series path /unmatched/Show"
        )
        request_get.assert_not_called()
        request_put.assert_not_called()
        send_command.assert_not_called()

    def test_process_uses_path_matching_for_overlapping_root_names(
        self, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(
            id=1,
            title="Anime Show",
            path="/data/media/tv-anime/OldName",
        )
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[
                dict(path="/data/media/tv"),
                dict(path="/data/media/tv-anime"),
            ],
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        mock_loguru_debug.assert_any_call("Processing pending series folder renames")
        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data=dict(
                rootFolderPath="/data/media/tv-anime",
                seriesIds=[1],
                moveFiles=True,
            ),
        )
